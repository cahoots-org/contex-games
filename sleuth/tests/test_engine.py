import json
import asyncio
import logging
import random
import time
from types import SimpleNamespace

import pytest

from sleuth import engine as engine_mod
from sleuth.actions import ANSWER, IGNORE, SPEAK, WARN
from sleuth.calibration import Baselines
from sleuth.case import Crime
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.contex_client import Match
from sleuth.decide import Decision, _state
from sleuth.engine import Engine
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.mind import Mind, mind_project, said_project
from sleuth.models import Utterance
from sleuth.player import Player
from sleuth.players import Players
from sleuth.tests.helpers import (
    PID, TIMEOUT, FakeMind, StubBaselines, StubClient, StubContex, make, stub_player, wait_for,
)
from sleuth.town import NEWCOMER, Town
from sleuth.usage import CountingJev, Usage
from sleuth.writer import Writer

SETTLE = 0.1


class RecordingFeed(Feed):
    def __init__(self):
        super().__init__(Lineage(), Town(), out=None)
        self.deliveries = []

    def on_delivery(self, utterance, listener_ids):
        self.deliveries.append((utterance.id, listener_ids))


class Turns:
    def __init__(self, fail_first=False, leave=False):
        self.views = []
        self.acts = []
        self.fail_first = fail_first
        self.leave = leave
        self.strength = None

    async def decide(self, jev, view):
        self.views.append(view)
        if self.fail_first and len(self.views) == 1:
            raise RuntimeError("jev down")
        return Decision(IGNORE, None, None, None, self.strength)

    async def act(self, decision, villager, *, town, **kw):
        self.acts.append((villager.id, kw["inspiration"]))
        if self.leave:
            town.remove(villager.id)


@pytest.fixture
def turns(monkeypatch):
    t = Turns()
    monkeypatch.setattr(engine_mod, "decide", t.decide)
    monkeypatch.setattr(engine_mod, "act", t.act)
    return t


async def setup(*vids, cooldown=0.05, game=None, contex=None, config=None):
    minds = {}

    def factory(v):
        minds[v.id] = FakeMind(v)
        return minds[v.id]

    feed = RecordingFeed()
    engine = Engine(
        config or Config(cooldown_seconds=cooldown), Town(), contex or StubContex(), None, None, Lineage(), Ids(), feed,
        mind_factory=factory, game=game,
    )
    engine.players.add(stub_player())
    for vid in vids:
        await engine.add_villager(make(vid))
    await engine.run()
    return engine, minds, feed


def push(mind, n=1):
    for _ in range(n):
        mind.queue.put_nowait(None)


@pytest.mark.asyncio
async def test_push_with_no_new_matches_makes_no_turn(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[]]
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 1)
    await asyncio.sleep(SETTLE)
    assert minds["v1"].results == []
    assert turns.views == []
    await engine.stop()


@pytest.mark.asyncio
async def test_pushes_during_cooldown_coalesce_into_one_turn(turns):
    engine, minds, _ = await setup("v1", cooldown=1.0)
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    push(minds["v1"], 3)
    await asyncio.sleep(SETTLE)
    assert len(turns.views) == 1
    await wait_for(lambda: len(turns.views) == 2)
    await asyncio.sleep(SETTLE)
    assert len(turns.views) == 2
    assert minds["v1"].polls == 2
    await engine.stop()


@pytest.mark.asyncio
async def test_turn_exception_is_logged_and_worker_survives(turns, caplog):
    turns.fail_first = True
    engine, minds, _ = await setup("v1")
    with caplog.at_level(logging.ERROR):
        push(minds["v1"])
        await wait_for(lambda: "turn failed for v1" in caplog.text)
    push(minds["v1"])
    await wait_for(lambda: len(turns.acts) == 1)
    await engine.stop()


@pytest.mark.asyncio
async def test_departed_villager_worker_ends(turns):
    turns.leave = True
    engine, minds, _ = await setup("v1")
    push(minds["v1"])
    await wait_for(lambda: "v1" not in engine.minds)
    push(minds["v1"])
    await asyncio.sleep(SETTLE)
    assert len(turns.acts) == 1
    assert minds["v1"].polls == 1
    await engine.stop()


@pytest.mark.asyncio
async def test_deliver_skips_departed_listeners_and_notifies_feed(turns):
    engine, minds, feed = await setup("v1", "v2", "v3")
    engine.town.remove("v3")
    utt = Utterance("u-1", "v1", "V1", "cafe", "hello", None)
    await engine.deliver(utt, ["v2", "v3"])
    assert minds["v2"].heard == [("utt:u-1", utt.to_data())]
    assert minds["v3"].heard == []
    assert feed.deliveries == [("u-1", ["v2"])]
    await engine.stop()


@pytest.mark.asyncio
async def test_a_mind_hears_the_line_without_its_place(turns):
    engine, minds, _ = await setup("v1", "v2")
    await engine.deliver(Utterance("u-1", "v1", "V1", "library", "the bread is stale", None), ["v2"])
    assert minds["v2"].heard == [("utt:u-1", {"id": "u-1", "text": "V1 said: the bread is stale"})]
    await engine.stop()


@pytest.mark.asyncio
async def test_stop_leaves_no_pending_tasks(turns):
    engine, minds, _ = await setup("v1", "v2", game=Game())
    push(minds["v1"])
    await wait_for(lambda: len(turns.acts) == 1)
    await engine.stop()
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert pending == []


@pytest.mark.asyncio
async def test_failed_open_leaves_town_and_engine_unchanged(turns):
    engine, _, _ = await setup("v1")

    class BrokenMind(FakeMind):
        async def open(self):
            raise RuntimeError("contex down")

    engine.mind_factory = BrokenMind
    with pytest.raises(RuntimeError):
        await engine.add_villager(make("v2"))
    assert engine.town.alive_count == 1
    assert [v.id for v in engine.town.villagers] == ["v1"]
    assert list(engine.minds) == ["v1"]
    assert list(engine._tasks) == ["v1"]
    await engine.stop()


class FailingMind(FakeMind):
    async def hear(self, key, data):
        raise RuntimeError("contex down")


@pytest.mark.asyncio
async def test_one_failing_listener_does_not_hide_the_others(turns, caplog):
    engine, minds, feed = await setup("v1", "v2", "v3")
    engine.minds["v3"] = FailingMind(engine.town.get("v3"))
    utt = Utterance("u-1", "v1", "V1", "cafe", "hello", None)
    with caplog.at_level(logging.ERROR):
        await engine.deliver(utt, ["v2", "v3"])
    assert minds["v2"].heard == [("utt:u-1", utt.to_data())]
    assert feed.deliveries == [("u-1", ["v2"])]
    assert "v3" in caplog.text
    await engine.stop()


@pytest.mark.asyncio
async def test_deliver_raises_when_every_listener_fails(turns):
    engine, _, feed = await setup("v1", "v2")
    engine.minds["v2"] = FailingMind(engine.town.get("v2"))
    utt = Utterance("u-1", "v1", "V1", "cafe", "hello", None)
    with pytest.raises(RuntimeError):
        await engine.deliver(utt, ["v2"])
    assert feed.deliveries == []
    await engine.stop()


