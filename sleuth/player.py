"""A player's run: walking, gathering evidence into a notebook and publishing episodes."""

import asyncio
import logging
import re
import time
from dataclasses import asdict, replace

from sleuth.alibi import claim, household_word
from sleuth.case import (
    WHEN, TEMPLATES, Crime, Record, clock_at, misdated, motive_of, recall_more, record_json, retime, told, when,
)
from sleuth.cases import CaseFile
from sleuth.config import Config
from sleuth.decide import warmth_words
from sleuth.episode import MAX_CITED, holds
from sleuth.game import Game
from sleuth.interview import Route, exchanges, route
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.town import PLACES, START_PLACE, STREETS, Town, at, neighbours, place_name
from sleuth.usage import charging
from sleuth.writer import strangers

log = logging.getLogger(__name__)
# ponytail: a phrase list, not a judge; it only ever swaps a model line for the plain record text.
DENIAL = re.compile(r"\b(can't say|cannot say|couldn't say|didn't see|did not see|never saw|haven't seen|"
                    r"don't know|do not know|no idea|not sure|nothing)\b")


def _denials(text: str) -> set[str]:
    return set(DENIAL.findall(text.lower().replace("\u2019", "'")))


def conveys(line: str, records: list[Record]) -> bool:
    """Whether an answer keeps to its records: no denial the records don't make themselves, and every trait a memory
    saw."""
    if not records:
        return True
    hedged = set().union(*(_denials(r.text) for r in records))
    said = line.lower()
    return not _denials(line) - hedged and all(value in said for r in records for value in r.traits.values())


def analytics(event: str, **fields) -> None:
    """One line on stdout per countable event, for the host's log search: `analytics <event> key=value ...`."""
    print("analytics", event, *(f"{k}={v}" for k, v in fields.items()))


MAX_QUESTION = 300
MESSAGES_PER_PART = 4
# How many exchanges a thread keeps.
THREAD_KEPT = 40
UNKNOWN = "I wouldn't know about that."
# Hearsay rooted in these is evidence; news-rooted hearsay is only talk.
EVIDENCE_ROOTS = ("memory", "cover")
PODCAST = "A true-crime podcast"
WRONG = "Your episode didn't hold up. The town now believes it, and people are warier of you."
GUIDED_WRONG = "Your episode didn't hold up: the evidence doesn't back it."
HELD = "It holds up. Case closed."
RIVAL = "Another podcaster cracked the case first."
GUIDE = (
    "This one's yours. {go} to {place} to search the scene and pull the records there.",
    "Your notebook keeps what people tell you. Witnesses describe what they saw, never a name. Ask anyone where they "
    "were {when}, or who'd have a reason. Pull records where a place has a camera or keeps logs, and search the "
    "crime scene once for anything left behind.",
    "When the evidence points to one person, publish an episode. Name them and cite what backs it up.",
    "The town's open case is yours to crack too. Other podcasters are on it, and the first episode that holds up wins.",
)


class Refusal(str):
    """A resident turning the podcaster away."""


