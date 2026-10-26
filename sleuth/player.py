"""A player's run: walking, gathering evidence into a notebook and publishing episodes."""

import logging
import random
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
from sleuth.town import PLACES, START_PLACE, Town, at, neighbours
from sleuth.traits import TRAITS
from sleuth.tutorial import Practice
from sleuth.usage import charging
from sleuth.writer import invents, strangers

log = logging.getLogger(__name__)
# ponytail: a phrase list, not a judge; it only ever swaps a model line for the plain record text.
DENIAL = re.compile(r"\b(can't say|cannot say|couldn't say|didn't see|did not see|never saw|haven't seen|"
                    r"don't know|do not know|no idea|not sure|nothing)\b")


def _denials(text: str) -> set[str]:
    return set(DENIAL.findall(text.lower().replace("\u2019", "'")))


def _plain(text: str) -> str:
    """text with its looks spelled one way: "Gray-haired" reads as "grey hair"."""
    return text.lower().replace("-", " ").replace("gray", "grey").replace("haired", "hair")


def conveys(line: str, records: list[Record]) -> bool:
    """Whether an answer keeps to its records: no denial the records don't make themselves, and every trait a memory
    saw."""
    if not records:
        return True
    hedged = set().union(*(_denials(r.text) for r in records))
    said = _plain(line)
    return not _denials(line) - hedged and all(_plain(v) in said for r in records for v in r.traits.values())


# How a line opening with its teller's name reads in their own voice.
VOICES = ((" says they were ", "I was "), (" says they're ", "I'm "), (" says they saw ", "I saw "), (" says ", ""),
          (" heard from (.+?): ", r"\1 told me: "), (": ", ""))


def voiced(text: str, name: str) -> str:
    """A record or talk line about what name knows, as name says it."""
    for third, first in VOICES:
        said, n = re.subn(rf"^{re.escape(name)}{third}", first, text)
        if n:
            return said.replace(name, "me")
    return text.replace(f"{name} found the ", "I found my ").replace(name, "me")


# ponytail: phrase lists, not judges; they only ever swap a model line for the plain record text.
HEARSAY = re.compile(r"\b(?:wasn't there|was not there|I was told|I'm told|I am told|I heard|I've heard|told me|"
                     r"people say|they say|word is|apparently|so I hear)\b", re.IGNORECASE)
WHEREABOUTS = re.compile(r"\bI(?:'m| am| was| wasn't| was not|'ve been| have been| had been| stayed| went)(?: \w+ly)?"
                         r"(?: not| never)?(?: even)? (?:there|here|home|at|on|in|away|out|nowhere|near|nearby|around|"
                         r"over|by|elsewhere|asleep)\b", re.IGNORECASE)


def _apostrophes(text: str) -> str:
    return text.replace("\u2019", "'")


def first_hand(line: str, records: list[Record], villager: Villager) -> bool:
    """Whether a reply tells the resident's own sighting as theirs, and says where they were only when one of their
    records does."""
    own = [r for r in records if r.holder == villager.id]
    saw = any(r.kind in ("memory", "discovery") for r in own)
    placed = saw or any(WHEREABOUTS.search(voiced(r.text, villager.name)) for r in own)
    line = _apostrophes(line)
    return not (saw and HEARSAY.search(line)) and (placed or not WHEREABOUTS.search(line))


def adds_nothing(line: str, names: set[str]) -> bool:
    """Whether a reply with no facts behind it names no one and gives no time, place, look or whereabouts."""
    lower = line.lower()
    return bool(line) and not (invents(line, "", names) or misdated(line, "") or re.search(r"\d", line)
                               or WHEREABOUTS.search(_apostrophes(line))
                               or any(re.search(rf"\b{re.escape(w)}\b", lower) for w in (*PLACES, *LOOKS)))


def analytics(event: str, **fields) -> None:
    """One line on stdout per countable event, for the host's log search: `analytics <event> key=value ...`."""
    print("analytics", event, *(f"{k}={v}" for k, v in fields.items()))


MAX_QUESTION = 300
MESSAGES_PER_PART = 4
# How many exchanges a thread keeps.
THREAD_KEPT = 40
# A reply with nothing behind it, when the writer's can't be used.
SHRUGS = ("I couldn't tell you, sorry.", "Can't help you there.", "No idea, I'm afraid.", "That's news to me.",
          "I really couldn't say.", "Not something I'd know about.")