@pytest.mark.asyncio
async def test_repeated_listen_failures_log_one_traceback(turns, monkeypatch, caplog):
    monkeypatch.setattr(engine_mod, "LISTEN_RETRY_SECONDS", 0.01)
    engine, minds, _ = await setup("v1")

    async def broken():
        raise RuntimeError("contex down")
        yield

    minds["v1"].pushes = broken
    with caplog.at_level(logging.WARNING):
        await wait_for(lambda: len(caplog.records) >= 3)
    await engine.stop()
    with_trace = [r for r in caplog.records if r.exc_info]
    assert len(with_trace) == 1
    assert all("v1" in r.getMessage() for r in caplog.records)


def utterance():
    return Utterance("u-1", "v1", "V1", "cafe", "watch the newcomer", None)


@pytest.mark.asyncio
async def test_addressed_message_wakes_a_villager_whose_needs_did_not_match(turns):
    engine, minds, _ = await setup("v1", "v2")
    minds["v2"].results = [[]]
    utt = utterance()
    await engine.deliver(utt, ["v2"], addressed=True)
    await wait_for(lambda: len(turns.views) == 1)
    view = turns.views[0]
    assert view.villager.id == "v2"
    assert view.new == [Match("utt:u-1", utt.to_data())]
    assert minds["v2"].heard == [("utt:u-1", utt.to_data())]
    await engine.stop()


@pytest.mark.asyncio
async def test_unaddressed_delivery_does_not_bypass_matching(turns):
    engine, minds, _ = await setup("v1", "v2")
    await engine.deliver(utterance(), ["v2"])
    await asyncio.sleep(SETTLE)
    assert minds["v2"].polls == 0
    assert turns.views == []
    assert engine._pending == {}
    await engine.stop()


@pytest.mark.asyncio
async def test_addressed_message_also_matched_by_poll_appears_once(turns):
    engine, minds, _ = await setup("v1", "v2")
    utt = utterance()
    minds["v2"].results = [[Match("utt:u-1", utt.to_data())]]
    await engine.deliver(utt, ["v2"], addressed=True)
    await wait_for(lambda: len(turns.views) == 1)
    assert [m.data_key for m in turns.views[0].new] == ["utt:u-1"]
    assert turns.views[0].recent == []
    await engine.stop()


@pytest.mark.asyncio
async def test_pending_is_cleared_after_the_turn(turns):
    engine, minds, _ = await setup("v1", "v2")
    minds["v2"].results = [[], []]
    await engine.deliver(utterance(), ["v2"], addressed=True)
    await wait_for(lambda: len(turns.views) == 1)
    assert "v2" not in engine._pending
    push(minds["v2"])
    await wait_for(lambda: minds["v2"].polls == 2)
    await asyncio.sleep(SETTLE)
    assert len(turns.views) == 1
    await engine.stop()


@pytest.mark.asyncio
async def test_addressed_message_during_cooldown_is_kept_for_the_next_turn(turns):
    engine, minds, _ = await setup("v1", "v2", cooldown=1.0)
    push(minds["v2"])
    await wait_for(lambda: len(turns.views) == 1)
    minds["v2"].results = [[]]
    await engine.deliver(utterance(), ["v2"], addressed=True)
    await asyncio.sleep(SETTLE)
    assert len(turns.views) == 1
    assert [m.data_key for m in engine._pending["v2"]] == ["utt:u-1"]
    await wait_for(lambda: len(turns.views) == 2)
    assert [m.data_key for m in turns.views[1].new] == ["utt:u-1"]
    await engine.stop()


@pytest.mark.asyncio
async def test_addressed_message_to_a_departed_villager_is_dropped_quietly(turns):
    engine, minds, feed = await setup("v1", "v2")
    await engine.remove_villager("v2")
    await engine.deliver(utterance(), ["v2"], addressed=True)
    assert engine._pending == {}
    assert "v2" not in engine._wakes
    assert minds["v2"].heard == []
    assert feed.deliveries == [("u-1", [])]
    await engine.stop()


@pytest.mark.asyncio
async def test_addressed_listener_who_leaves_during_delivery_is_skipped(turns):
    engine, minds, feed = await setup("v1", "v2", "v3")
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_hear(key, data):
        started.set()
        await release.wait()

    minds["v2"].hear = slow_hear
    delivery = asyncio.create_task(engine.deliver(utterance(), ["v2", "v3"], addressed=True))
    await started.wait()
    await engine.remove_villager("v2")
    release.set()
    await delivery
    assert "v2" not in engine._pending
    assert feed.deliveries == [("u-1", ["v2", "v3"])]
    await wait_for(lambda: [v.villager.id for v in turns.views] == ["v3"])
    await engine.stop()


@pytest.mark.asyncio
async def test_addressed_message_survives_a_failed_poll(turns):
    engine, minds, _ = await setup("v1", "v2")
    mind = minds["v2"]
    real_poll = mind.poll
    mind.results = [[]]

    async def flaky_poll():
        if mind.polls == 0:
            mind.polls += 1
            raise RuntimeError("contex down")
        return await real_poll()

    mind.poll = flaky_poll
    await engine.deliver(utterance(), ["v2"], addressed=True)
    await wait_for(lambda: len(turns.views) == 1)
    assert [m.data_key for m in turns.views[0].new] == ["utt:u-1"]
    await engine.stop()


@pytest.mark.asyncio
async def test_suspicion_strength_updates_scores_and_a_rating_error_does_not_fail_the_turn(turns, caplog):
    engine, minds, _ = await setup("v1")
    engine.lineage.record("w-1", None, player=PID)
    engine.lineage.record("u-0", "w-1")
    engine.facts.record(Utterance("u-0", "v2", "V2", "cafe", "news", "w-1", names_newcomer=True))
    turns.strength = 1.0
    push(minds["v1"])
    await wait_for(lambda: len(turns.acts) == 1)
    view = turns.views[0]
    assert view.names_newcomer == view.new
    assert (view.suspicion, view.warn_threshold) == (0.0, engine.config.warn_threshold)
    assert engine.suspicion.score("v1", PID) == engine.config.suspicion_hear_max

    def broken(*args):
        raise RuntimeError("rating down")

    engine.suspicion.rate = broken
    push(minds["v1"])
    await wait_for(lambda: len(turns.acts) == 2)
    assert turns.views[1].suspicion == engine.config.suspicion_hear_max
    assert "rating down" in caplog.text
    engine.suspect("v1", PID, 0.1, "was warned about the newcomer", "u-1")
    assert engine.suspicion.score("v1", PID) == pytest.approx(engine.config.suspicion_hear_max + 0.1)
    await engine.stop()


def test_default_minds_get_the_engine_baselines():
    config = Config()
    baselines = Baselines(None, config)
    engine = Engine(config, Town(), None, None, None, Lineage(), Ids(), RecordingFeed(), baselines=baselines)
    mind = engine.mind_factory(make("v1"))
    assert isinstance(mind, Mind) and mind.baselines is baselines


