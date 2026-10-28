import json
import asyncio
import logging
import random
import time

import pytest

from sleuth import engine as engine_mod
from sleuth.actions import IGNORE, MOVE
from sleuth.calibration import Baselines
from sleuth.case import Crime
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.contex_client import Match
from sleuth.decide import Decision
from sleuth.engine import Engine
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.mind import Mind, mind_project
from sleuth.models import Utterance
from sleuth.players import Players
from sleuth.tests.helpers import (
    FakeMind, StubContex, StubRoutine, make, stub_player, wait_for,
)
from sleuth.town import Town

SETTLE = 0.1


class RecordingFeed(Feed):
    def __init__(self):
        super().__init__(Lineage(), Town(), out=None)


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
        self.acts.append(villager.id)
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
async def test_deliver_skips_departed_listeners(turns):
    engine, minds, feed = await setup("v1", "v2", "v3")
    engine.town.remove("v3")
    utt = Utterance("u-1", "v1", "V1", "cafe", "hello", None)
    await engine.deliver(utt, ["v2", "v3"])
    assert minds["v2"].heard == [("utt:u-1", utt.to_data())]
    assert minds["v3"].heard == []
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
    assert "v3" in caplog.text
    await engine.stop()


@pytest.mark.asyncio
async def test_deliver_raises_when_every_listener_fails(turns):
    engine, _, feed = await setup("v1", "v2")
    engine.minds["v2"] = FailingMind(engine.town.get("v2"))
    utt = Utterance("u-1", "v1", "V1", "cafe", "hello", None)
    with pytest.raises(RuntimeError):
        await engine.deliver(utt, ["v2"])
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
async def test_recall_heard_skips_weak_matches_best_first():
    contex = StubContex()
    contex.default = [heard_line("u-3", 0.85), heard_line("u-2", 0.9), heard_line("u-4", 0.82)]
    engine, _, _ = await setup("v1", contex=contex)
    found = await engine.recall_heard("v1", "psst")
    assert [m.data_key for m in found] == ["utt:u-2", "utt:u-3"]
    [(project, query, kwargs)] = contex.queries
    assert (project, query) == (mind_project(engine.config.session, "v1"), "psst")
    assert kwargs == {"top_k": 3, "threshold": 0}
    await engine.stop()


@pytest.mark.asyncio
async def test_a_failed_heard_search_returns_nothing_and_logs_ids_only(caplog):
    engine, _, _ = await setup("v1", contex=StubContex(error=RuntimeError("down 0.93")))
    with caplog.at_level(logging.WARNING):
        assert await engine.recall_heard("v1", "psst") == []
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "v1" in warning.getMessage() and "0.93" not in warning.getMessage()
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


def test_state_round_trips_as_json():
    engine = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    engine._gossip = {"v1": 0.7}
    fresh = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    fresh.restore(json.loads(json.dumps(engine.to_state())))
    assert fresh._gossip == engine._gossip


def test_consumed_keys_round_trip_in_order():
    engine = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    engine._consumed = {"v1": {"utt:u-3": None, "utt:u-2": None}}
    fresh = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), RecordingFeed())
    fresh.restore(json.loads(json.dumps(engine.to_state())))
    assert {vid: list(keys) for vid, keys in fresh._consumed.items()} == {"v1": ["utt:u-3", "utt:u-2"]}


def case_file(state, culprit="v1", roots=None):
    crime = Crime("case-1", "steal", "bike", culprit, "v2", "cafe", 1, "night", 1422, "rival", "Someone stole V2's bike.")
    return CaseFile(crime, {}, state, roots=roots or {})


@pytest.mark.asyncio
async def test_room_speech_rooted_in_a_case_is_shown_in_the_feed_as_hearsay(turns):
    engine, _, feed = await setup("v1", "v2")
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    engine.cases.files["case-1"] = case_file("open", roots={"u-1": "news"})
    engine.lineage.record("u-2", "u-1")
    engine.lineage.record("u-3", "u-1")
    await engine.deliver(Utterance("u-2", "v1", "V1", "cafe", "who took it?", "u-1", audience="room"), ["v2"])
    await engine.deliver(Utterance("u-3", "v1", "V1", "cafe", "between us", "u-1"), ["v2"])
    await engine.deliver(Utterance("u-4", "v1", "V1", "cafe", "nice day", None, audience="room"), ["v2"])
    posts = [e.data for e in feed.recent if e.kind == "post"]
    assert posts == [{"case_id": "case-1", "speaker": "V1 heard", "text": "who took it?", "app": False}]
    assert [e.line for e in feed.recent if e.kind == "post"] == ['V1 heard: "who took it?"']
    await engine.stop()


@pytest.mark.asyncio
async def test_talk_rooted_in_testimony_reaches_minds_but_not_the_feed(turns):
    engine, minds, feed = await setup("v1", "v2")
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    engine.cases.files["case-1"] = case_file("open", roots={"u-1": "memory", "u-5": "news"})
    engine.lineage.record("u-2", "u-1")
    await engine.deliver(Utterance("u-2", "v1", "V1", "cafe", "grey hoodie at ten to one", "u-1", audience="room"),
                         ["v2"])
    assert [k for k, _ in minds["v2"].heard] == ["utt:u-2"]
    assert not [e for e in feed.recent if e.kind == "post"]
    await engine.stop()


