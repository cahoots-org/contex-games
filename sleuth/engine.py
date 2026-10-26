"""The engine: one worker per villager, woken only by Contex pushes."""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import aclosing, suppress

from sleuth.actions import ALIBI, MOVE
from sleuth.calibration import Baselines
from sleuth.cases import APP, CaseFile, Cases
from sleuth.config import Config
from sleuth.contex_client import ContexClient, Match
from sleuth.decide import Decision, TurnView, decide, warmth_words
from sleuth.effects import act
from sleuth.facts import Facts
from sleuth.game import PHASES, Game
from sleuth.lineage import Ids, Lineage
from sleuth.mind import Mind, mind_project
from sleuth.models import Utterance, Villager
from sleuth.players import Players
from sleuth.reputation import Reputation
from sleuth.routine import Routine
from sleuth.town import START_PLACE, Town
from sleuth.writer import Writer

log = logging.getLogger(__name__)

LISTEN_RETRY_SECONDS = 1
# How many keys that reached a turn are remembered per villager, so neither a poll nor a direct hit hears them again.
CONSUMED_KEYS = 500
# How many villagers set off together on their daily round, and how much of each part of the day the round spans.
ROUTINE_BATCH = 5
ROUTINE_SPREAD = 0.5
WARNING = "The podcaster is stirring up trouble."
COLDER = "Someone in town seems colder toward you."