@pytest.mark.asyncio
async def test_hit_goes_to_the_next_turn_without_a_push(turns):
    engine, minds, _ = await setup("v1", cooldown=1.0)
    assert engine.cooldown_ends("v1") <= time.time()
    minds["v1"].results = [[]]
    hit = Match("utt:w-1", {"id": "w-1", "text": "psst"}, 0.8)
    engine.hear_directly("v1", hit)
    engine.hear_directly("v1", hit)
    await wait_for(lambda: len(turns.views) == 1)
    assert turns.views[0].new == [hit]
    assert minds["v1"].heard == []
    assert time.time() + 0.5 < engine.cooldown_ends("v1") <= time.time() + 1.0
    await engine.stop()


@pytest.mark.asyncio
async def test_target_leaving_before_the_turn_leaves_no_pending(turns):
    engine, minds, _ = await setup("v1", "v2", cooldown=1.0)
    push(minds["v2"])
    await wait_for(lambda: len(turns.views) == 1)
    engine.hear_directly("v2", Match("utt:w-1", {"id": "w-1"}, 0.8))
    assert [m.data_key for m in engine._pending["v2"]] == ["utt:w-1"]
    await engine.remove_villager("v2")
    assert engine._pending == {}
    assert engine.cooldown_ends("v2") <= time.time()
    engine.hear_directly("v2", Match("utt:w-2", {"id": "w-2"}, 0.8))
    assert engine._pending == {}
    await asyncio.sleep(SETTLE)
    assert len(turns.views) == 1
    await engine.stop()


def whisper_match():
    return Match("utt:w-1", {"id": "w-1", "text": "psst"}, 0.8)


@pytest.mark.asyncio
async def test_whisper_heard_directly_then_polled_reaches_one_turn(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[], [whisper_match()]]
    engine.hear_directly("v1", whisper_match())
    await wait_for(lambda: len(turns.views) == 1)
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 2)
    await asyncio.sleep(SETTLE)
    assert [[m.data_key for m in v.new] for v in turns.views] == [["utt:w-1"]]
    await engine.stop()


@pytest.mark.asyncio
async def test_whisper_polled_then_heard_directly_reaches_one_turn(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[whisper_match()], []]
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    engine.hear_directly("v1", whisper_match())
    await wait_for(lambda: minds["v1"].polls == 2)
    await asyncio.sleep(SETTLE)
    assert [[m.data_key for m in v.new] for v in turns.views] == [["utt:w-1"]]
    assert engine._pending.get("v1") is None
    await engine.stop()


@pytest.mark.asyncio
async def test_a_hit_while_a_turn_is_in_progress_reports_busy(turns, monkeypatch):
    engine, minds, _ = await setup("v1", cooldown=5.0)
    engine.contex = StubContex({"bread": [Match("utt:w-1", {}, 0.9)]})
    engine.baselines = StubBaselines(0.5)
    deciding, release = asyncio.Event(), asyncio.Event()

    async def slow_decide(jev, view):
        deciding.set()
        await release.wait()
        return Decision(IGNORE, None, None, None)

    monkeypatch.setattr(engine_mod, "decide", slow_decide)
    lineage = Lineage()
    feed = Feed(lineage, engine.town, out=None)
    player = Player(engine, engine.town, lineage, Ids(), feed, engine.config, player_id=PID)
    push(minds["v1"])
    await asyncio.wait_for(deciding.wait(), TIMEOUT)
    assert await player.whisper_to("v1", "psst") is None
    status = [e.data for e in feed.recent if e.kind == "whisper_status"][-1]
    assert status["state"] == "busy" and status["until"] > time.time() + 4
    release.set()
    await wait_for(lambda: engine.cooldown_ends("v1") > time.time() and "v1" not in engine._turning)
    await engine.stop()


@pytest.mark.asyncio
async def test_whisper_polled_then_forgotten_then_heard_directly_reaches_one_turn(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[whisper_match()], [], [whisper_match()]]
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    engine.hear_directly("v1", whisper_match())
    await wait_for(lambda: minds["v1"].polls == 2)
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 3)
    await asyncio.sleep(SETTLE)
    assert [[m.data_key for m in v.new] for v in turns.views] == [["utt:w-1"]]
    await engine.stop()


class Relays:
    """Each turn takes the next planned action; a speak relays the first new item to the planned listeners."""

    def __init__(self):
        self.plan = []

    async def decide(self, jev, view):
        action, listeners = self.plan.pop(0)
        return Decision(action, view.new[0], listeners, None)

    async def act(self, decision, villager, *, hub, lineage, ids, **kw):
        if decision.action != SPEAK:
            return
        uid = ids.next("u")
        lineage.record(uid, decision.source.data["id"])
        utterance = Utterance(uid, villager.id, villager.name, "cafe", "did you hear", decision.source.data["id"])
        await hub.deliver(utterance, decision.target)


@pytest.fixture
def relays(monkeypatch):
    r = Relays()
    monkeypatch.setattr(engine_mod, "decide", r.decide)
    monkeypatch.setattr(engine_mod, "act", r.act)
    return r


def statuses(feed):
    return [(e.data["whisper_id"], e.data["villager_id"], e.data["state"], e.data.get("told"))
            for e in feed.recent if e.kind == "whisper_status"]


def whisper(engine, vid, wid="w-1"):
    engine.lineage.record(wid, None, player=PID)
    engine.hear_directly(vid, Match(f"utt:{wid}", {"id": wid, "text": "psst"}, 0.8))


@pytest.mark.asyncio
async def test_turn_that_relays_reports_took_the_bait_with_count(relays):
    engine, minds, feed = await setup("v1", "v2", "v3")
    minds["v1"].results = [[]]
    relays.plan = [(SPEAK, ["v2", "v3"])]
    whisper(engine, "v1")
    await wait_for(lambda: statuses(feed))
    assert statuses(feed) == [("w-1", "v1", "took_the_bait", 2)]
    await engine.stop()


@pytest.mark.asyncio
async def test_turn_that_ignores_reports_kept_then_later_relay_upgrades(relays):
    engine, minds, feed = await setup("v1", "v2")
    minds["v1"].results = [[], [Match("utt:u-9", {"id": "u-9", "text": "the well"})]]
    engine.lineage.record("u-9", "w-1")
    relays.plan = [(IGNORE, None), (SPEAK, ["v2"])]
    whisper(engine, "v1")
    await wait_for(lambda: statuses(feed))
    assert statuses(feed) == [("w-1", "v1", "kept", None)]
    push(minds["v1"])
    await wait_for(lambda: len(statuses(feed)) == 2)
    assert statuses(feed)[1] == ("w-1", "v1", "took_the_bait", 1)
    await engine.stop()


@pytest.mark.asyncio
async def test_a_routine_move_that_carries_a_kept_whisper_takes_the_bait(relays, monkeypatch):
    engine, minds, feed = await setup("v1", "v2")
    minds["v1"].results = [[]]
    relays.plan = [(IGNORE, None)]
    whisper(engine, "v1")
    await wait_for(lambda: statuses(feed))

    async def carry(decision, villager, *, hub, lineage, **kw):
        lineage.record("u-c", decision.source.data["id"])
        line = Utterance("u-c", villager.id, villager.name, "cafe", "did you hear", decision.source.data["id"])
        await hub.deliver(line, ["v2"])

    monkeypatch.setattr(engine_mod, "act", carry)
    await engine._stroll("v1", "gym")
    assert statuses(feed) == [("w-1", "v1", "kept", None), ("w-1", "v1", "took_the_bait", 1)]
    assert "v1" not in engine._said
    await engine.stop()


