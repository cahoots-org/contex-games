"""The engine: one worker per villager, woken only by Contex pushes."""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import aclosing, suppress

from sleuth.actions import ALIBI, ANSWER, MOVE, WARN
from sleuth.calibration import Baselines
from sleuth.cases import APP, CaseFile, Cases
from sleuth.config import Config
from sleuth.contex_client import ContexClient, Match
from sleuth.decide import Decision, TurnView, decide
from sleuth.effects import act
from sleuth.facts import Facts
from sleuth.game import PHASES, Game, Summary
from sleuth.hints import Hints
from sleuth.lineage import Ids, Lineage
from sleuth.mind import Mind, group_project, mind_project, said_project
from sleuth.models import Group, Utterance, Villager
from sleuth.player import Player
from sleuth.players import Players
from sleuth.rapport import Rapport, taken_words
from sleuth.routine import Routine
from sleuth.suspicion import Suspicion
from sleuth.town import START_PLACE, Town
from sleuth.usage import charging
from sleuth.writer import WHISPER_FRAMING, Writer

log = logging.getLogger(__name__)

LISTEN_RETRY_SECONDS = 1
# How many keys that reached a turn are remembered per villager, so neither a poll nor a direct hit hears them again.
CONSUMED_KEYS = 500
# How many whispers a villager kept to themselves are watched for a later relay.
KEPT_WHISPERS = 50
# How many villagers set off together on their daily round, and how much of each part of the day the round spans.
ROUTINE_BATCH = 5
ROUTINE_SPREAD = 0.5
MEETING = "The town meets at town hall and runs the newcomer out of town."


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
        self.hints = Hints(contex, config)
        self.suspicion = Suspicion(config, town)
        self.rapport = Rapport(config)
        self.baselines = baselines
        self.routine = routine
        self.cases = cases
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
        # Villagers on a routine move, whose carried news counts as said like a turn's.
        self._strolling: set[str] = set()
        self._consumed: dict[str, dict[str, None]] = {}
        self._listen_failed: set[str] = set()
        self._said: dict[str, list[tuple[str, int]]] = {}
        self._kept: dict[str, dict[str, None]] = {}
        # How readily each villager passes news on, asked once per villager.
        self._gossip: dict[str, float] = {}
        # Each open conversation, keyed by (villager id, player id): its first whisper and the whispers answered so far.
        self.conversations: dict[tuple[str, str], dict] = {}
        self._renewal: asyncio.Task | None = None
        self._checks: asyncio.Task | None = None
        self._clock: asyncio.Task | None = None
        self._walking: asyncio.Task | None = None
        # The last new item of each villager's last turn, which a routine move may carry.
        self._latest: dict[str, Match] = {}
        # Villagers whose own turn moved them this part of the day, so the round leaves them be.
        self._chose_move: set[str] = set()
        self._turns = asyncio.Semaphore(config.turn_concurrency)

    def to_state(self) -> dict:
        """Each villager's gossip taste, kept whispers and read keys as plain JSON."""
        return {"gossip": dict(self._gossip), "kept": {vid: list(kept) for vid, kept in self._kept.items()},
                "consumed": {vid: list(keys) for vid, keys in self._consumed.items()}}

    def restore(self, state: dict) -> None:
        """Replace gossip, kept whispers and read keys with a saved state.

        A whisper a villager had read but not yet answered when the game stopped is told as kept.
        """
        self._gossip = dict(state["gossip"])
        self._kept = {vid: dict.fromkeys(kept) for vid, kept in state["kept"].items()}
        self._consumed = {vid: dict.fromkeys(keys) for vid, keys in state["consumed"].items()}
        for vid, keys in self._consumed.items():
            for wid, name in self.feed.listening(vid):
                if f"utt:{wid}" in keys:
                    self.feed.on_whisper_status(wid, vid, name, "kept")

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
        self._said.pop(vid, None)
        self._kept.pop(vid, None)
        self._latest.pop(vid, None)
        self._chose_move.discard(vid)
        self.end_conversation(vid)
        for wid, name in self.feed.listening(vid):
            self.feed.on_whisper_status(wid, vid, name, "kept")
        with suppress(KeyError):
            self.town.remove(vid)
        current = asyncio.current_task()
        tasks = [t for t in self._tasks.pop(vid, []) if t is not current]
        await _cancel(tasks)

    async def run(self) -> None:
        """Start lease renewal and, with a game, the town check; returns at once."""
        self._renewal = asyncio.create_task(self._renew_loop())
        if self.game is not None:
            self._checks = asyncio.create_task(self._suspicion_loop())
            self._clock = asyncio.create_task(self._clock_loop())

    async def stop(self) -> None:
        tasks = [t for ts in self._tasks.values() for t in ts]
        tasks += [t for t in (self._renewal, self._checks, self._clock, self._walking) if t]
        self._tasks.clear()
        self._renewal = self._checks = self._clock = self._walking = None
        await _cancel(tasks)

    async def deliver(self, utterance: Utterance, listener_ids: list[str], addressed: bool = False) -> None:
        """Publish the utterance to each listener's mind; raises only if every listener failed.

        An addressed utterance also wakes each listener and joins their next turn unmatched. Room talk rooted in a
        case is posted to the app.
        """
        listeners = [i for i in listener_ids if i in self.town and i in self.minds]
        data = utterance.to_data()
        hearing = [self.minds[i].hear(f"utt:{utterance.id}", data) for i in listeners]
        if utterance.speaker in self.minds:
            hearing.append(self._remember_said(utterance.speaker, f"said:{utterance.id}", data))
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
        if heard and (utterance.speaker in self._turning or utterance.speaker in self._strolling):
            self._said.setdefault(utterance.speaker, []).append((utterance.id, len(heard)))
        self.feed.on_delivery(utterance, heard)
        if utterance.audience == "room" and self.cases is not None:
            if rooted := self.cases.root_kind(self.lineage.root(utterance.id)):
                self.feed.on_post(utterance, rooted[0].crime.id, player=rooted[0].crime.owner)

    async def reply(self, utterance: Utterance) -> None:
        """Remember a villager's answer to the newcomer and show it on its conversation; no mind hears it."""
        await self._remember_said(utterance.speaker, f"said:{utterance.id}", utterance.to_data())
        whisper = self.facts.get(utterance.parent)
        conversation = (whisper and whisper.conversation) or utterance.parent
        self.feed.on_reply(conversation, utterance)

    def end_conversation(self, vid: str, player: str | None = None) -> None:
        """Close the villager's conversation with player, or with every player when None; its answers have moved on."""
        keys = [k for k in self.conversations if k[0] == vid and player in (None, k[1])]
        name = self.town.name_of(vid) or vid
        for key in keys:
            for wid in self.conversations.pop(key)["answered"]:
                self.feed.on_whisper_status(wid, vid, name, "moved_on")

    async def _remember_said(self, vid: str, key: str, data: dict) -> None:
        """Keep a line the villager spoke in their said project, which nothing subscribes to."""
        try:
            await self.contex.publish(said_project(self.config.session, vid), key, data)
        except Exception as e:
            log.warning("remembering a line said by %s failed: %s", vid, type(e).__name__)

    async def _recall_said(self, vid: str, lines: list[Match]) -> list[Match]:
        """The villager's earlier lines that the newcomer's words match, best first."""
        found: dict[str, Match] = {}
        for m in lines:
            words = WHISPER_FRAMING.sub("", m.data.get("text", ""))
            try:
                hits = await self.contex.query(
                    said_project(self.config.session, vid), words,
                    top_k=3, since=self.game and self.game.memory_since(), threshold=0,
                )
            except Exception as e:
                log.warning("searching what %s said failed: %s", vid, type(e).__name__)
                continue
            for hit in hits:
                if hit.similarity is not None and hit.similarity >= self.config.said_floor:
                    found.setdefault(hit.data_key, hit)
        return sorted(found.values(), key=lambda h: h.similarity, reverse=True)[:3]

    async def recall_heard(self, vid: str, text: str, exclude: str) -> list[Match]:
        """Lines the villager heard earlier that the newcomer's words match, best first.

        The newcomer's own whispers, this one (exclude) and any before it, are left out.
        """
        try:
            hits = await self.contex.query(
                mind_project(self.config.session, vid), WHISPER_FRAMING.sub("", text),
                top_k=3, since=self.game and self.game.memory_since(), threshold=0,
            )
        except Exception as e:
            log.warning("searching what %s heard failed: %s", vid, type(e).__name__)
            return []
        found = [
            h for h in hits
            if h.similarity is not None and h.similarity >= self.config.heard_floor
            and h.data.get("id") != exclude and not self.lineage.is_whisper(h.data.get("id"))
        ]
        return sorted(found, key=lambda h: h.similarity, reverse=True)[:3]

    async def _recall_heard_all(self, vid: str, whispers: list[Match]) -> list[Match]:
        """What the villager heard before that any of the newcomer's whispers this turn bring back, best first."""
        found: dict[str, Match] = {}
        for m in whispers:
            for hit in await self.recall_heard(vid, m.data.get("text", ""), m.data.get("id")):
                found.setdefault(hit.data_key, hit)
        return sorted(found.values(), key=lambda h: h.similarity, reverse=True)

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

    def suspect(self, vid: str, player: str, amount: float, reason: str, uid: str | None = None) -> None:
        """Raise the villager's suspicion of player."""
        self.suspicion.bump(vid, player, amount, reason, uid)

    async def publish_group(self, group: Group) -> None:
        data = {"id": group.id, "name": group.name, "creed": group.creed, "founder": group.founder}
        await self.contex.publish(group_project(self.config.session, group.id), f"group:{group.id}", data)

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
        # The newcomer's own whispers among the new items, for whisper outcomes.
        whispers = [m for m in new if self.lineage.is_whisper(m.data.get("id"))]
        said = await self._recall_said(v.id, whispers) if whispers else []
        heard = await self._recall_heard_all(v.id, whispers)
        answerable = [m for m in whispers if self._can_answer(v.id, m.data["id"])]
        place = self.town.place_of(v.id)
        front = {self._about(m) for m in new} - {None}
        suspect = self.suspicion.most_suspected(v.id, front)
        holders = self._holders(v.id)
        own_case = self.cases.culprit_case(v.id) if self.cases is not None else None
        view = TurnView(
            villager=v,
            place=place,
            present=self.town.present(place, exclude=v.id),
            member_groups=self.town.member_groups(v.id),
            visible_groups=self.town.visible_groups(v.id),
            new=new,
            recent=stale + [m for m in mind.matches if m.data_key not in keys | stale_keys],
            suspicion=self.suspicion.score(v.id, suspect) if suspect else 0.0,
            warn_threshold=self.config.warn_threshold,
            names_newcomer=[m for m in new if m in whispers or self._names_newcomer(m)],
            said=said,
            heard=heard,
            answerable=answerable,
            ask_gossip=v.id not in self._gossip,
            held=any(not p.annoyed(v.id) for p in holders),
            taken=self._taken(v.id, new),
            case=own_case.crime.text if own_case else None,
        )
        action = answered = None
        # The turn answers to the player behind the first of its new items that a player started, if any.
        started = [p for p in map(self._player_behind, new) if p]
        payer = started[0] if started else None
        try:
            async with self._turns:
                with charging(payer):
                    decision = await decide(self.jev, view)
                action = decision.action
                if decision.suspicion_strength is not None:
                    self._rate(v.id, decision.suspicion_strength, view.names_newcomer)
                if decision.gossip is not None:
                    self._gossip[v.id] = decision.gossip
                if action == MOVE:
                    for p in holders:
                        if p.annoyed(v.id):
                            await self._storm_off(v, p)
                with charging(self._player_behind(decision.source) or payer):
                    await act(
                        decision, v, town=self.town, writer=self.writer, hub=self,
                        lineage=self.lineage, ids=self.ids, facts=self.facts,
                        inspiration=[m.data.get("text", "") for m in new],
                        said=[m.data.get("text", "") for m in said],
                        heard=[m.data.get("text", "") for m in heard],
                        suspicion_hear_max=self.config.suspicion_hear_max,
                        share_chance=self.share_chance(v.id, decision.source) if action == MOVE else 0.0,
                        about=suspect,
                        mood=self._mood(v.id, decision) if action == ANSWER else "",
                    )
                if action == MOVE:
                    self._chose_move.add(v.id)
                if action == ANSWER:
                    answered = decision.source.data["id"]
                    if (player := self._player_behind(decision.source)) is not None:
                        self.rapport.greeted(v.id, player, self._rumor_of(answered))
        finally:
            self._report(
                v, [m.data["id"] for m in whispers], action, self._said.pop(v.id, []), answered,
            )
        return True

    async def _storm_off(self, v: Villager, player: Player) -> None:
        """The villager breaks off with player: parting words to them alone, their exchange ended, and a little
        suspicion."""
        with charging(player.id):
            try:
                line = await self.writer.storm_off(v) or None
            except Exception:
                log.exception("parting line for %s failed", v.id)
                line = None
        self.feed.on_storm_off(v.id, v.name, line, player=player.id)
        player.part(v.id)
        self.suspicion.bump(v.id, player.id, self.config.suspicion_whisper_bump / 2, "stormed off")

    def cover_story(self, vid: str, action: str) -> str | None:
        """The culprit's alibi or blame line, from the case."""
        if self.cases is None:
            return None
        return self.cases.alibi(vid) if action == ALIBI else self.cases.blame(vid)

    def mark_cover(self, vid: str, uid: str) -> None:
        if self.cases is not None:
            self.cases.mark_cover(vid, uid)

    async def press(self, file: CaseFile) -> None:
        """Tell the culprit a podcaster is asking around, at most once a part of the day."""
        now = f"{self.game.day}:{self.game.phase}"
        if file.pressed == now:
            return
        file.pressed = now
        crime = file.crime
        u = Utterance(self.ids.next("u"), "app", APP, crime.place, f"A podcaster is asking around about this: {crime.text}",
                      None, "posted")
        await self.deliver(u, [crime.culprit], addressed=True)

    def _rumor_of(self, uid: str) -> str:
        """The key her interest is kept under for the player's whisper behind uid."""
        whisper = self.lineage.root(uid)
        fact = self.facts.get(whisper)
        return fact.conversation if fact and fact.conversation else whisper

    def _interest_in(self, vid: str, uid: str) -> float | None:
        """Her interest in the player's rumor behind uid, or None when no player's whisper is or she only heard it
        second-hand."""
        player = self.lineage.player_of(uid)
        if player is None:
            return None
        rumor = self._rumor_of(uid)
        return self.rapport.interest(vid, player, rumor) if self.rapport.known(vid, player, rumor) else None

    def taken_by(self, vid: str, uid: str) -> str | None:
        """How taken she was with the player's rumor behind uid, in a word, or None."""
        interest = self._interest_in(vid, uid)
        return None if interest is None else taken_words(interest)

    def _taken(self, vid: str, new: list[Match]) -> str | None:
        """How taken she was with the player's rumor behind the new items: the strongest if several."""
        interests = [i for m in new if (i := self._interest_in(vid, m.data.get("id"))) is not None]
        return taken_words(max(interests)) if interests else None

    def _mood(self, vid: str, decision: Decision) -> str:
        """How the villager feels about the rumor behind the newcomer line she is answering."""
        uid = decision.source.data["id"]
        player = self._player_behind(decision.source)
        if player is None:
            return ""
        rumor = self._rumor_of(uid)
        return self.rapport.mood(vid, player, rumor, greet=self.rapport.greets(vid, player, rumor))

    def _player_behind(self, m: Match | None) -> str | None:
        """The player whose whisper the item's lineage roots in."""
        return None if m is None else self.lineage.player_of(m.data.get("id"))

    def _about(self, m: Match) -> str | None:
        """The player the item's lineage roots in, or else the player it warns of."""
        uid = m.data.get("id")
        fact = self.facts.get(uid)
        return self.lineage.player_of(uid) or (fact.about if fact else None)

    def _rate(self, vid: str, strength: float, named: list[Match]) -> None:
        """Raise the villager's suspicion of each player the named lines are about by strength."""
        first: dict[str, str | None] = {}
        for m in named:
            if (player := self._about(m)) is not None:
                first.setdefault(player, m.data.get("id"))
        for player, uid in first.items():
            try:
                self.suspicion.rate(vid, player, strength, "heard the newcomer named", uid)
            except Exception:
                log.exception("suspicion rating failed for %s", vid)

    def share_chance(self, vid: str, source: Match | None) -> float:
        """How likely a villager who walks off is to share source where they arrive: their nature times its pull."""
        pull = 0.5 if source is None or source.clearance is None else source.clearance / self.config.share_clearance
        return self._gossip.get(vid, 0.5) * min(1.0, max(0.0, pull))

    def _fresh(self, m: Match) -> bool:
        """Whether the item clears its need by enough to wake the villager, given how often it was retold.

        The newcomer's own whisper is always fresh.
        """
        if m.clearance is None or self.lineage.is_whisper(m.data.get("id")):
            return True
        fact = self.facts.get(m.data.get("id"))
        depth = fact.depth if fact else 0
        room = self.config.overheard_margin if fact and fact.audience == "room" else 0.0
        return m.clearance >= self.config.fatigue_per_hop * depth + room

    def _names_newcomer(self, m: Match) -> bool:
        """Whether the item names the newcomer; a direct warning already raised suspicion when it was given."""
        # ponytail: Facts evicts after 5000 lines, so very old named lines stop raising suspicion.
        fact = self.facts.get(m.data.get("id"))
        return fact is not None and fact.names_newcomer and fact.action != WARN

    def _report(
        self, v: Villager, whispers: list[str], action: str | None, said: list[tuple[str, int]],
        answered: str | None = None,
    ) -> None:
        """Tell the feed what the villager did with the whispers this turn heard and any they kept before.

        said holds (utterance id, listeners who heard it) for what this turn said, in order; answered is the
        whisper the villager answered, if any. A reply in an open conversation ends it unless the turn answered.
        """
        told: dict[str, int] = {}
        for uid, heard in said:
            told.setdefault(self.lineage.root(uid), heard)
        kept = self._kept.setdefault(v.id, {})
        for wid in [w for w in kept if w in told]:
            del kept[wid]
            self.feed.on_whisper_status(wid, v.id, v.name, "took_the_bait", told=told[wid])
        for wid in whispers:
            if wid == answered:
                self._answered(v, wid)
                continue
            fact = self.facts.get(wid)
            player = self.lineage.player_of(wid)
            talking = fact is not None and fact.conversation is not None and (
                self.conversations.get((v.id, player), {}).get("id") == fact.conversation
            )
            if wid in told:
                self.feed.on_whisper_status(wid, v.id, v.name, "took_the_bait", told=told[wid])
            elif action == WARN:
                self.feed.on_whisper_status(wid, v.id, v.name, "warned")
            else:
                kept[wid] = None
                self.feed.on_whisper_status(wid, v.id, v.name, "moved_on" if talking else "kept")
            if talking and answered is None:
                self.end_conversation(v.id, player)
        while len(kept) > KEPT_WHISPERS:
            del kept[next(iter(kept))]

    def _can_answer(self, vid: str, wid: str) -> bool:
        """Whether the whisper's player has turns left in their conversation with the villager."""
        talking = self.conversations.get((vid, self.lineage.player_of(wid)), {"answered": []})
        return len(talking["answered"]) < self.config.talk_turns

    def _answered(self, v: Villager, wid: str) -> None:
        """Open or extend the whisper's player's conversation on the card the whisper belongs to; the cap ends it."""
        fact = self.facts.get(wid)
        player = self.lineage.player_of(wid)
        conversation = self.conversations.setdefault(
            (v.id, player), {"id": (fact and fact.conversation) or wid, "answered": []},
        )
        conversation["answered"].append(wid)
        self.feed.on_whisper_status(wid, v.id, v.name, "answered")
        if len(conversation["answered"]) >= self.config.talk_turns:
            self.end_conversation(v.id, player)

    async def _clock_loop(self) -> None:
        """Move the village through the parts of each day, announce each one, run its cases and walk its daily round."""
        phase_seconds = self.config.day_seconds / len(PHASES)
        while True:
            await asyncio.sleep(phase_seconds)
            self.game.tick()
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

    def _free_to_walk(self, vid: str) -> bool:
        """Whether someone is playing and the villager is in town, free of a turn, a move of their own, a
        player talking with them, or a crime being set up."""
        return self.players.any_playing() and vid in self.town and vid not in self._turning and (
            vid not in self._chose_move
        ) and not self._holders(vid) and (self.cases is None or vid not in self.cases.busy())

    def _holders(self, vid: str) -> list[Player]:
        """The players talking with the villager who keep them where they are."""
        return [p for p in self.players if p.holds(vid)]

    async def _stroll(self, vid: str, place: str) -> None:
        """Move the villager to place, perhaps sharing their latest news with someone there once, while it is fresh."""
        if vid not in self.town:
            return
        latest = self._latest.pop(vid, None)
        if latest is not None and not self._fresh(latest):
            latest = None
        v = self.town.get(vid)
        self._strolling.add(vid)
        try:
            with charging(self._player_behind(latest)):
                await act(
                    Decision(MOVE, latest, place, None), v, town=self.town, writer=self.writer,
                    hub=self, lineage=self.lineage, ids=self.ids, facts=self.facts,
                    suspicion_hear_max=self.config.suspicion_hear_max,
                    share_chance=self.share_chance(vid, latest) if latest else 0.0,
                )
            self._report(v, [], MOVE, self._said.pop(vid, []))
        except Exception:
            log.exception("routine move failed for %s", vid)
        finally:
            self._strolling.discard(vid)

    async def _suspicion_loop(self) -> None:
        """Decay suspicion, then check where each player someone is playing stands with the town."""
        days = self.config.suspicion_check_days
        labels: dict[str, str] = {}
        held: dict[str, int] = {}
        while True:
            await asyncio.sleep(days * self.config.day_seconds)
            try:
                self.suspicion.decay(days)
                for p in self.players:
                    if p.active() and not p.over():
                        self._check(p, labels, held)
            except Exception:
                log.exception("town check failed")

    def _check(self, p: Player, labels: dict[str, str], held: dict[str, int]) -> None:
        """Report the player's label if it changed, and run them out after enough checks at the run-out level."""
        if (now := self.suspicion.label(p.id)) != labels.get(p.id, "quiet"):
            labels[p.id] = now
            self.feed.on_heat(now, player=p.id)
        held[p.id] = held.get(p.id, 0) + 1 if self.suspicion.level(p.id) >= self.config.run_out_level else 0
        if held[p.id] >= self.config.run_out_checks:
            self.feed.say(MEETING, player=p.id)
            p.end(Summary("lost", self.suspicion.reasons(p.id)))

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