LOOKS = tuple(v for values in TRAITS.values() for v in values)
# Hearsay rooted in these is evidence; news-rooted hearsay is only talk.
EVIDENCE_ROOTS = ("memory", "cover")
PODCAST = "A true-crime podcast"
WRONG = "Your episode didn't hold up. The town now believes it, and people are warier of you."
GUIDED_WRONG = "Your episode didn't hold up: the evidence doesn't back it."
HELD = "It holds up. Case closed."
GRADUATED = "That was practice. You're in the real town now."
SKIPPED = f"Tutorial skipped. {GRADUATED}"
RIVAL = "Another podcaster cracked the case first."


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
        # The real town's engine, town and clock while the player is in the practice town.
        self._real = None
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
            "threads": self.threads, "searched": self.searched,
            "tutorial": self.engine.cases.to_state() if self.practising else None,
        }

    def restore(self, state: dict) -> None:
        """Fill the run from a saved state; with no tab open it is idle until its player reconnects."""
        self.place, self.created_at = state["place"], state["created_at"]
        self.notebook = {r["id"]: Record(**r) for r in state["notebook"]}
        self.threads = state["threads"]
        self.searched = state["searched"]
        active_at = state["active_at"]
        self._active_at = None if active_at is None else min(active_at, time.time() - self.config.idle_after_seconds)
        if state["tutorial"] is not None:
            self.begin_tutorial(state["tutorial"])

    @property
    def practising(self) -> bool:
        """Whether the player is in the practice town."""
        return self._real is not None

    def begin_tutorial(self, saved: dict | None = None) -> None:
        """Move into the practice town for a first case of the player's own; saved is its case store, on a restore."""
        practice = Practice(self.engine, self.ids, self.config, self.id, saved)
        self._real = self.engine, self.town, self.game
        self.engine, self.town, self.game = practice, practice.town, practice.game
        self.feed.practising.add(self.id)

    def skip(self) -> str | None:
        """Leave the practice case unsolved for the real town; returns why it could not be done."""
        self.touch()
        file = self.engine.cases.private(self.id) if self.practising else None
        if file is None:
            return "You're not on the tutorial."
        self._graduate(file, None, SKIPPED)
        return None

    def _graduate(self, file: CaseFile, solved_by: str | None, line: str) -> None:
        """Close the practice case and move into the real town, with a clean notebook and feed, told its open case."""
        self.engine.cases.close(file, solved_by)
        self.feed.on_case_closed(file.crime.id, line, player=self.id)
        self.engine, self.town, self.game = self._real
        self._real = None
        self.engine.players.onboarded.add(self.owner)
        self.notebook, self.threads, self.searched, self._talked = {}, {}, [], {}
        self.place = START_PLACE
        self.feed.forget(self.id)
        self.feed.practising.discard(self.id)
        self.engine.cases.brief(self.feed, self.id, self._today())

    def steps(self) -> list[dict] | None:
        """The practice case's checklist, each step with why it matters, done or not, and the person or action it
        needs; None off it."""
        file = self.engine.cases.private(self.id) if self.practising else None
        if file is None:
            return None
        crime = file.crime
        witness = self.town.get(next(r.holder for r in file.records.values() if r.kind == "memory"))
        victim = self.town.get(crime.victim).name
        when = "at night" if crime.phase == "night" else f"in the {crime.phase}"
        return [
            {"text": f"Ask {victim}, the victim, what happened", "why": f"{victim} reported it. Ask what happened.",
             "done": crime.victim in self.threads, "person": crime.victim},
            {"text": f"Ask {witness.name} what they saw",
             "why": f"{witness.name} is usually {at(crime.place)} {when}, when it happened. "
                    "People nearby may have seen something.",
             "done": any(r.kind == "memory" for r in self.notebook.values()), "person": witness.id},
            {"text": f"Search the scene {at(crime.place)}",
             "why": "The culprit may have left something behind. Search where it happened.",
             "done": crime.id in self.searched, "action": "search", "place": crime.place},
            {"text": "Publish an episode naming who did it", "why": "Name who the evidence points to, and cite what backs it.",
             "done": self.id in file.published, "action": "publish"},
        ]

    def _tick(self) -> None:
        """Send the guided case's checklist to the player, if they are on one."""
        if (steps := self.steps()) is not None:
            self.feed.on_steps(steps, player=self.id)

    def connected(self) -> None:
        """A tab opened its feed."""
        if not self.ever_active():
            analytics("visit", owner=self.owner, run=self.id)
        self._sockets += 1
        self.touch()

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
        self._tick()
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

    def _today(self) -> float | None:
        return self.game.time() if self.game else None

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
            return self._seen(file, vid), []
        if kind == "what_happened":
            seen = self._seen(file, vid)
            return (seen, []) if seen else await self._hearsay(file, villager)
        if kind == "who_told_you":
            return await self._hearsay(file, villager)
        if kind == "who_had_reason":
            victim = self.town.get(crime.victim)
            if vid == victim.id:
                known = [v.id for v in self.town.villagers
                         if victim.warmth.get(v.id, 0.0) < 0 or motive_of(v, victim) != "opportunity"]
            else:
                known = [o for o, tie in victim.relationships.items() if tie == "rival"]
            reasons = [self.town.get(o) for o in known if o in self.town and o not in (vid, victim.id)]
            return [self._statement(file, vid, f"{name} says {o.name} has never got on with {victim.name}.", True,
                                    who=o.id) for o in reasons], []
        if kind == "what_do_you_think_of" and about:
            mates = villager.household and about.household == villager.household
            tie = villager.relationships.get(about.id) or ("housemate" if mates else None)
            feeling = warmth_words(villager.warmth.get(about.id, 0.0))
            return [], [f"{about.name} is my {tie}, and we are on {feeling} terms."] if tie else []
        return [], []

    def _seen(self, file: CaseFile, vid: str) -> list[Record]:
        """What the resident saw or found of the case; a trusting witness recalls more."""
        crime = file.crime
        records = [replace(r) for r in file.records.values() if r.kind in ("memory", "discovery") and r.holder == vid]
        if self.engine.reputation.get(vid, self.id) >= self.config.trusted_at:
            culprit = self.town.get(crime.culprit).traits
            records = [recall_more(crime, r, culprit) if r.kind == "memory" else r for r in records]
        return records

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
                talk.append(f"{heard.speaker_name} told me: {self._told(retime(heard.text, WHEN), crime)}")
        return [], talk

    async def _phrase(self, villager: Villager, file: CaseFile, question: str, thread: list[dict],
                      records: list[Record], talk: list[str]) -> str:
        """The resident's reply from the writer, or a plain line from the records when it fails, doesn't convey them
        all, names someone they don't or gives a time they and the case don't; with nothing known, a shrug."""
        crime = file.crime
        records = [replace(r, text=self._told(r.text, crime)) for r in records]
        texts = [r.text for r in records] + talk
        if not texts:
            return await self._shrug(villager, file, question, thread)
        if self.writer is not None:
            try:
                case = self._told(crime.text, crime)
                known = neighbours(self.town, villager, case)
                now = self.game.now() if self.game else ""
                line = await self.writer.reply(villager, case, question, exchanges(thread), texts, known, now,
                                               when(crime, self._today()))
                allowed = " ".join([villager.name, question, *texts, *known, *(t["line"] for t in thread)])
                firsts = {v.name.split()[0] for v in self.town.villagers}
                if (line and conveys(line, records) and first_hand(line, records, villager)
                        and not strangers(line, allowed, firsts)
                        and not misdated(line, " ".join([case, *texts]))):
                    return line
            except Exception:
                log.exception("reply from %s failed", villager.id)
        return " ".join([*(f"I saw it myself. {r.text}" if r.kind == "memory" else voiced(r.text, villager.name)
                           for r in records), *talk])

    async def _shrug(self, villager: Villager, file: CaseFile, question: str, thread: list[dict]) -> str:
        """The resident's reply when they know nothing for the question: the writer's, if it adds nothing, else a
        stock line. Names the question itself used may be echoed."""
        if self.writer is not None:
            try:
                line = await self.writer.reply(villager, self._told(file.crime.text, file.crime), question,
                                               exchanges(thread), [])
                asked = set(re.findall(r"\w+", question.lower()))
                names = {w for v in self.town.villagers for w in v.name.split() if w.lower() not in asked}
                if adds_nothing(line, names):
                    return line
            except Exception:
                log.exception("reply from %s failed", villager.id)
        return random.choice(SHRUGS)

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
        self._tick()
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
        self._tick()
        return None

    def _keepers(self) -> list[str]:
        """Who keeps this place's records: those who live on it, for a street, or work at it."""
        routine = self.engine.routine
        return [v.id for v in self.town.villagers
                if v.home == self.place or (routine is not None and routine.place(v.id, "morning") == self.place)]

    async def publish(self, culprit_id: str, record_ids: list[str]) -> str | None:
        """Publish an episode naming culprit_id on the evidence cited; returns why it could not be done.

        Code judges it. A right one closes the case and wins the town's regard; a wrong one spreads the accusation
        and costs it. The town always hears it. The practice case closes either way, moving no regard, and the player
        moves into the real town.
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
        accused, victim = self.town.get(culprit_id), self.town.get(crime.victim)
        held = holds(crime, culprit_id, accused.traits, [self.notebook[i] for i in record_ids])
        if crime.owner:
            verdict = HELD if held else f"{GUIDED_WRONG} It was {self.town.get(crime.culprit).name}."
            self.feed.on_episode(crime.id, accused.name, held, by=self.id, cited=len(record_ids), verdict=verdict,
                                 player=self.id)
            self._graduate(file, self.id if held else None, f"{verdict} {GRADUATED}")
            return None
        everyone = [v.id for v in self.town.villagers]
        named = f"{accused.name} {TEMPLATES[crime.template][0]} {victim.name}'s {crime.item}"
        if held:
            for rival in self.engine.players:
                if rival is not self and any(r.case == crime.id for r in rival.notebook.values()):
                    self.feed.say(RIVAL, player=rival.id)
        self.feed.on_episode(crime.id, accused.name, held, by=self.id, cited=len(record_ids),
                             verdict=HELD if held else WRONG)
        if held:
            self.engine.cases.close(file, self.id)
            self.feed.on_case_closed(crime.id, "")
            reputation.nudge_all(self.id, self.config.reputation_right, everyone)
            text = f"{named}, and the evidence holds up."
        else:
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