@pytest.mark.asyncio
async def test_departure_resolves_whispers_still_being_heard(relays):
    engine, _, feed = await setup("v1", "v2")
    feed.on_whisper_status("w-1", "v1", "V1", "heard")
    feed.on_whisper_status("w-2", "v1", "V1", "busy", until=0.0)
    feed.on_whisper_status("w-3", "v1", "V1", "brushed_off")
    feed.on_whisper_status("w-4", "v2", "V2", "checking")
    await engine.remove_villager("v1")
    assert statuses(feed)[4:] == [("w-1", "v1", "kept", None), ("w-2", "v1", "kept", None)]
    feed.on_whisper_status("w-1", "v1", "V1", "heard")
    assert len(statuses(feed)) == 6
    await engine.stop()


class Rater:
    """A Jev that always ignores and is convinced the newcomer is behind it, when asked."""

    def __init__(self):
        self.asked = []

    async def system_one(self, state, questions):
        self.asked.append("suspicion" in questions)
        choices = {"action": SimpleNamespace(choice=IGNORE, probabilities={IGNORE: 1.0})}
        scores = {"suspicion": SimpleNamespace(score=3.0)} if "suspicion" in questions else {}
        return SimpleNamespace(choices=choices, scores=scores)


@pytest.mark.asyncio
async def test_hurtful_gossip_raises_no_suspicion(monkeypatch):
    async def no_act(*args, **kw):
        pass

    monkeypatch.setattr(engine_mod, "act", no_act)
    engine, minds, _ = await setup("v1")
    engine.jev = Rater()
    engine.lineage.record("w-1", None, player=PID)
    engine.lineage.record("u-0", "w-1")
    engine.facts.record(Utterance("u-0", "v2", "V2", "cafe", "Drogo drinks", "w-1", style="exaggerated"))
    minds["v1"].results = [[Match("utt:u-0", {"id": "u-0", "text": "V2 said: Drogo drinks"})]]
    push(minds["v1"])
    await wait_for(lambda: engine.jev.asked)
    assert engine.jev.asked == [False]
    assert engine.suspicion.score("v1", PID) == 0.0
    await engine.stop()


@pytest.mark.asyncio
async def test_a_warning_asks_no_score_question(monkeypatch):
    async def no_act(*args, **kw):
        pass

    monkeypatch.setattr(engine_mod, "act", no_act)
    engine, minds, _ = await setup("v1")
    engine.jev = Rater()
    engine.facts.record(Utterance("u-0", "v2", "V2", "cafe", "Mind the newcomer", None, "warned",
                                  names_newcomer=True, action=WARN, about=PID))
    engine.suspect("v1", PID, 0.1, "was warned about the newcomer", "u-0")
    engine.hear_directly("v1", Match("utt:u-0", {"id": "u-0", "text": "V2 warned: Mind the newcomer"}))
    await wait_for(lambda: engine.jev.asked)
    assert engine.jev.asked == [False]
    assert engine.suspicion.score("v1", PID) == pytest.approx(0.1)
    await engine.stop()


def told(engine, uid, depth=0, audience="one", action=None):
    engine.facts.record(Utterance(uid, "v9", "V9", "bar", "news", None, depth=depth, audience=audience, action=action))


@pytest.mark.asyncio
async def test_deep_retelling_does_not_wake(turns):
    engine, minds, _ = await setup("v1")
    told(engine, "u-deep", depth=3)
    minds["v1"].results = [[Match("k-deep", {"id": "u-deep", "text": "old news"}, 0.9, 0.004)]]
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 1)
    await asyncio.sleep(SETTLE)
    assert turns.views == []
    await engine.stop()


@pytest.mark.asyncio
async def test_room_talk_needs_the_overheard_margin(turns):
    engine, minds, _ = await setup("v1", cooldown=0.0)
    told(engine, "u-room", audience="room")
    told(engine, "u-loud", audience="room")
    minds["v1"].results = [
        [Match("k-room", {"id": "u-room", "text": "murmur"}, 0.9, 0.004)],
        [Match("k-loud", {"id": "u-loud", "text": "shout"}, 0.9, 0.015)],
    ]
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 1)
    await asyncio.sleep(SETTLE)
    assert turns.views == []
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    assert [m.data_key for m in turns.views[0].new] == ["k-loud"]
    await engine.stop()


@pytest.mark.asyncio
async def test_stale_items_become_memories(turns):
    engine, minds, _ = await setup("v1")
    told(engine, "u-stale", depth=5)
    fresh = Match("k-fresh", {"id": "u-fresh", "text": "hot news"}, 0.9, 0.05)
    stale = Match("k-stale", {"id": "u-stale", "text": "old news"}, 0.9, 0.007)
    minds["v1"].results = [[fresh, stale]]
    push(minds["v1"])
    await wait_for(lambda: len(turns.acts) == 1)
    view = turns.views[0]
    assert view.new == [fresh]
    assert stale in view.recent
    assert turns.acts[0][1] == ["hot news"]
    await engine.stop()


@pytest.mark.asyncio
async def test_no_turn_without_a_fresh_item(turns):
    engine, minds, _ = await setup("v1", cooldown=0.0)
    told(engine, "u-stale", depth=5)
    stale = Match("k-stale", {"id": "u-stale", "text": "old news"}, 0.9, 0.007)
    fresh = Match("k-fresh", {"id": "u-fresh", "text": "hot news"}, 0.9, 0.05)
    minds["v1"].results = [[stale], [stale, fresh]]
    push(minds["v1"])
    await wait_for(lambda: minds["v1"].polls == 1)
    await asyncio.sleep(SETTLE)
    assert turns.views == []
    assert "v1" not in engine._last_turn
    assert "k-stale" in engine._consumed["v1"]
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    assert turns.views[0].new == [fresh]
    await engine.stop()


@pytest.mark.asyncio
async def test_the_newcomers_whisper_is_fresh_even_with_negative_clearance(turns):
    engine, minds, _ = await setup("v1")
    engine.lineage.record("w-1", None, player=PID)
    minds["v1"].results = [[Match("k-w", {"id": "w-1", "text": "psst"}, 0.4, -0.01)]]
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    assert [m.data_key for m in turns.views[0].new] == ["k-w"]
    await engine.stop()


@pytest.mark.asyncio
async def test_warnings_always_fresh(turns):
    engine, minds, _ = await setup("v1")
    warning = Utterance("u-warn", "v2", "V2", "bar", "watch the newcomer", None, depth=4, action=WARN)
    engine.facts.record(warning)
    minds["v1"].results = [[]]
    await engine.deliver(warning, ["v1"], addressed=True)
    await wait_for(lambda: len(turns.views) == 1)
    assert [m.data_key for m in turns.views[0].new] == ["utt:u-warn"]
    await engine.stop()


