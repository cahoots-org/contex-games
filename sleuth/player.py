"""A player's run: walking, looking around, gathering evidence into a notebook and publishing episodes."""

import asyncio
import logging
import re
import time
from dataclasses import asdict, replace

from sleuth.alibi import claim, household_word
from sleuth.case import TEMPLATES, Record, clock_at, recall_more, record_json, when
from sleuth.cases import CaseFile
from sleuth.config import Config
from sleuth.episode import MAX_CITED, holds
from sleuth.facts import audible
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.town import PLACES, START_PLACE, STREETS, Town, at, neighbours, place_name
from sleuth.usage import charging

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


LISTEN_OPENING = 5
LISTEN_LOOKBACK_DAYS = 1 / 4
ALREADY_LISTENING = "You just looked around."
# Hearsay rooted in these is evidence; news-rooted hearsay is only talk.
EVIDENCE_ROOTS = ("memory", "cover")
PODCAST = "A true-crime podcast"
WRONG = "Your episode didn't hold up. The town now believes it, and people are warier of you."
GUIDED_WRONG = "Your episode didn't hold up: the evidence doesn't back it."
RIVAL = "Another podcaster cracked the case first."
GUIDE = (
    "A case just for you: {case}. Watch the neighborhood app, then walk to {place} and {then}.",
    "Your notebook keeps what people tell you. Witnesses describe what they saw, never a name. Pull records where a "
    "place has a camera or keeps logs.",
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
        # When the running listen ends, or None when the player is not listening.
        self._listen_until: float | None = None
        # The last answer from each resident per case, and the part of the day each resident was last interviewed.
        self._answers: dict[tuple[str, str], str] = {}
        self._interviewed: dict[str, tuple[int, str]] = {}
        self.created_at = time.time()
        # Open tabs, and when the player last acted or closed one; None until they first do.
        self._sockets = 0
        self._active_at: float | None = None

    def to_state(self) -> dict:
        """The run's durable fields as plain JSON; listens, tabs and tasks are left out."""
        return {
            "id": self.id, "owner": self.owner, "place": self.place, "created_at": self.created_at,
            "active_at": self._active_at, "notebook": [asdict(r) for r in self.notebook.values()],
            "guide_step": self.guide_step,
        }

    def restore(self, state: dict) -> None:
        """Fill the run from a saved state; with no tab open it is idle until its player reconnects."""
        self.place, self.created_at = state["place"], state["created_at"]
        self.notebook = {r["id"]: Record(**r) for r in state["notebook"]}
        self.guide_step = state["guide_step"]
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
                there = any(r.kind == "memory" and self.town.place_of(r.holder) == crime.place
                            for r in case.records.values())
                self._guide(0, case=crime.text.rstrip("."), place=place_name(crime.place) if crime.place in STREETS else f"the {crime.place}",
                            then="interview whoever is there" if there else "pull the records there")
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

    def listen(self) -> str | None:
        """Show the last few lines said where the player stands this part of the day; returns why it could not be done.

        The player can look again after listen_seconds or once they walk.
        """
        self.touch()
        if self.listening():
            return ALREADY_LISTENING
        now = time.time()
        until = self._listen_until = now + self.config.listen_seconds
        since = now - self.config.day_seconds * LISTEN_LOOKBACK_DAYS
        heard = [u for u in self.engine.facts.recent(self.place, since) if audible(u)]
        self.feed.on_listen(self.place, heard[-LISTEN_OPENING:], until, player=self.id)
        self._track(asyncio.create_task(self._end_listen(until)))
        return None

    def listening(self) -> bool:
        """Whether the player is listening now."""
        return self._listen_until is not None

    async def _end_listen(self, until: float) -> None:
        await asyncio.sleep(self.config.listen_seconds)
        if self._listen_until == until:
            self._stop_listening()

    def _stop_listening(self) -> None:
        if self._listen_until is None:
            return
        self._listen_until = None
        self.feed.on_listen_end(self.place, player=self.id)

    def _move(self, place: str) -> None:
        self._stop_listening()
        self.place = place
        self.feed.on_place(place, player=self.id)

    async def interview(self, vid: str) -> str | None:
        """Interview the resident about the open case; returns why it could not be done, if it couldn't.

        Once per resident per part of the day. New evidence goes in the notebook, and the culprit hears a podcaster
        is asking around. With nothing new the resident repeats their last answer, so the writer isn't called. The
        model calls are charged to this player.
        """
        self.touch()
        with charging(self.id):
            return await self._interview(vid)

    async def _interview(self, vid: str) -> str | None:
        if vid not in self.town:
            return "No one in town has that id."
        file = self.engine.cases.for_player(self.id) if self.engine.cases else None
        if file is None:
            return "There's no open case."
        villager = self.town.get(vid)
        place = self.town.place_of(vid)
        if place != self.place:
            return f"{villager.name} is {at(place)}. Walk there to talk to them."
        if self.engine.reputation.get(vid, self.id) < self.config.guarded_at:
            return Refusal(f"{villager.name} won't talk to you.")
        part = (self.game.day, self.game.phase) if self.game else None
        if part and self._interviewed.get(vid) == part:
            return Refusal(f"{villager.name} has nothing more to say until later.")
        found, talk = await self._gather(file, villager)
        seen = {(r.kind, r.holder, r.text) for r in self.notebook.values() if r.case == file.crime.id}
        new = []
        for r in found:
            if (r.kind, r.holder, r.text) not in seen:
                seen.add((r.kind, r.holder, r.text))
                r.id = r.id or self.ids.next("r")
                self.notebook[r.id] = r
                new.append(r)
        key = (file.crime.id, vid)
        if new or key not in self._answers:
            self._answers[key] = await self._phrase(villager, file, found, talk)
        line = self._answers[key]
        if part:
            self._interviewed[vid] = part
        self.feed.on_interview(vid, villager.name, line, [record_json(r, self.town) for r in new], player=self.id)
        self._guide(1)
        try:
            await self.engine.press(file)
        except Exception:
            log.exception("pressing the culprit of %s failed", file.crime.id)
        return None

    async def _gather(self, file: CaseFile, villager: Villager) -> tuple[list[Record], list[str]]:
        """What the resident can give: their memory, their claim, their housemates' whereabouts and the best hearsay
        as records, and news-rooted hearsay as talk."""
        crime, vid, name = file.crime, villager.id, villager.name
        records = [replace(r) for r in file.records.values() if r.kind == "memory" and r.holder == vid]
        if self.engine.reputation.get(vid, self.id) >= self.config.trusted_at:
            culprit = self.town.get(crime.culprit).traits
            records = [recall_more(crime, r, culprit) for r in records]

        def statement(text: str, sound: bool, source: str | None = None, who: str | None = None) -> Record:
            return Record("", crime.id, "statement", self.place, self._clock(), text, vid, who=who, sound=sound,
                          utterance=source, day=self.game.day if self.game else 0)

        places, sound = claim(file, vid, self.engine.routine)
        if places:
            records.append(statement(f"{name} says they were {' then '.join(at(p) for p in places)} {when(crime.phase)}.",
                                     sound))
        for mate in self.town.villagers:
            try:
                word = await household_word(self.engine.jev, file, villager, mate)
            except Exception:
                log.exception("household word from %s failed", vid)
                continue
            if word:
                records.append(statement(f"{name}: {word[0]}", word[1], who=mate.id))
        talk = []
        for m in await self.engine.recall_heard(vid, crime.text):
            if (heard := self.engine.facts.get(m.data.get("id"))) is None:
                continue
            root = self.lineage.root(heard.id)
            rooted = self.engine.cases.root_kind(root)
            if rooted is None or rooted[0] is not file:
                continue
            if rooted[1] in EVIDENCE_ROOTS:
                source = next((r.id for r in file.records.values() if r.utterance == root), None)
                records.append(statement(f"{name} heard from {heard.speaker_name}: {heard.text}",
                                         rooted[1] == "memory", source))
                break
            if rooted[1] == "news" and not talk:
                talk.append(f"{heard.speaker_name}: {heard.text}")
        return records, talk

    async def _phrase(self, villager: Villager, file: CaseFile, records: list[Record], talk: list[str]) -> str:
        """The resident's answer from the writer, or a plain line from the records when it fails or doesn't convey
        them all."""
        texts = [r.text for r in records]
        if self.writer is not None:
            try:
                line = await self.writer.answer(
                    villager, file.crime.text, texts + talk, neighbours(self.town, villager, file.crime.text),
                )
                if line and conveys(line, records):
                    return line
            except Exception:
                log.exception("answer for %s failed", villager.id)
        if said := texts or talk[:1]:
            return f"{villager.name} says: {' '.join(said)}"
        return f"{villager.name} doesn't know anything about it."

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
        for r in found:
            self.notebook[r.id] = r
        self.feed.on_pulled(self.place, [record_json(r, self.town) for r in found], player=self.id)
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
        self.feed.on_episode(crime.id, accused.name, held, player=crime.owner)
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
                self.feed.say(WRONG, player=self.id)
            else:
                self.feed.say(GUIDED_WRONG, player=self.id)
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
