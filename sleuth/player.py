"""A player's run: walking, looking around and interviewing residents into a notebook."""

import asyncio
import logging
import time
from dataclasses import asdict

from sleuth.alibi import claim, household_word
from sleuth.case import Record, at, clock_at, record_json, when
from sleuth.cases import CaseFile
from sleuth.config import Config
from sleuth.facts import audible
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.models import Villager
from sleuth.town import PLACES, START_PLACE, Town, neighbours
from sleuth.usage import charging

log = logging.getLogger(__name__)


def analytics(event: str, **fields) -> None:
    """One line on stdout per countable event, for the host's log search: `analytics <event> key=value ...`."""
    print("analytics", event, *(f"{k}={v}" for k, v in fields.items()))


LISTEN_OPENING = 5
LISTEN_LOOKBACK_DAYS = 1 / 4
ALREADY_LISTENING = "You just looked around."
# Hearsay rooted in these is evidence; news-rooted hearsay is only talk.
EVIDENCE_ROOTS = ("memory", "cover")


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
        self._tasks: set[asyncio.Task] = set()
        # When the running listen ends, or None when the player is not listening.
        self._listen_until: float | None = None
        self.created_at = time.time()
        # Open tabs, and when the player last acted or closed one; None until they first do.
        self._sockets = 0
        self._active_at: float | None = None

    def to_state(self) -> dict:
        """The run's durable fields as plain JSON; listens, tabs and tasks are left out."""
        return {
            "id": self.id, "owner": self.owner, "place": self.place, "created_at": self.created_at,
            "active_at": self._active_at, "notebook": [asdict(r) for r in self.notebook.values()],
        }

    def restore(self, state: dict) -> None:
        """Fill the run from a saved state; with no tab open it is idle until its player reconnects."""
        self.place, self.created_at = state["place"], state["created_at"]
        self.notebook = {r["id"]: Record(**r) for r in state["notebook"]}
        active_at = state["active_at"]
        self._active_at = None if active_at is None else min(active_at, time.time() - self.config.idle_after_seconds)

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
            return f"You're already at the {place}."
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

        New evidence goes in the notebook, and the culprit hears a podcaster is asking around. The model calls are
        charged to this player.
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
            return f"{villager.name} is at the {place}. Walk there to talk to them."
        if self.engine.reputation.get(vid, self.id) < self.config.guarded_at:
            return Refusal(f"{villager.name} won't talk to you.")
        found, talk = await self._gather(file, villager)
        seen = {(r.kind, r.holder, r.text) for r in self.notebook.values()}
        new = []
        for r in found:
            if (r.kind, r.holder, r.text) not in seen:
                seen.add((r.kind, r.holder, r.text))
                r.id = r.id or self.ids.next("r")
                self.notebook[r.id] = r
                new.append(r)
        line = await self._phrase(villager, file, [r.text for r in new] + talk)
        self.feed.on_interview(vid, villager.name, line, [record_json(r, self.town) for r in new], player=self.id)
        try:
            await self.engine.press(file)
        except Exception:
            log.exception("pressing the culprit of %s failed", file.crime.id)
        return None

    async def _gather(self, file: CaseFile, villager: Villager) -> tuple[list[Record], list[str]]:
        """What the resident can give: their memory, their claim, their housemates' whereabouts and the best hearsay
        as records, and news-rooted hearsay as talk."""
        crime, vid, name = file.crime, villager.id, villager.name
        records = [r for r in file.records.values() if r.kind == "memory" and r.holder == vid]

        def statement(text: str, sound: bool, source: str | None = None) -> Record:
            return Record("", crime.id, "statement", self.place, self._clock(), text, vid, sound=sound, utterance=source)

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
                records.append(statement(f"{name}: {word[0]}", word[1]))
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

    async def _phrase(self, villager: Villager, file: CaseFile, facts: list[str]) -> str:
        """The resident's answer from the writer, or a plain line when there is none or it fails."""
        if self.writer is not None:
            try:
                if line := await self.writer.answer(
                    villager, file.crime.text, facts, neighbours(self.town, villager, file.crime.text),
                ):
                    return line
            except Exception:
                log.exception("answer for %s failed", villager.id)
        if facts:
            return f"{villager.name} says: {facts[0]}"
        return f"{villager.name} doesn't know anything about it."

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