def said_line(uid="u-9", text="Ada said: the well is fine"):
    return Match(f"said:{uid}", {"id": uid, "text": text}, 0.9)


@pytest.mark.asyncio
async def test_spoken_lines_go_to_the_said_project(turns):
    contex = StubContex()
    engine, _, _ = await setup("v1", "v2", contex=contex)
    utt = Utterance("u-1", "v1", "V1", "cafe", "the well is fine", None, "announced")
    await engine.deliver(utt, ["v2"])
    assert contex.published == [(said_project(engine.config.session, "v1"), "said:u-1", utt.to_data())]
    await engine.stop()


@pytest.mark.asyncio
async def test_a_town_crier_line_is_not_remembered_as_said(turns):
    contex = StubContex()
    engine, _, _ = await setup("v1", contex=contex)
    await engine.deliver(Utterance("u-1", "town", "The town crier", "gate", "a newcomer arrives", None, "announced"), ["v1"])
    assert contex.published == []
    await engine.stop()


@pytest.mark.asyncio
async def test_the_players_whispers_are_not_remembered_as_said(turns):
    contex = StubContex()
    engine, _, _ = await setup("v1", contex=contex)
    utt = Utterance("w-1", NEWCOMER, "A newcomer", "cafe", "psst", None, "whispered to you")
    await engine.deliver(utt, ["v1"])
    assert contex.published == []
    await engine.stop()


@pytest.mark.asyncio
async def test_a_failed_said_publish_is_logged_with_ids_only_and_delivery_goes_on(turns, caplog):
    contex = StubContex()

    async def broken(*args):
        raise RuntimeError("down 0.93")

    contex.publish = broken
    engine, minds, _ = await setup("v1", "v2", contex=contex)
    utt = Utterance("u-1", "v1", "V1", "cafe", "the well is fine", None)
    with caplog.at_level(logging.WARNING):
        await engine.deliver(utt, ["v2"])
    assert minds["v2"].heard
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "v1" in warning.getMessage() and "0.93" not in warning.getMessage() and "library" not in warning.getMessage()
    await engine.stop()


async def whisper_turn(turns, contex, **config):
    engine, minds, _ = await setup("v1", contex=contex, config=Config(**{"cooldown_seconds": 0.05, **config}))
    minds["v1"].results = [[]]
    engine.lineage.record("w-1", None, player=PID)
    text = "A newcomer whispered to you: psst"
    engine.hear_directly("v1", Match("utt:w-1", {"id": "w-1", "text": text}, 0.8))
    await wait_for(lambda: len(turns.views) == 1)
    await engine.stop()
    return engine, turns.views[0]


@pytest.mark.asyncio
async def test_newcomer_line_retrieves_related_said_lines(turns):
    contex = StubContex()
    contex.default = [said_line("u-1"), Match("said:u-2", {"id": "u-2", "text": "unrelated"}, 0.5)]
    engine, view = await whisper_turn(turns, contex)
    assert [m.data_key for m in view.said] == ["said:u-1"]
    [(project, query, kwargs)] = [q for q in contex.queries if q[0] == said_project(engine.config.session, "v1")]
    assert query == "psst"
    assert kwargs == {"top_k": 3, "since": None, "threshold": 0}


@pytest.mark.asyncio
async def test_a_turn_without_a_newcomer_line_does_not_search_said(turns):
    contex = StubContex()
    engine, minds, _ = await setup("v1", contex=contex)
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    assert contex.queries == []
    assert turns.views[0].said == []
    await engine.stop()


@pytest.mark.asyncio
async def test_said_floor_is_configurable(turns):
    contex = StubContex()
    contex.default = [said_line()]
    _, view = await whisper_turn(turns, contex, said_floor=0.95)
    assert view.said == []


@pytest.mark.asyncio
async def test_a_failed_said_search_leaves_no_lines_and_logs_ids_only(turns, caplog):
    contex = StubContex(error=RuntimeError("down 0.93"))
    with caplog.at_level(logging.WARNING):
        _, view = await whisper_turn(turns, contex)
    assert view.said == []
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "v1" in warning.getMessage() and "0.93" not in warning.getMessage()


@pytest.mark.asyncio
async def test_said_project_has_no_subscription(turns):
    contex = StubContex()
    contex.default = [said_line()]
    subscribed = []

    async def subscribe(project_id, *args, **kwargs):
        subscribed.append(project_id)

    contex.subscribe = subscribe
    engine, _ = await whisper_turn(turns, contex)
    utt = Utterance("u-1", "v1", "V1", "cafe", "the well is fine", None)
    await engine.deliver(utt, [])
    assert contex.queries and contex.published
    assert not any(p == said_project(engine.config.session, "v1") for p in subscribed)


class Talks:
    """Each turn takes the next planned action, answering the newcomer's line; a planned None fails the turn."""

    def __init__(self):
        self.plan = []
        self.views = []
        self.moods = []

    async def decide(self, jev, view):
        self.views.append(view)
        action = self.plan.pop(0)
        if action is None:
            raise RuntimeError("jev down")
        return Decision(action, view.answerable[-1] if action == ANSWER else view.new[0], None, None)

    async def act(self, decision, villager, **kw):
        self.moods.append(kw.get("mood"))


@pytest.fixture
def talks(monkeypatch):
    t = Talks()
    monkeypatch.setattr(engine_mod, "decide", t.decide)
    monkeypatch.setattr(engine_mod, "act", t.act)
    return t


def reply_whisper(engine, vid, wid, conversation):
    engine.facts.record(Utterance(wid, NEWCOMER, "A newcomer", "cafe", "psst", None, conversation=conversation))
    whisper(engine, vid, wid)


def states(feed):
    return [(wid, state) for wid, _, state, _ in statuses(feed)]


async def answered_once(talks, then, **config):
    engine, minds, feed = await setup("v1", config=Config(**{"cooldown_seconds": 0.05, **config}))
    minds["v1"].results = [[], []]
    talks.plan = [ANSWER, then]
    whisper(engine, "v1", "w-1")
    await wait_for(lambda: statuses(feed))
    assert [m.data_key for m in talks.views[0].answerable] == ["utt:w-1"]
    assert engine.conversations[("v1", PID)] == {"id": "w-1", "answered": ["w-1"]}
    reply_whisper(engine, "v1", "w-2", "w-1")
    await wait_for(lambda: len(statuses(feed)) >= 3)
    await engine.stop()
    return engine, feed


@pytest.mark.asyncio
async def test_cap_ends_with_moved_on(talks):
    engine, feed = await answered_once(talks, ANSWER, talk_turns=2)
    assert states(feed) == [("w-1", "answered"), ("w-2", "answered"), ("w-1", "moved_on"), ("w-2", "moved_on")]
    assert ("v1", PID) not in engine.conversations


@pytest.mark.asyncio
async def test_other_action_ends_with_moved_on(talks):
    engine, feed = await answered_once(talks, IGNORE)
    assert states(feed) == [("w-1", "answered"), ("w-2", "moved_on"), ("w-1", "moved_on")]
    assert ("v1", PID) not in engine.conversations