@pytest.mark.asyncio
async def test_a_resident_mid_turn_at_the_night_round_goes_home_after_it(turns, monkeypatch):
    game = Game()
    game.phase = "night"
    engine, minds, _ = await setup("v1", game=game)
    engine.routine = StubRoutine({"v1": {"night": "elm street"}})
    release, moves = asyncio.Event(), []

    async def slow_decide(jev, view):
        turns.views.append(view)
        await release.wait()
        return Decision(IGNORE, None, None, None)

    async def act(decision, villager, **kw):
        if decision.target:
            moves.append((villager.id, decision.target))

    monkeypatch.setattr(engine_mod, "decide", slow_decide)
    monkeypatch.setattr(engine_mod, "act", act)
    push(minds["v1"])
    await wait_for(lambda: turns.views)
    await engine._walk("night", 0)
    assert moves == [] and turns.views[0].night
    release.set()
    await wait_for(lambda: moves == [("v1", "elm street")])
    await engine.stop()


@pytest.mark.asyncio
async def test_a_move_picked_after_the_night_round_still_ends_the_night_at_home(turns, monkeypatch):
    game = Game()
    game.phase = "evening"
    engine, minds, _ = await setup("v1", game=game)
    engine.routine = StubRoutine({"v1": {"night": "elm street"}})
    release, moves = asyncio.Event(), []

    async def slow_decide(jev, view):
        turns.views.append(view)
        await release.wait()
        return Decision(MOVE, None, "gym", None)

    async def act(decision, villager, **kw):
        moves.append((villager.id, decision.target))

    monkeypatch.setattr(engine_mod, "decide", slow_decide)
    monkeypatch.setattr(engine_mod, "act", act)
    push(minds["v1"])
    await wait_for(lambda: turns.views)
    game.phase = "night"
    engine._chose_move.clear()
    release.set()
    await wait_for(lambda: moves == [("v1", "gym"), ("v1", "elm street")])
    await engine.stop()


@pytest.mark.asyncio
async def test_press_wakes_the_culprit_once_a_phase(turns):
    game = Game()
    engine, minds, _ = await setup("v1", "v2", game=game)
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    file = engine.cases.files["case-1"] = case_file("open")
    await engine.press(file, "p-1")
    await engine.press(file, "p-1")
    game.tick()
    await engine.press(file, "p-1")
    heard = [data for _, data in minds["v1"].heard]
    line = "The neighborhood app posted: A podcaster is asking around about this: Someone stole V2's bike."
    assert [d["text"] for d in heard] == [line, line]
    assert not minds["v2"].heard and file.pressed == "1:afternoon"
    await engine.stop()


@pytest.mark.asyncio
async def test_a_failed_press_is_tried_again_the_same_phase(turns):
    engine, minds, _ = await setup("v1", game=Game())
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    file = engine.cases.files["case-1"] = case_file("open")

    async def down(*_):
        raise RuntimeError("contex down")

    minds["v1"].hear = down
    with pytest.raises(RuntimeError):
        await engine.press(file, "p-1")
    assert file.pressed == ""
    await engine.stop()


@pytest.mark.asyncio
async def test_a_pressed_culprit_may_warn_someone_close_once_a_phase(turns):
    game = Game()
    engine, minds, feed = await setup("v1", "v2", "v3", game=game)
    engine.cases = Cases(Config(), engine.town, None, random.Random(1), engine.ids)
    file = engine.cases.files["case-1"] = case_file("open")
    engine.town.get("v1").warmth.update({"v2": 0.7, "v3": 0.3})
    assert engine.warn("v1", "v2") is None
    await engine.press(file, "p-1")
    await wait_for(lambda: turns.views)
    assert turns.views[-1].warn and file.pressed_by == "p-1"
    assert engine.warn("v1", "v3") is None
    assert engine.warn("v1", "v2") == "The podcaster is stirring up trouble."
    assert engine.reputation.get("v2", "p-1") == engine.config.reputation_warned
    [colder] = [e for e in feed.recent if e.kind == "system"]
    assert colder.player == "p-1" and colder.data["text"] == "Someone in town seems colder toward you."
    assert engine.warn("v1", "v2") is None and engine.warn("v2", "v1") is None
    game.tick()
    assert engine.warn("v1", "v2") is not None
    assert engine.reputation.get("v2", "p-1") == 2 * engine.config.reputation_warned
    await engine.stop()


class Posting:
    def __init__(self):
        self.calls = 0

    async def post(self, villager, kind, case_text, somber=False):
        self.calls += 1
        return "Has anyone seen my good spatula?"


@pytest.mark.asyncio
async def test_the_clock_posts_chatter_only_while_someone_plays(turns):
    engine, _, feed = await setup("v1", config=Config(chatter_chance=1.0))
    engine.town.get("v1").quirks = ["counts every duck"]
    engine.cases = Cases(engine.config, engine.town, None, random.Random(1), engine.ids)
    engine.writer = Posting()
    engine.players = Players()
    await engine._chatter()
    assert engine.writer.calls == 0 and not [e for e in feed.recent if e.kind == "post"]
    engine.players.add(stub_player())
    await engine._chatter()
    [post] = [e.data for e in feed.recent if e.kind == "post"]
    assert engine.writer.calls == 1
    assert post == {"case_id": None, "speaker": "V1", "text": "Has anyone seen my good spatula?", "app": False}
    await engine.stop()