class Engine:
    def __init__(
        self,
        config: Config,
        town: Town,
        contex: ContexClient,
        jev,
        writer: Writer,
        lineage: Lineage,
        ids: Ids,
        feed,
        mind_factory: Callable[[Villager], Mind] | None = None,
        game: Game | None = None,
        baselines: Baselines | None = None,
        routine: Routine | None = None,
        facts: Facts | None = None,
        cases: Cases | None = None,
    ):
        self.config = config
        self.town = town
        self.contex = contex
        self.jev = jev
        self.writer = writer
        self.lineage = lineage
        self.ids = ids
        self.feed = feed
        self.facts = facts or Facts()
        self.baselines = baselines
        self.routine = routine
        self.cases = cases
        self.reputation = Reputation(config)
        self.players = Players()
        self.mind_factory = mind_factory or (lambda v: Mind(contex, v, config, baselines))
        self.game = game
        self.minds: dict[str, Mind] = {}
        self._tasks: dict[str, list[asyncio.Task]] = {}
        self._read_at: dict[str, float] = {}
        self._wakes: dict[str, asyncio.Event] = {}
        self._pending: dict[str, list[Match]] = {}
        self._last_turn: dict[str, float] = {}
        self._turning: set[str] = set()
        self._consumed: dict[str, dict[str, None]] = {}
        self._listen_failed: set[str] = set()
        # How readily each villager passes news on, asked once per villager.
        self._gossip: dict[str, float] = {}
        self._renewal: asyncio.Task | None = None
        self._clock: asyncio.Task | None = None
        self._walking: asyncio.Task | None = None
        # The last new item of each villager's last turn, which a routine move may carry.
        self._latest: dict[str, Match] = {}
        # Villagers whose own turn moved them this part of the day, so the round leaves them be.
        self._chose_move: set[str] = set()
        self._turns = asyncio.Semaphore(config.turn_concurrency)

    def to_state(self) -> dict:
        """Each villager's gossip taste and read keys as plain JSON."""
        return {"gossip": dict(self._gossip), "consumed": {vid: list(keys) for vid, keys in self._consumed.items()}}

    def restore(self, state: dict) -> None:
        """Replace gossip and read keys with a saved state."""
        self._gossip = dict(state["gossip"])
        self._consumed = {vid: dict.fromkeys(keys) for vid, keys in state["consumed"].items()}

    async def add_villager(self, v: Villager, place: str = START_PLACE) -> None:
        mind = self.mind_factory(v)
        await mind.open()
        self.town.add(v, place)
        self.minds[v.id] = mind
        self._read_at[v.id] = time.monotonic()
        wake = self._wakes[v.id] = asyncio.Event()
        self._tasks[v.id] = [
            asyncio.create_task(self._listen(mind, wake)),
            asyncio.create_task(self._work(mind, wake)),
        ]

    async def remove_villager(self, vid: str) -> None:
        """Stop the villager's tasks; the subscription is left to expire."""
        self.minds.pop(vid, None)
        self._read_at.pop(vid, None)
        self._wakes.pop(vid, None)
        self._pending.pop(vid, None)
        self._last_turn.pop(vid, None)
        self._turning.discard(vid)
        self._consumed.pop(vid, None)
        self._listen_failed.discard(vid)
        self._latest.pop(vid, None)
        self._chose_move.discard(vid)
        with suppress(KeyError):
            self.town.remove(vid)
        current = asyncio.current_task()
        tasks = [t for t in self._tasks.pop(vid, []) if t is not current]
        await _cancel(tasks)

    async def run(self) -> None:
        """Start lease renewal and, with a game, the clock; returns at once."""
        self._renewal = asyncio.create_task(self._renew_loop())
        if self.game is not None:
            self._clock = asyncio.create_task(self._clock_loop())

    async def stop(self) -> None:
        tasks = [t for ts in self._tasks.values() for t in ts]
        tasks += [t for t in (self._renewal, self._clock, self._walking) if t]
        self._tasks.clear()
        self._renewal = self._clock = self._walking = None
        await _cancel(tasks)

    async def deliver(self, utterance: Utterance, listener_ids: list[str], addressed: bool = False) -> None:
        """Publish the utterance to each listener's mind; raises only if every listener failed.

        An addressed utterance also wakes each listener and joins their next turn unmatched. Room talk rooted in a
        case is shown in the feed.
        """
        listeners = [i for i in listener_ids if i in self.town and i in self.minds]
        data = utterance.to_data()
        hearing = [self.minds[i].hear(f"utt:{utterance.id}", data) for i in listeners]
        results = await asyncio.gather(*hearing, return_exceptions=True)
        for vid, result in zip(listeners, results):
            if isinstance(result, Exception):
                log.error("delivery to %s failed", vid, exc_info=result)
        heard = [vid for vid, result in zip(listeners, results) if not isinstance(result, Exception)]
        if addressed:
            for vid in heard:
                self.hear_directly(vid, Match(f"utt:{utterance.id}", data))
        if listeners and not heard:
            raise next(r for r in results if isinstance(r, Exception))
        if utterance.audience == "room" and self.cases is not None:
            if rooted := self.cases.root_kind(self.lineage.root(utterance.id)):
                self.feed.on_post(utterance, rooted[0].crime.id, player=rooted[0].crime.owner)

    async def recall_heard(self, vid: str, text: str) -> list[Match]:
        """Lines the villager heard earlier that the words match, best first."""
        try:
            hits = await self.contex.query(mind_project(self.config.session, vid), text, top_k=3, threshold=0)
        except Exception as e:
            log.warning("searching what %s heard failed: %s", vid, type(e).__name__)
            return []
        found = [
            h for h in hits
            if h.similarity is not None and h.similarity >= self.config.heard_floor
        ]
        return sorted(found, key=lambda h: h.similarity, reverse=True)[:3]

    def hear_directly(self, vid: str, match: Match) -> bool:
        """Add the match to the villager's next turn and wake them; False once they have left."""
        if vid not in self.town or vid not in self.minds:
            return False
        pending = self._pending.setdefault(vid, [])
        if all(m.data_key != match.data_key for m in pending):
            pending.append(match)
        self._wakes[vid].set()
        return True

    def cooldown_ends(self, vid: str) -> float:
        """Wall-clock time when the villager can next take a turn; now or earlier when free."""
        cooldown = self.config.cooldown_seconds
        if vid in self._turning:
            return time.time() + cooldown
        last = self._last_turn.get(vid)
        if last is None:
            return time.time()
        return time.time() + last + cooldown - time.monotonic()

    async def _listen(self, mind: Mind, wake: asyncio.Event) -> None:
        """Own the push stream for one mind; a push only sets the wake event."""
        while True:
            try:
                async with aclosing(mind.pushes()) as pushes:
                    async for _ in pushes:
                        wake.set()
            except Exception as e:
                vid = mind.villager.id
                if vid in self._listen_failed:
                    log.warning("listen failed again for %s: %r", vid, e)
                else:
                    self._listen_failed.add(vid)
                    log.exception("listen failed for %s", vid)
            await asyncio.sleep(LISTEN_RETRY_SECONDS)

    async def _work(self, mind: Mind, wake: asyncio.Event) -> None:
        """Take at most one turn per cooldown, coalescing the pushes in between."""
        vid = mind.villager.id
        while True:
            await wake.wait()
            await asyncio.sleep(max(0.0, self.cooldown_ends(vid) - time.time()))
            wake.clear()
            self._turning.add(vid)
            try:
                if await self._turn(mind):
                    self._last_turn[vid] = time.monotonic()
            except Exception:
                log.exception("turn failed for %s", vid)
                self._last_turn[vid] = time.monotonic()
                if self._pending.get(vid):
                    wake.set()
            finally:
                self._turning.discard(vid)
            if vid not in self.town:
                await self.remove_villager(vid)
                return
            await self._catch_up(vid)

    async def _turn(self, mind: Mind) -> bool:
        """Poll the mind, add addressed messages, and if anything fresh is new, decide and act.

        Returns whether a turn ran. While nobody is playing, nothing is read and no turn runs.
        """
        if not self.players.any_playing():
            return False
        v = mind.villager
        new = await mind.poll()
        self._read_at[v.id] = time.monotonic()
        consumed = self._consumed.setdefault(v.id, {})
        pending = self._pending.pop(v.id, [])
        pending_keys = {m.data_key for m in pending}
        new = [m for m in new if m.data_key not in consumed and m.data_key not in pending_keys]
        new += [m for m in pending if m.data_key not in consumed]
        for m in new:
            consumed[m.data_key] = None
        while len(consumed) > CONSUMED_KEYS:
            del consumed[next(iter(consumed))]
        stale = [m for m in new if not self._fresh(m)]
        stale_keys = {m.data_key for m in stale}
        new = [m for m in new if m.data_key not in stale_keys]
        if not new:
            return False
        self._latest[v.id] = new[-1]
        keys = {m.data_key for m in new}
        place = self.town.place_of(v.id)
        own_case = self.cases.culprit_case(v.id) if self.cases is not None else None
        view = TurnView(
            villager=v,
            place=place,
            present=self.town.present(place, exclude=v.id),
            new=new,
            recent=stale + [m for m in mind.matches if m.data_key not in keys | stale_keys],
            ask_gossip=v.id not in self._gossip,
            case=own_case.crime.text if own_case else None,
            night=self.game is not None and self.game.phase == "night",
            warn=own_case is not None and bool(own_case.pressed_by) and own_case.warned != self._part(),
        )
        phase = self.game.phase if self.game is not None else None
        async with self._turns:
            decision = await decide(self.jev, view)
            if decision.gossip is not None:
                self._gossip[v.id] = decision.gossip
            await act(
                decision, v, town=self.town, writer=self.writer, hub=self,
                lineage=self.lineage, ids=self.ids, facts=self.facts,
                share_chance=self.share_chance(v.id, decision.source) if decision.action == MOVE else 0.0,
            )
            if decision.action == MOVE and (self.game.phase if self.game is not None else None) == phase:
                self._chose_move.add(v.id)
        return True

    def cover_story(self, vid: str, action: str) -> str | None:
        """The culprit's alibi or blame line, from the case."""
        if self.cases is None:
            return None
        return self.cases.alibi(vid) if action == ALIBI else self.cases.blame(vid)

    def mark_cover(self, vid: str, uid: str) -> None:
        if self.cases is not None:
            self.cases.mark_cover(vid, uid)

    def warn(self, vid: str, target: str) -> str | None:
        """The pressed culprit's warning about the podcaster, told to someone close, at most once a part of the day.

        The target thinks less of that podcaster, who hears only that someone seems colder.
        """
        case = self.cases.culprit_case(vid) if self.cases is not None else None
        if case is None or not case.pressed_by or case.warned == self._part():
            return None
        if warmth_words(self.town.get(vid).warmth.get(target, 0.0)) != "close":
            return None
        case.warned = self._part()
        self.reputation.nudge(target, case.pressed_by, self.config.reputation_warned)
        self.feed.say(COLDER, player=case.pressed_by)
        return WARNING

    def _part(self) -> str:
        """The part of the day as "day:phase"; empty without a game."""
        return f"{self.game.day}:{self.game.phase}" if self.game is not None else ""

    async def press(self, file: CaseFile, player_id: str) -> None:
        """Tell the culprit a podcaster is asking around, at most once a part of the day."""
        file.pressed_by = player_id
        now = self._part()
        if file.pressed == now:
            return
        crime = file.crime
        u = Utterance(self.ids.next("u"), "app", APP, crime.place, f"A podcaster is asking around about this: {crime.text}",
                      None, "posted")
        await self.deliver(u, [crime.culprit], addressed=True)
        file.pressed = now

    def share_chance(self, vid: str, source: Match | None) -> float:
        """How likely a villager who walks off is to share source where they arrive: their nature times its pull."""
        pull = 0.5 if source is None or source.clearance is None else source.clearance / self.config.share_clearance
        return self._gossip.get(vid, 0.5) * min(1.0, max(0.0, pull))

    def _fresh(self, m: Match) -> bool:
        """Whether the item clears its need by enough to wake the villager, given how often it was retold."""
        if m.clearance is None:
            return True
        fact = self.facts.get(m.data.get("id"))
        depth = fact.depth if fact else 0
        room = self.config.overheard_margin if fact and fact.audience == "room" else 0.0
        return m.clearance >= self.config.fatigue_per_hop * depth + room

    async def _clock_loop(self) -> None:
        """Run the parts of each day: announce each, ease reputations, run cases and walk the daily round."""
        phase_seconds = self.config.day_seconds / len(PHASES)
        while True:
            await asyncio.sleep(phase_seconds)
            self.game.tick()
            self.reputation.decay()
            self.feed.on_time(self.game.day, self.game.phase)
            finished = self.town.new_phase()
            if self.cases is not None:
                try:
                    await self.cases.on_tick(self, self.game.day, self.game.phase, finished, self.players.any_playing())
                except Exception:
                    log.exception("cases tick failed")
            self._chose_move.clear()
            if self.routine is not None:
                if self._walking is not None:
                    self._walking.cancel()
                self._walking = asyncio.create_task(self._walk(self.game.phase, phase_seconds * ROUTINE_SPREAD))

    async def _walk(self, phase: str, spread: float) -> None:
        """Send villagers who are not at their routine place there, a batch at a time across spread seconds."""
        try:
            due = [
                v.id for v in self.town.villagers
                if self.routine.place(v.id, phase) not in (None, self.town.place_of(v.id))
            ]
            batches = [due[i:i + ROUTINE_BATCH] for i in range(0, len(due), ROUTINE_BATCH)]
            for i, batch in enumerate(batches):
                if i:
                    await asyncio.sleep(spread / len(batches))
                free = [vid for vid in batch if self._free_to_walk(vid)]
                await asyncio.gather(*(self._stroll(vid, self.routine.place(vid, phase)) for vid in free))
        except Exception:
            log.exception("routine round failed")

    async def _catch_up(self, vid: str) -> None:
        """Send a villager the round skipped mid-turn to their routine place."""
        if self.routine is None or self.game is None:
            return
        place = self.routine.place(vid, self.game.phase)
        if place not in (None, self.town.place_of(vid)) and self._free_to_walk(vid):
            await self._stroll(vid, place)

    def _free_to_walk(self, vid: str) -> bool:
        """Whether someone is playing and the villager is in town, free of a turn, a move of their own, or a crime
        being set up."""
        return self.players.any_playing() and vid in self.town and vid not in self._turning and (
            vid not in self._chose_move
        ) and (self.cases is None or vid not in self.cases.busy())

    async def _stroll(self, vid: str, place: str) -> None:
        """Move the villager to place, perhaps sharing their latest news with someone there once, while it is fresh."""
        if vid not in self.town:
            return
        latest = self._latest.pop(vid, None)
        if latest is not None and not self._fresh(latest):
            latest = None
        try:
            await act(
                Decision(MOVE, latest, place, None), self.town.get(vid), town=self.town, writer=self.writer,
                hub=self, lineage=self.lineage, ids=self.ids, facts=self.facts,
                share_chance=self.share_chance(vid, latest) if latest else 0.0,
            )
        except Exception:
            log.exception("routine move failed for %s", vid)

    async def _renew_loop(self) -> None:
        """Renew the lease of every mind not read within renew_seconds."""
        while True:
            await asyncio.sleep(self.config.renew_seconds)
            cutoff = time.monotonic() - self.config.renew_seconds
            for vid, mind in list(self.minds.items()):
                if self._read_at.get(vid, 0.0) > cutoff:
                    continue
                try:
                    await mind.renew()
                    self._read_at[vid] = time.monotonic()
                except Exception:
                    log.exception("renew failed for %s", vid)


async def _cancel(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