@pytest.mark.asyncio
async def test_failed_turn_ends_with_moved_on(talks):
    engine, feed = await answered_once(talks, None)
    assert states(feed) == [("w-1", "answered"), ("w-2", "moved_on"), ("w-1", "moved_on")]
    assert ("v1", PID) not in engine.conversations


@pytest.mark.asyncio
async def test_one_villager_holds_a_conversation_with_each_player():
    engine, _, _ = await setup("v1")
    engine.conversations[("v1", "p-a")] = {"id": "w-1", "answered": ["w-1"]}
    engine.conversations[("v1", "p-b")] = {"id": "w-2", "answered": ["w-2"]}
    engine.end_conversation("v1", "p-b")
    assert list(engine.conversations) == [("v1", "p-a")]
    engine.end_conversation("v1")
    assert engine.conversations == {}
    await engine.stop()


@pytest.mark.asyncio
async def test_answerable_leaves_out_a_player_whose_conversation_is_full(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[]]
    full = ["w-0"] * engine.config.talk_turns
    engine.conversations[("v1", "p-a")] = {"id": "w-0", "answered": full}
    engine.lineage.record("w-1", None, player="p-a")
    engine.lineage.record("w-2", None, player="p-b")
    engine.hear_directly("v1", Match("utt:w-1", {"id": "w-1", "text": "psst"}, 0.8))
    engine.hear_directly("v1", Match("utt:w-2", {"id": "w-2", "text": "psst"}, 0.8))
    await wait_for(lambda: len(turns.views) == 1)
    await engine.stop()
    assert [m.data["id"] for m in turns.views[0].answerable] == ["w-2"]


@pytest.mark.asyncio
async def test_no_answer_is_offered_without_a_newcomer_line(talks):
    engine, minds, _ = await setup("v1")
    talks.plan = [IGNORE]
    push(minds["v1"])
    await wait_for(lambda: talks.views)
    assert talks.views[0].answerable == []
    await engine.stop()


@pytest.mark.asyncio
async def test_departure_ends_the_conversation(talks):
    engine, _, feed = await setup("v1")
    engine.conversations[("v1", PID)] = {"id": "w-1", "answered": ["w-1"]}
    await engine.remove_villager("v1")
    assert states(feed) == [("w-1", "moved_on")]
    assert ("v1", PID) not in engine.conversations
    await engine.stop()


@pytest.mark.asyncio
async def test_a_reply_is_remembered_and_reaches_the_feed_not_minds(turns):
    contex = StubContex()
    engine, minds, _ = await setup("v1", "v2", contex=contex)
    lines = []
    engine.feed = Feed(engine.lineage, engine.town, out=lines.append)
    engine.facts.record(Utterance("w-2", NEWCOMER, "A newcomer", "cafe", "psst", None, conversation="w-1"))
    utt = Utterance("u-5", "v1", "V1", "cafe", "Aye, the well.", "w-2", "answered", action=ANSWER)
    await engine.reply(utt)
    assert minds["v2"].heard == [] and minds["v1"].heard == []
    assert contex.published == [(said_project(engine.config.session, "v1"), "said:u-5", utt.to_data())]
    event = engine.feed.recent[-1]
    assert event.kind == "reply"
    assert {k: event.data[k] for k in ("conversation", "villager_id", "name", "text", "uid")} == {
        "conversation": "w-1", "villager_id": "v1", "name": "V1", "text": "Aye, the well.", "uid": "u-5",
    }
    assert lines == ['V1 answers you: "Aye, the well."']
    await engine.stop()


@pytest.mark.asyncio
async def test_two_replies_in_one_turn_keep_the_conversation_when_one_is_answered(talks):
    engine, minds, feed = await setup("v1")
    minds["v1"].results = [[]]
    talks.plan = [ANSWER]
    engine.conversations[("v1", PID)] = {"id": "w-1", "answered": ["w-1"]}
    reply_whisper(engine, "v1", "w-2", "w-1")
    reply_whisper(engine, "v1", "w-3", "w-1")
    await wait_for(lambda: len(statuses(feed)) == 2)
    await engine.stop()
    assert states(feed) == [("w-2", "moved_on"), ("w-3", "answered")]
    assert engine.conversations[("v1", PID)] == {"id": "w-1", "answered": ["w-1", "w-3"]}


@pytest.mark.asyncio
async def test_an_answer_after_the_conversation_closed_reopens_it_on_its_card(talks):
    engine, minds, feed = await setup("v1")
    minds["v1"].results = [[]]
    talks.plan = [ANSWER]
    reply_whisper(engine, "v1", "w-3", "w-1")
    await wait_for(lambda: statuses(feed))
    await engine.stop()
    assert engine.conversations[("v1", PID)] == {"id": "w-1", "answered": ["w-3"]}


@pytest.mark.asyncio
async def test_share_chance_is_nature_times_how_close_the_news_came():
    engine, _, _ = await setup("v1")
    engine._gossip["v1"] = 0.8
    news = lambda clearance: Match("k", {"id": "u"}, 0.9, clearance)  # noqa: E731
    assert engine.share_chance("v1", news(0.01)) == pytest.approx(0.4)
    assert engine.share_chance("v1", news(0.05)) == pytest.approx(0.8)
    assert engine.share_chance("v1", news(None)) == pytest.approx(0.4)
    assert engine.share_chance("v2", news(-0.01)) == 0.0
    await engine.stop()


def heard_line(uid, similarity, text="Bo said: the miller waters his flour"):
    return Match(f"utt:{uid}", {"id": uid, "text": text}, similarity)


@pytest.mark.asyncio
async def test_recall_heard_skips_the_whisper_itself_and_weak_matches():
    contex = StubContex()
    contex.default = [heard_line("w-1", 0.99), heard_line("u-3", 0.85), heard_line("u-2", 0.9), heard_line("u-4", 0.82)]
    engine, _, _ = await setup("v1", contex=contex)
    found = await engine.recall_heard("v1", "A newcomer whispered to you: psst", "w-1")
    assert [m.data_key for m in found] == ["utt:u-2", "utt:u-3"]
    [(project, query, kwargs)] = contex.queries
    assert (project, query) == (mind_project(engine.config.session, "v1"), "psst")
    assert kwargs == {"top_k": 3, "since": None, "threshold": 0}
    await engine.stop()


@pytest.mark.asyncio
async def test_recall_heard_looks_back_over_the_remembered_moves():
    contex = StubContex()
    game = Game(memory_moves=2)
    game.moved(PID)
    game.moved(PID)
    engine, _, _ = await setup("v1", contex=contex, game=game)
    await engine.recall_heard("v1", "psst", "w-1")
    assert contex.queries[0][2]["since"] == game.memory_since() is not None
    await engine.stop()


@pytest.mark.asyncio
async def test_a_failed_heard_search_returns_nothing_and_logs_ids_only(caplog):
    engine, _, _ = await setup("v1", contex=StubContex(error=RuntimeError("down 0.93")))
    with caplog.at_level(logging.WARNING):
        assert await engine.recall_heard("v1", "psst", "w-1") == []
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "v1" in warning.getMessage() and "0.93" not in warning.getMessage()
    await engine.stop()


