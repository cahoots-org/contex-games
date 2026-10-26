"""A player's run: walking, listening and asking around."""

import asyncio
import logging
import time
from dataclasses import asdict

from sleuth.config import Config
from sleuth.contex_client import Match
from sleuth.facts import audible
from sleuth.game import Game, Summary
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.town import PLACES, START_PLACE, Town, neighbours
from sleuth.usage import charging

log = logging.getLogger(__name__)


def analytics(event: str, **fields) -> None:
    """One line on stdout per countable event, for the host's log search: `analytics <event> key=value ...`."""
    print("analytics", event, *(f"{k}={v}" for k, v in fields.items()))


MAX_ASK_CHARS = 500
GAME_OVER = "The game is over."
LISTEN_OPENING = 5
LISTEN_LOOKBACK_DAYS = 1 / 4
ALREADY_LISTENING = "You're already listening."
ASK_LINES = 3


class Refusal(str):
    """The message for a question a suspicious villager turned away; the feed has already shown it."""


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
        self.state = "playing"
        self.summary: Summary | None = None
        self.finished = asyncio.Event()
        self.ended_at: float | None = None
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
            "id": self.id, "owner": self.owner, "place": self.place, "state": self.state, "ended_at": self.ended_at,
            "created_at": self.created_at, "summary": self.summary and asdict(self.summary), "active_at": self._active_at,
        }

    def restore(self, state: dict) -> None:
        """Fill the run from a saved state; with no tab open it is idle until its player reconnects."""
        self.place, self.state, self.ended_at = state["place"], state["state"], state["ended_at"]
        self.created_at = state["created_at"]
        summary = state["summary"]
        self.summary = summary and Summary(summary["outcome"], summary["reasons"])
        active_at = state["active_at"]
        self._active_at = None if active_at is None else min(active_at, time.time() - self.config.idle_after_seconds)
        if self.state != "playing":
            self.finished.set()

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
        if self.over():
            return GAME_OVER
        if place not in PLACES:
            return f"There's no {place} here. Try one of: {', '.join(PLACES)}."
        if place == self.place:
            return f"You're already at the {place}."
        self._move(place)
        return None

    def listen(self) -> str | None:
        """Listen to everything said where the player stands for a while; returns why it could not be done, if it couldn't.

        It opens with the last few lines said here in this part of the day.
        """
        self.touch()
        if self.over():
            return GAME_OVER
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

    async def ask(self, villager_id: str, topic: str) -> str | None:
        """Ask the villager what folk have been saying about the topic; returns why it could not be done, if it couldn't.

        A villager turning the question away comes back as a Refusal. The model call is charged to this player.
        """
        self.touch()
        with charging(self.id):
            return await self._ask(villager_id, topic)

    async def _ask(self, villager_id: str, topic: str) -> str | None:
        if self.over():
            return GAME_OVER
        if villager_id not in self.town:
            gone = self.town.name_of(villager_id)
            return f"{gone} has left town." if gone else "No one in town has that id."
        topic = topic.strip()
        if not topic:
            return "Ask about what? Try: the gym"
        if len(topic) > MAX_ASK_CHARS:
            return f"Too long: a question is at most {MAX_ASK_CHARS} characters."
        villager = self.town.get(villager_id)
        place = self.town.place_of(villager_id)
        if place != self.place:
            return f"{villager.name} is at the {place}. Walk there to ask them."
        if self.engine.suspicion.score(villager_id, self.id) >= self.config.refuse_threshold:
            self.feed.on_refusal(villager_id, villager.name, await self._turn_away(villager), player=self.id)
            return Refusal(f"{villager.name} turns away from you.")
        self.engine.suspicion.bump(villager_id, self.id, self.config.suspicion_whisper_bump / 2, "asked questions")
        recalled = await self.engine.recall_heard(villager_id, topic)
        heard = [u for u in map(self._tellable, recalled) if u is not None][:ASK_LINES]
        line = await self._answer(villager, topic, heard)
        self.feed.on_answer(villager_id, villager.name, topic, line, player=self.id)
        return None

    def _tellable(self, m: Match) -> Utterance | None:
        """The fact behind a recalled line, if it is still kept."""
        return self.engine.facts.get(m.data.get("id"))

    async def _answer(self, villager: Villager, topic: str, heard: list[Utterance]) -> str:
        """The villager's answer from the writer, or a plain line when there is none or it fails."""
        if self.writer is not None:
            try:
                if line := await self.writer.answer(
                    villager, topic, [f"{u.speaker_name} at the {u.place}: {u.text}" for u in heard],
                    neighbours(self.town, villager, topic),
                ):
                    return line
            except Exception:
                log.exception("answer for %s failed", villager.id)
        if heard:
            return f"{villager.name} heard {heard[0].speaker_name} talking about it at the {heard[0].place}."
        return f"{villager.name} hasn't heard anything about that."

    async def _turn_away(self, villager: Villager) -> str | None:
        """An in-character refusal line, or None when there is no writer or it fails."""
        if self.writer is None:
            return None
        try:
            return await self.writer.turn_away(villager) or None
        except Exception:
            log.exception("turn-away for %s failed", villager.id)
            return None

    def over(self) -> bool:
        """Whether this player's game is over."""
        return self.finished.is_set()

    def end(self, summary: Summary) -> None:
        """End this player's game once; announce it to them, then send them nothing more."""
        if self.over():
            return
        self.state, self.summary, self.ended_at = summary.outcome, summary, time.time()
        self.finished.set()
        analytics("end", owner=self.owner, run=self.id, outcome=summary.outcome)
        self.feed.on_game_over(summary, player=self.id)
        self.feed.close(self.id)

    def close(self) -> None:
        """Cancel every background task this player started."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    def _track(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