class Player:
    def __init__(
        self, engine, town: Town, lineage: Lineage, ids: Ids, feed, config: Config, writer=None, game: Game | None = None,
        *, player_id: str, owner: str | None = None,
    ):
        self.id = player_id
        # The person behind this run, across runs.
        self.owner = player_id if owner is None else owner
        self.engine = engine
        self.town = town
        self.lineage = lineage
        self.ids = ids
        self.feed = feed
        self.config = config
        self.writer = writer
        self.game = game
        self.place = START_PLACE
        self.notebook: dict[str, Record] = {}
        # The next GUIDE line to send.
        self.guide_step = 0
        self._starting = False
        self._tasks: set[asyncio.Task] = set()
        # Each resident's conversation with the player, oldest first, and how many messages the player sent each
        # resident in which part of the day.
        self.threads: dict[str, list[dict]] = {}
        # The cases whose crime place the player has searched.
        self.searched: list[str] = []
        self._talked: dict[str, tuple[tuple[int, str] | None, int]] = {}
        self.created_at = time.time()
        # Open tabs, and when the player last acted or closed one; None until they first do.
        self._sockets = 0
        self._active_at: float | None = None

    def to_state(self) -> dict:
        """The run's durable fields as plain JSON; tabs and tasks are left out."""
        return {
            "id": self.id, "owner": self.owner, "place": self.place, "created_at": self.created_at,
            "active_at": self._active_at, "notebook": [asdict(r) for r in self.notebook.values()],
            "guide_step": self.guide_step, "threads": self.threads, "searched": self.searched,
        }

    def restore(self, state: dict) -> None:
        """Fill the run from a saved state; with no tab open it is idle until its player reconnects."""
        self.place, self.created_at = state["place"], state["created_at"]
        self.notebook = {r["id"]: Record(**r) for r in state["notebook"]}
        self.guide_step = state["guide_step"]
        self.threads = state["threads"]
        self.searched = state["searched"]
        active_at = state["active_at"]
        self._active_at = None if active_at is None else min(active_at, time.time() - self.config.idle_after_seconds)

    async def start(self) -> None:
        """Open a guided first case for a new, not yet onboarded owner while the town is awake, and tell them."""
        players = self.engine.players
        try:
            if self.owner in players.onboarded or players.resting():
                return
            if case := await self.engine.cases.open_guided(self.engine, self.id, self.game.day, self.game.phase):
                crime = case.crime
                witness = next((r.holder for r in case.records.values() if r.kind == "memory"), None)
                go = (f"Ask {self.town.get(witness).name} what they saw; you can reach anyone from anywhere. Then go"
                      if witness else "Go")
                self._guide(0, go=go, place=place_name(crime.place) if crime.place in STREETS else f"the {crime.place}")
        except Exception:
            log.exception("opening a guided case for %s failed", self.id)
        finally:
            self._starting = False

    def _guide(self, step: int, **fields) -> None:
        """Send GUIDE[step] to the player when it is the next one due."""
        if self.guide_step == step:
            self.guide_step += 1
            self.feed.on_guide(GUIDE[step].format(**fields), player=self.id)

    def connected(self) -> None:
        """A tab opened its feed."""
        if not self.ever_active():
            analytics("visit", owner=self.owner, run=self.id)
        self._sockets += 1
        self.touch()
        if self.guide_step == 0 and not self._starting and self.engine.cases is not None and self.game is not None:
            self._starting = True
            self._track(asyncio.create_task(self.start()))

    def disconnected(self) -> None:
        """A tab closed its feed."""
        self._sockets -= 1
        self.touch()

    def touch(self) -> None:
        """The player did something."""
        self._active_at = time.time()

    def ever_active(self) -> bool:
        return self._active_at is not None

    def active(self) -> bool:
        """Whether a tab is open, or the player acted or closed one within idle_after_seconds."""
        return self._sockets > 0 or (
            self._active_at is not None and time.time() - self._active_at < self.config.idle_after_seconds
        )

    def walk(self, place: str) -> str | None:
        """Move to place for free; returns why it could not be done, if it couldn't."""
        self.touch()
        if place not in PLACES:
            return f"There's no {place} here. Try one of: {', '.join(PLACES)}."
        if place == self.place:
            return f"You're already {at(place)}."
        self._move(place)
        return None

    def _move(self, place: str) -> None:
        self.place = place
        self.feed.on_place(place, player=self.id)

    async def interview(self, vid: str, question: str) -> str | None:
        """Ask the resident a question about the open case; returns why it could not be done, if it couldn't.

        Jev routes the question and code answers from what the resident knows; Haiku phrases the reply. A few
        messages per resident per part of the day. New evidence goes in the notebook, and the culprit hears a
        podcaster is asking around. The model calls are charged to this player.
        """
        self.touch()
        with charging(self.id):
            return await self._interview(vid, question.strip())

    async def _interview(self, vid: str, question: str) -> str | None:
        if vid not in self.town:
            return "No one in town has that id."
        if not question:
            return "Type a question."
        if len(question) > MAX_QUESTION:
            return f"Keep your question under {MAX_QUESTION} characters."
        file = self.engine.cases.for_player(self.id) if self.engine.cases else None
        if file is None:
            return "There's no open case."
        villager = self.town.get(vid)
        if self.engine.reputation.get(vid, self.id) < self.config.guarded_at:
            return Refusal(f"{villager.name} won't talk to you.")
        part = (self.game.day, self.game.phase) if self.game else None
        talked_in, said = self._talked.get(vid, (part, 0))
        said = said if talked_in == part else 0
        if part and said >= MESSAGES_PER_PART:
            return Refusal(f"{villager.name}: Let's talk later.")
        self._talked[vid] = (part, said + 1)
        thread = self.threads.setdefault(vid, [])
        try:
            case = self._told(file.crime.text, file.crime)
            routed = await route(self.engine.jev, file, villager, self.town, question, thread, case)
        except Exception:
            log.exception("routing a question to %s failed", vid)
            routed = None
        found, talk = await self._known(file, villager, routed) if routed else ([], [])
        seen = {(r.kind, r.holder, r.text) for r in self.notebook.values() if r.case == file.crime.id}
        new = []
        for r in found:
            if (r.kind, r.holder, r.text) not in seen:
                seen.add((r.kind, r.holder, r.text))
                r.id = r.id or self.ids.next("r")
                self.notebook[r.id] = r
                new.append(r)
        line = await self._phrase(villager, file, question, thread, found, talk)
        thread.append({"question": question, "line": line, "records": [r.id for r in new]})
        del thread[:-THREAD_KEPT]
        self.feed.on_interview(vid, villager.name, question, line, [self._record_json(r) for r in new],
                               case_id=file.crime.id, player=self.id)
        self._guide(1, when=when(file.crime, self._today()))
        try:
            await self.engine.press(file, self.id)
        except Exception:
            log.exception("pressing the culprit of %s failed", file.crime.id)
        return None

    def thread_json(self, vid: str) -> list[dict]:
        """What the player sees of their conversation with the resident: each question, reply and what it added."""
        return [{"question": t["question"], "line": t["line"],
                 "records": [self._record_json(self.notebook[i]) for i in t["records"] if i in self.notebook]}
                for t in self.threads.get(vid, [])]

    def _record_json(self, r: Record) -> dict:
        """What the player sees of a notebook record today."""
        file = self.engine.cases.files.get(r.case) if self.engine.cases else None
        return record_json(r, self.town, file.crime if file else None, self._today())

    def _today(self) -> int | None:
        return self.game.day if self.game else None

    def _told(self, text: str, crime: Crime) -> str:
        return told(text, crime, self._today())

    def _statement(self, file: CaseFile, vid: str, text: str, sound: bool, source: str | None = None,
                   who: str | None = None) -> Record:
        return Record("", file.crime.id, "statement", self.place, self._clock(), text, vid, who=who, sound=sound,
                      utterance=source, day=self.game.day if self.game else 0)

    async def _known(self, file: CaseFile, villager: Villager, routed: Route) -> tuple[list[Record], list[str]]:
        """What the resident knows for the routed question: records for evidence, and talk that is only phrased."""
        crime, vid, name, routine = file.crime, villager.id, villager.name, self.engine.routine
        kind, about = routed.kind, self.town.get(routed.who) if routed.who else None
        if kind == "where_were_you" and routed.when == crime.phase:
            places, sound = claim(file, vid, routine)
            text = f"{name} says they were {' then '.join(at(p) for p in places)} {WHEN}."
            return [self._statement(file, vid, text, sound)] if places else [], []
        if kind == "where_were_you":
            usual = routine.place(vid, routed.when) if routine else None
            text = f"{name} says they're usually {at(usual)} in the {routed.when}."
            return [self._statement(file, vid, text, True)] if usual else [], []
        if kind == "where_was" and about:
            if word := household_word(file, villager, about, routed.words.get(about.id)):
                return [self._statement(file, vid, f"{name}: {word[0]}", word[1], who=about.id)], []
            theirs = file.whereabouts.get(about.id, [])
            met = [p for p in file.whereabouts.get(vid, []) if p in theirs and p != crime.place]
            if not met:
                return [], []
            text = f"{name} says they saw {about.name} {at(met[0])} {WHEN}."
            return [self._statement(file, vid, text, True, who=about.id)], []
        if kind == "what_did_you_see":
            records = [replace(r) for r in file.records.values()
                       if r.kind in ("memory", "discovery") and r.holder == vid]
            if self.engine.reputation.get(vid, self.id) >= self.config.trusted_at:
                culprit = self.town.get(crime.culprit).traits
                records = [recall_more(crime, r, culprit) if r.kind == "memory" else r for r in records]
            return records, []
        if kind == "who_told_you":
            return await self._hearsay(file, villager)
        if kind == "who_had_reason":
            victim = self.town.get(crime.victim)
            known = [*villager.relationships, *(v.id for v in self.town.villagers
                                                if villager.household and v.household == villager.household)]
            reasons = [self.town.get(o) for o in dict.fromkeys(known)
                       if o in self.town and o not in (vid, victim.id) and motive_of(self.town.get(o), victim) != "opportunity"]
            return [self._statement(file, vid, f"{name} says {o.name} has never got on with {victim.name}.", True,
                                    who=o.id) for o in reasons], []
        if kind == "what_do_you_think_of" and about:
            mates = villager.household and about.household == villager.household
            tie = villager.relationships.get(about.id) or ("housemate" if mates else None)
            feeling = warmth_words(villager.warmth.get(about.id, 0.0))
            return [], [f"{about.name} is {name}'s {tie}, and they are on {feeling} terms."] if tie else []
        return [], []

    async def _hearsay(self, file: CaseFile, villager: Villager) -> tuple[list[Record], list[str]]:
        """The best case hearsay the resident heard: a record when it traces to evidence, else news as talk."""
        crime, vid, name = file.crime, villager.id, villager.name
        talk = []
        for m in await self.engine.recall_heard(vid, self._told(crime.text, crime)):
            if (heard := self.engine.facts.get(m.data.get("id"))) is None:
                continue
            root = self.lineage.root(heard.id)
            rooted = self.engine.cases.root_kind(root)
            if rooted is None or rooted[0] is not file:
                continue
            if rooted[1] in EVIDENCE_ROOTS:
                source = next((r.id for r in file.records.values() if r.utterance == root), None)
                text = f"{name} heard from {heard.speaker_name}: {retime(heard.text, WHEN)}"
                return [self._statement(file, vid, text, rooted[1] == "memory", source)], []
            if rooted[1] == "news" and not talk:
                talk.append(f"{heard.speaker_name}: {self._told(retime(heard.text, WHEN), crime)}")
        return [], talk

    async def _phrase(self, villager: Villager, file: CaseFile, question: str, thread: list[dict],
                      records: list[Record], talk: list[str]) -> str:
        """The resident's reply from the writer, or a plain line from the records when it fails, doesn't convey them
        all, names someone they don't or gives a time they and the case don't; with nothing known, that they wouldn't
        know."""
        crime = file.crime
        records = [replace(r, text=self._told(r.text, crime)) for r in records]
        texts = [r.text for r in records] + talk
        if not texts:
            return UNKNOWN
        if self.writer is not None:
            try:
                case = self._told(crime.text, crime)
                known = neighbours(self.town, villager, case)
                now = self.game.now() if self.game else ""
                line = await self.writer.reply(villager, case, question, exchanges(thread), texts, known, now,
                                               when(crime, self._today()))
                allowed = " ".join([villager.name, *texts, *known, *(t["line"] for t in thread)])
                firsts = {v.name.split()[0] for v in self.town.villagers}
                if (line and conveys(line, records) and not strangers(line, allowed, firsts)
                        and not misdated(line, " ".join([case, *texts]))):
                    return line
            except Exception:
                log.exception("reply from %s failed", villager.id)
        return f"{villager.name} says: {' '.join(texts)}"

    def pull(self) -> str | None:
        """Copy the open case's footage and logs at this place into the notebook; returns why it could not be done."""
        self.touch()
        file = self.engine.cases.for_player(self.id) if self.engine.cases else None
        if file is None:
            return "There's no open case."
        if max((self.engine.reputation.get(vid, self.id) for vid in self._keepers()), default=0.0) < self.config.guarded_at:
            return "No one who keeps the records here will share them with you."
        found = [replace(r) for r in file.records.values() if r.kind in ("clip", "log") and r.place == self.place]
        if not found:
            return "There's no footage or log for the case here."
        new = [r for r in found if r.id not in self.notebook]
        for r in new:
            self.notebook[r.id] = r
        self.feed.on_pulled(self.place, [self._record_json(r) for r in new], case_id=file.crime.id,
                            player=self.id)
        self._guide(2)
        return None

    def search(self) -> str | None:
        """Search the open case's crime place, once per case, adding what was left there to the notebook; returns
        why it could not be done."""
        self.touch()
        file = self.engine.cases.for_player(self.id) if self.engine.cases else None
        if file is None:
            return "There's no open case."
        if self.place != file.crime.place:
            return "There's nothing to search for here."
        if file.crime.id in self.searched:
            return "You've already searched here."
        self.searched.append(file.crime.id)
        found = [replace(r) for r in file.records.values() if r.kind == "clue"]
        for r in found:
            self.notebook[r.id] = r
        self.feed.on_searched(self.place, [self._record_json(r) for r in found], case_id=file.crime.id,
                              player=self.id)
        self._guide(2)
        return None

    def _keepers(self) -> list[str]:
        """Who keeps this place's records: those who live on it, for a street, or work at it."""
        routine = self.engine.routine
        return [v.id for v in self.town.villagers
                if v.home == self.place or (routine is not None and routine.place(v.id, "morning") == self.place)]

    async def publish(self, culprit_id: str, record_ids: list[str]) -> str | None:
        """Publish an episode naming culprit_id on the evidence cited; returns why it could not be done.

        Code judges it. A right one closes the case and wins the town's regard; a wrong one spreads the accusation
        and costs it. A guided case closes either way and moves no regard. The town always hears it.
        """
        self.touch()
        file = self._case()
        if file is None:
            return "There's no open case."
        if file.state != "open":
            return "That case is closed."
        if self.id in file.published:
            return "You've already published on this case."
        if not 1 <= len(record_ids) <= MAX_CITED:
            return f"Cite between 1 and {MAX_CITED} notebook entries."
        if any(i not in self.notebook for i in record_ids):
            return "Cite only entries from your notebook."
        if len(set(record_ids)) != len(record_ids):
            return "Cite each entry once."
        if any(self.notebook[i].case != file.crime.id for i in record_ids):
            return "Cite only evidence from this case."
        if culprit_id not in self.town:
            return "No one in town has that id."
        file.published.append(self.id)
        crime, reputation = file.crime, self.engine.reputation
        everyone = [v.id for v in self.town.villagers]
        accused, victim = self.town.get(culprit_id), self.town.get(crime.victim)
        named = f"{accused.name} {TEMPLATES[crime.template][0]} {victim.name}'s {crime.item}"
        held = holds(crime, culprit_id, accused.traits, [self.notebook[i] for i in record_ids])
        if held and crime.owner is None:
            for rival in self.engine.players:
                if rival is not self and any(r.case == crime.id for r in rival.notebook.values()):
                    self.feed.say(RIVAL, player=rival.id)
        verdict = HELD if held else GUIDED_WRONG if crime.owner else WRONG
        self.feed.on_episode(crime.id, accused.name, held, by=self.id, cited=len(record_ids), verdict=verdict,
                             player=crime.owner)
        if held or crime.owner:
            self.engine.cases.close(file, self.id if held else None)
            self.feed.on_case_closed(crime.id, "", player=crime.owner)
        if crime.owner:
            self.engine.players.onboarded.add(self.owner)
        if held:
            if not crime.owner:
                reputation.nudge_all(self.id, self.config.reputation_right, everyone)
            text = f"{named}, and the evidence holds up."
        else:
            if not crime.owner:
                reputation.nudge_all(self.id, self.config.reputation_wrong, everyone)
                reputation.nudge(culprit_id, self.id, self.config.reputation_accused)
            text = f"{named}."
        u = Utterance(self.ids.next("u"), "podcast", PODCAST, self.place, text, None, "reported")
        file.roots[u.id] = "episode"
        household = [v.id for v in self.town.villagers if accused.household and v.household == accused.household]
        listeners = [*(v.id for v in self.town.present(self.place)), culprit_id, *household]
        try:
            await self.engine.deliver(u, list(dict.fromkeys(listeners)))
        except Exception:
            log.exception("delivering the episode on %s failed", crime.id)
        self._guide(3)
        return None

    def _case(self) -> CaseFile | None:
        """The player's open case, else the case of their latest notebook entry."""
        cases = self.engine.cases
        if cases is None:
            return None
        latest = next(reversed(self.notebook.values()), None)
        return cases.for_player(self.id) or (cases.files.get(latest.case) if latest else None)

    def _clock(self) -> str:
        """The game's time of day, like "9:40am"; empty without a game."""
        return clock_at(int(360 + self.game.clock()["fraction"] * 1440)) if self.game else ""

    def close(self) -> None:
        """Cancel every background task this player started."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    def _track(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