@pytest.mark.asyncio
async def test_the_turn_view_and_state_carry_what_they_heard(turns):
    contex = StubContex()
    contex.default = [heard_line("w-1", 0.99), heard_line("u-2", 0.9)]
    engine, view = await whisper_turn(turns, contex)
    assert [m.data_key for m in view.heard] == ["utt:u-2"]
    assert _state(view)["things_i_heard_before"] == ["Bo said: the miller waters his flour"]


@pytest.mark.asyncio
async def test_a_turn_without_a_newcomer_line_recalls_nothing_heard(turns):
    engine, minds, _ = await setup("v1")
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    assert turns.views[0].heard == []
    assert "things_i_heard_before" not in _state(turns.views[0])
    await engine.stop()


@pytest.mark.asyncio
async def test_recall_heard_leaves_out_the_newcomers_earlier_whispers():
    contex = StubContex()
    contex.default = [heard_line("w-1", 0.99), heard_line("u-2", 0.9)]
    engine, _, _ = await setup("v1", contex=contex)
    engine.lineage.record("w-1", None, player=PID)
    found = await engine.recall_heard("v1", "psst", "w-2")
    assert [m.data_key for m in found] == ["utt:u-2"]
    await engine.stop()


async def skip_act(*args, **kw):
    pass


def player_whisper(engine, wid, player):
    engine.lineage.record(wid, None, player=player)
    return Match(f"utt:{wid}", {"id": wid, "text": f"A newcomer whispered to you: {wid}"})


@pytest.mark.asyncio
async def test_a_named_line_raises_suspicion_of_the_player_it_roots_in(monkeypatch):
    monkeypatch.setattr(engine_mod, "act", skip_act)
    engine, minds, _ = await setup("v1")
    engine.jev = Rater()
    minds["v1"].results = [[player_whisper(engine, "w-1", "p-a")]]
    push(minds["v1"])
    await wait_for(lambda: engine.jev.asked)
    await wait_for(lambda: engine.suspicion.score("v1", "p-a") > 0)
    assert engine.suspicion.score("v1", "p-b") == 0.0
    await engine.stop()


@pytest.mark.asyncio
async def test_one_turn_naming_two_players_raises_each(monkeypatch):
    monkeypatch.setattr(engine_mod, "act", skip_act)
    engine, minds, _ = await setup("v1")
    engine.jev = Rater()
    minds["v1"].results = [[player_whisper(engine, "w-1", "p-a"), player_whisper(engine, "w-2", "p-b")]]
    push(minds["v1"])
    await wait_for(lambda: engine.suspicion.score("v1", "p-b") > 0)
    hear_max = engine.config.suspicion_hear_max
    assert engine.suspicion.score("v1", "p-a") == engine.suspicion.score("v1", "p-b") == hear_max
    await engine.stop()


@pytest.mark.asyncio
async def test_the_turn_weighs_suspicion_of_the_player_in_front(turns):
    engine, minds, _ = await setup("v1")
    engine.suspect("v1", "p-b", 0.6, "r")
    engine.suspect("v1", "p-a", 0.1, "r")
    minds["v1"].results = [[player_whisper(engine, "w-1", "p-a")]]
    push(minds["v1"])
    await wait_for(lambda: turns.views)
    assert turns.views[0].suspicion == pytest.approx(0.1)
    await engine.stop()


class TokenJev:
    """A Jev whose answers cost a million input tokens per id in the state's villager field."""

    def __init__(self, gate=None):
        self.gate = gate
        self.started = 0

    async def system_one(self, state, questions):
        self.started += 1
        if self.gate:
            await self.gate.wait()
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=1_000_000 * state["n"], output_tokens=0))


class Paying:
    """Each turn asks Jev, then has the writer speak about its first new item, as a real turn does."""

    async def decide(self, jev, view):
        await jev.system_one(state={"n": int(view.villager.id[1:])}, questions={})
        return Decision(SPEAK, view.new[0], None, None)

    async def act(self, decision, villager, *, writer, **kw):
        await writer.complete("system", "user")


async def paying_engine(monkeypatch, *vids, gate=None):
    p = Paying()
    monkeypatch.setattr(engine_mod, "decide", p.decide)
    monkeypatch.setattr(engine_mod, "act", p.act)
    engine, minds, feed = await setup(*vids)
    usage = Usage(Config())
    engine.jev = CountingJev(TokenJev(gate), usage)
    engine.writer = Writer(StubClient(*["Did you hear?"] * len(vids)), "haiku", usage)
    return engine, minds, usage


def hop(engine, uid, root, player):
    engine.lineage.record(root, None, player=player)
    engine.lineage.record(uid, root)
    return Match(f"utt:{uid}", {"id": uid, "text": "V9 said: the well is cursed"})


@pytest.mark.asyncio
async def test_a_turn_on_a_players_rumor_is_charged_to_that_player(monkeypatch):
    engine, minds, usage = await paying_engine(monkeypatch, "v1")
    minds["v1"].results = [[hop(engine, "u-1", "w-1", "p-a")]]
    push(minds["v1"])
    await wait_for(lambda: usage.tokens["haiku"][0])
    assert usage.tokens == {"haiku": [120, 30], "jev": [1_000_000, 0]}
    assert usage.cost("p-a") == pytest.approx(usage.cost()) and usage.cost() > 0
    await engine.stop()


@pytest.mark.asyncio
async def test_village_talk_is_charged_to_no_player(monkeypatch):
    engine, minds, usage = await paying_engine(monkeypatch, "v1")
    engine.lineage.record("u-0", None)
    minds["v1"].results = [[Match("utt:u-0", {"id": "u-0", "text": "V9 said: rain tomorrow"})]]
    push(minds["v1"])
    await wait_for(lambda: usage.tokens["haiku"][0])
    assert usage.cost() > 0 and usage.cost(PID) == usage.cost("p-a") == 0.0
    await engine.stop()


@pytest.mark.asyncio
async def test_concurrent_turns_charge_each_their_own_player(monkeypatch):
    gate = asyncio.Event()
    engine, minds, usage = await paying_engine(monkeypatch, "v1", "v2", gate=gate)
    minds["v1"].results = [[hop(engine, "u-1", "w-1", "p-a")]]
    minds["v2"].results = [[hop(engine, "u-2", "w-2", "p-b")]]
    push(minds["v1"])
    push(minds["v2"])
    await wait_for(lambda: engine.jev.client.started == 2)
    gate.set()
    await wait_for(lambda: usage.tokens["haiku"][0] == 240)
    assert usage.cost("p-a") + usage.cost("p-b") == pytest.approx(usage.cost())
    assert usage.cost("p-b") - usage.cost("p-a") == pytest.approx(0.04)
    await engine.stop()


@pytest.mark.asyncio
async def test_no_turn_while_nobody_is_playing_and_turns_resume_when_a_player_joins(turns):
    engine, minds, feed = await setup("v1")
    engine.players = Players()
    push(minds["v1"])
    await asyncio.sleep(SETTLE)
    assert minds["v1"].polls == 0 and turns.views == []
    engine.players.add(stub_player())
    push(minds["v1"])
    await wait_for(lambda: len(turns.views) == 1)
    await engine.stop()


@pytest.mark.asyncio
async def test_an_answer_carries_how_taken_the_villager_is_with_the_rumor(talks):
    engine, minds, feed = await setup("v1")
    minds["v1"].results = [[], []]
    talks.plan = [ANSWER, ANSWER]
    engine.rapport.sour("v1", PID, 0.5)
    engine.rapport.move("v1", PID, "w-1", 0.6)
    whisper(engine, "v1", "w-1")
    await wait_for(lambda: statuses(feed))
    reply_whisper(engine, "v1", "w-2", "w-1")
    await wait_for(lambda: len(talks.moods) == 2)
    await engine.stop()
    first, second = talks.moods
    assert first.startswith("eager to hear more") and "fond of the newcomer" in first and "Greet the newcomer" in first
    assert second == "eager to hear more"


@pytest.mark.asyncio
async def test_engine_fills_taken_from_interest(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[]]
    engine.rapport.move("v1", PID, "w-1", 0.6)
    whisper(engine, "v1", "w-1")
    await wait_for(lambda: len(turns.views) == 1)
    await engine.stop()
    assert turns.views[0].taken == "eager"


@pytest.mark.asyncio
async def test_taken_follows_a_retelling_back_to_the_players_rumor(turns):
    engine, _, _ = await setup("v1")
    engine.facts.record(Utterance("w-2", NEWCOMER, "A newcomer", "cafe", "psst", None, conversation="w-1"))
    engine.lineage.record("w-2", None, player=PID)
    engine.lineage.record("u-9", "w-2")
    engine.rapport.move("v1", PID, "w-1", -0.5)
    assert engine.taken_by("v1", "u-9") == "put off"
    assert engine.taken_by("v1", "u-unrelated") is None
    await engine.stop()


@pytest.mark.asyncio
async def test_a_villager_who_only_heard_the_rumor_second_hand_has_no_taken_word(turns):
    engine, minds, _ = await setup("v1")
    minds["v1"].results = [[]]
    engine.rapport.sour("v1", PID, 0.5)
    engine.rapport.move("v2", PID, "w-1", 0.6)
    whisper(engine, "v1", "w-1")
    await wait_for(lambda: len(turns.views) == 1)
    await engine.stop()
    assert turns.views[0].taken is None and engine.taken_by("v1", "w-1") is None
    assert engine.taken_by("v2", "w-1") == "eager"


@pytest.mark.asyncio
async def test_a_reply_that_fails_keeps_the_greeting_for_the_next(talks, monkeypatch):
    engine, minds, feed = await setup("v1")
    minds["v1"].results = [[], [], []]
    talks.plan = [ANSWER, ANSWER, ANSWER]
    engine.rapport.sour("v1", PID, 0.5)
    act = talks.act

    async def failing_once(decision, villager, **kw):
        await act(decision, villager, **kw)
        if len(talks.moods) == 1:
            raise RuntimeError("haiku down")

    monkeypatch.setattr(engine_mod, "act", failing_once)
    whisper(engine, "v1", "w-1")
    await wait_for(lambda: len(talks.moods) == 1 and not engine._turning)
    engine._last_turn.clear()
    reply_whisper(engine, "v1", "w-2", "w-1")
    await wait_for(lambda: len(talks.moods) == 2 and not engine._turning)
    engine._last_turn.clear()
    reply_whisper(engine, "v1", "w-3", "w-1")
    await wait_for(lambda: len(talks.moods) == 3)
    await engine.stop()
    assert ["Greet the newcomer" in m for m in talks.moods] == [True, True, False]


def test_state_round_trips_as_json():
    engine = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    engine._gossip = {"v1": 0.7}
    engine._kept = {"v1": {"w-2": None, "w-1": None}}
    fresh = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    fresh.restore(json.loads(json.dumps(engine.to_state())))
    assert fresh._gossip == engine._gossip
    assert {vid: list(kept) for vid, kept in fresh._kept.items()} == {"v1": ["w-2", "w-1"]}


def test_consumed_keys_round_trip_and_a_whisper_cut_off_by_the_restart_is_kept():
    engine = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    engine._consumed = {"v1": {"utt:w-1": None, "utt:u-2": None}}
    feed = RecordingFeed()
    feed._listening = {"w-1": ("v1", "Marta"), "w-3": ("v1", "Marta")}
    fresh = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), feed)
    fresh.restore(json.loads(json.dumps(engine.to_state())))
    assert {vid: list(keys) for vid, keys in fresh._consumed.items()} == {"v1": ["utt:w-1", "utt:u-2"]}
    assert [(e.data["whisper_id"], e.data["state"]) for e in feed.recent] == [("w-1", "kept")]
    assert feed.listening("v1") == [("w-3", "Marta")]


def case_file(state, culprit="v1", roots=None):
    crime = Crime("case-1", "steal", "bike", culprit, "v2", "cafe", 1, "night", 1422, "rival", "Someone stole V2's bike.")
    return CaseFile(crime, {}, state, roots=roots or {})


@pytest.mark.asyncio
async def test_room_speech_rooted_in_a_case_is_posted_to_the_app(turns):
    engine, _, feed = await setup("v1", "v2")
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    engine.cases.files["case-1"] = case_file("open", roots={"u-1": "news"})
    engine.lineage.record("u-2", "u-1")
    engine.lineage.record("u-3", "u-1")
    await engine.deliver(Utterance("u-2", "v1", "V1", "cafe", "who took it?", "u-1", audience="room"), ["v2"])
    await engine.deliver(Utterance("u-3", "v1", "V1", "cafe", "between us", "u-1"), ["v2"])
    await engine.deliver(Utterance("u-4", "v1", "V1", "cafe", "nice day", None, audience="room"), ["v2"])
    posts = [e.data for e in feed.recent if e.kind == "post"]
    assert posts == [{"case_id": "case-1", "speaker": "V1", "text": "who took it?"}]
    await engine.stop()


@pytest.mark.asyncio
async def test_culprit_is_not_walked_during_setup(turns):
    engine, _, _ = await setup("v1", "v2")
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    engine.cases.files["case-1"] = case_file("setup")
    assert not engine._free_to_walk("v1") and engine._free_to_walk("v2")
    engine.cases.files["case-1"].state = "open"
    assert engine._free_to_walk("v1")
    await engine.stop()


@pytest.mark.asyncio
async def test_press_wakes_the_culprit_once_a_phase(turns):
    game = Game()
    engine, minds, _ = await setup("v1", "v2", game=game)
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    file = engine.cases.files["case-1"] = case_file("open")
    await engine.press(file)
    await engine.press(file)
    game.tick()
    await engine.press(file)
    heard = [data for _, data in minds["v1"].heard]
    line = "The neighborhood app posted: A podcaster is asking around about this: Someone stole V2's bike."
    assert [d["text"] for d in heard] == [line, line]
    assert not minds["v2"].heard and file.pressed == "1:afternoon"
    await engine.stop()
