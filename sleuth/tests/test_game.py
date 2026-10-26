import json
import asyncio
import logging
import time

import pytest

from sleuth import engine as engine_mod
from sleuth import game as game_mod
from sleuth.actions import MOVE
from sleuth.config import Config
from sleuth.contex_client import Match
from sleuth.engine import Engine
from sleuth.feed import Feed
from sleuth.game import MEMORY_PLAYERS, Game
from sleuth.lineage import Ids, Lineage
from sleuth.player import Player
from sleuth.players import Players
from sleuth.tests.helpers import PID, FakeMind, make, wait_for
from sleuth.town import PLACES, Town

async def start(*vids, **cfg):
    town, lineage, lines = Town(), Lineage(), []
    feed = Feed(lineage, town, out=lines.append)
    game = Game()
    config = Config(**{"day_seconds": 0.05, **cfg})
    engine = Engine(
        config, town, None, None, None, lineage, Ids(), feed,
        mind_factory=FakeMind, game=game,
    )
    player = Player(engine, town, lineage, Ids(), feed, config, player_id=PID)
    engine.players.add(player)
    player.connected()
    for vid in vids:
        await engine.add_villager(make(vid))
    return engine, player, feed, lines


class StubRoutine:
    """Sends each villager to one place at every part of the day."""

    def __init__(self, places):
        self.places = places

    def place(self, vid, phase):
        return self.places.get(vid)


def record_moves(monkeypatch, engine, delay=0.0):
    """Replace act with one that moves the villager after delay and records (vid, decision, share_chance, time)."""
    moves = []

    async def act(decision, v, *, town, share_chance=0.0, **_):
        moves.append((v.id, decision, share_chance, time.monotonic()))
        await asyncio.sleep(delay)
        town.move(v.id, decision.target)

    monkeypatch.setattr(engine_mod, "act", act)
    return moves


def kinds(feed, kind):
    return [e for e in feed.replay(PID) if e.kind == kind]


def test_memory_starts_at_the_oldest_remembered_move():
    game = Game(memory_moves=2)
    game.moved(PID)
    assert game.memory_since() is None
    game.moved(PID)
    first = game.memory_since()
    game.moved(PID)
    assert first is not None and game.memory_since() >= first


def test_memory_spans_the_moves_of_every_active_player():
    game = Game(memory_moves=2)
    game.moved("p-a")
    game.moved("p-a")
    first = game.memory_since()
    assert first is not None
    game.moved("p-b")
    assert game.memory_since() is None
    game.moved("p-b")
    assert game.memory_since() == first


def test_memory_stays_capped_beyond_the_most_players_it_counts():
    game = Game(memory_moves=2)
    for i in range(2 * MEMORY_PLAYERS):
        game.moved(f"p-{i % (MEMORY_PLAYERS + 1)}")
    assert game.memory_since() is not None


@pytest.mark.asyncio
async def test_an_idle_player_stops_widening_memory():
    game = Game(memory_moves=1, day_seconds=0.01)
    game.moved("p-a")
    game.moved("p-b")
    await asyncio.sleep(0.02)
    game.moved("p-a")
    assert game.memory_since() is not None


def test_the_clock_runs_through_the_day_and_into_the_next():
    game = Game()
    assert (game.day, game.phase) == (1, "morning")
    seen = []
    for _ in range(4):
        game.tick()
        seen.append((game.day, game.phase))
    assert seen == [(1, "afternoon"), (1, "evening"), (1, "night"), (2, "morning")]


@pytest.mark.asyncio
async def test_the_engine_announces_each_part_of_the_day():
    engine, _, feed, _ = await start("v1", day_seconds=0.04)
    game = engine.game
    await engine.run()
    await wait_for(lambda: len(kinds(feed, "time")) >= 3)
    await engine.stop()
    assert [(e.data["day"], e.data["phase"]) for e in kinds(feed, "time")][:3] == [
        (1, "afternoon"), (1, "evening"), (1, "night"),
    ]
    assert (game.day, game.phase) != (1, "morning")


@pytest.mark.asyncio
async def test_the_clock_walks_villagers_to_their_routine_place():
    engine, _, _, _ = await start("v1", "v2", day_seconds=0.2)
    engine.routine = StubRoutine({"v1": "gym", "v2": "bar"})
    await engine.run()
    await wait_for(lambda: (engine.town.place_of("v1"), engine.town.place_of("v2")) == ("gym", "bar"))
    await engine.stop()


@pytest.mark.asyncio
async def test_a_villager_in_a_turn_or_a_chosen_move_stays_put():
    vids = ("v1", "v2", "v3")
    engine, _, _, _ = await start(*vids)
    engine.routine = StubRoutine(dict.fromkeys(vids, "gym"))
    engine._turning.add("v1")
    engine._chose_move.add("v2")
    await engine._walk("morning", 0.0)
    assert [engine.town.place_of(v) for v in vids] == ["cafe", "cafe", "gym"]
    await engine.stop()


@pytest.mark.asyncio
async def test_a_failing_round_is_logged(caplog):
    engine, _, _, _ = await start("v1")

    class Broken:
        def place(self, vid, phase):
            raise RuntimeError("no places")

    engine.routine = Broken()
    with caplog.at_level(logging.ERROR):
        await engine._walk("morning", 0.0)
    assert "routine round failed" in caplog.text
    await engine.stop()


@pytest.mark.asyncio
async def test_a_departed_villager_is_not_moved(caplog):
    vids = ("v2", "v3", "v4", "v5", "v6", "v1")
    engine, _, _, _ = await start(*vids)
    engine.routine = StubRoutine(dict.fromkeys(vids, "gym"))
    walk = asyncio.create_task(engine._walk("morning", 0.4))
    await wait_for(lambda: engine.town.place_of("v2") == "gym")
    engine.town.remove("v1")
    with caplog.at_level(logging.ERROR):
        await walk
    assert not any("v1" in [v.id for v in engine.town.present(p)] for p in PLACES)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    await engine.stop()


@pytest.mark.asyncio
async def test_a_routine_move_may_carry_the_latest_news(monkeypatch):
    engine, _, _, _ = await start("v1")
    engine.routine = StubRoutine({"v1": "gym"})
    moves = record_moves(monkeypatch, engine)
    latest = Match("k1", {"id": "u-1", "text": "the miller cheats"}, clearance=0.05)
    engine._latest["v1"] = latest
    await engine._walk("morning", 0.0)
    [(vid, decision, share, _)] = moves
    assert (vid, decision.action, decision.source, decision.target) == ("v1", MOVE, latest, "gym")
    assert share == engine.share_chance("v1", latest)
    await engine.stop()


@pytest.mark.asyncio
async def test_a_routine_move_carries_fresh_news_once(monkeypatch):
    engine, _, _, _ = await start("v1", "v2")
    engine.routine = StubRoutine({"v1": "gym", "v2": "gym"})
    moves = record_moves(monkeypatch, engine)
    engine._latest["v1"] = Match("k1", {"id": "u-1", "text": "the miller cheats"}, clearance=0.05)
    engine._latest["v2"] = Match("k2", {"id": "u-2", "text": "the well is dry"}, clearance=-0.01)
    await engine._walk("morning", 0.0)
    engine.routine = StubRoutine({"v1": "bar", "v2": "bar"})
    await engine._walk("evening", 0.0)
    assert [(vid, d.source and d.source.data_key) for vid, d, *_ in moves] == [
        ("v1", "k1"), ("v2", None), ("v1", None), ("v2", None),
    ]
    await engine.stop()


@pytest.mark.asyncio
async def test_routine_moves_come_in_batches_of_five_across_the_window(monkeypatch):
    vids = [f"v{i}" for i in range(12)]
    engine, _, _, _ = await start(*vids)
    engine.routine = StubRoutine(dict.fromkeys(vids, "gym"))
    moves = record_moves(monkeypatch, engine)
    spread = 0.6
    await engine._walk("morning", spread)
    times = [t for *_, t in moves]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert [vid for vid, *_ in moves] == vids
    assert all(gaps[i] >= 0.9 * spread / 3 for i in (4, 9))
    assert all(g < 0.5 * spread / 3 for i, g in enumerate(gaps) if i not in (4, 9))
    await engine.stop()


@pytest.mark.asyncio
async def test_phases_stay_evenly_spaced_with_a_routine(monkeypatch):
    vids = [f"v{i}" for i in range(12)]
    engine, _, feed, _ = await start(*vids, day_seconds=0.4)
    engine.routine = StubRoutine(dict.fromkeys(vids, "gym"))
    record_moves(monkeypatch, engine, delay=5.0)
    ticks = []
    on_time = feed.on_time
    monkeypatch.setattr(feed, "on_time", lambda day, phase: (ticks.append(time.monotonic()), on_time(day, phase)))
    await engine.run()
    await wait_for(lambda: len(ticks) >= 4)
    await engine.stop()
    assert all(b - a < 1.0 for a, b in zip(ticks, ticks[1:4]))


def test_the_clock_says_how_far_through_the_day_it_is(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(game_mod.time, "time", lambda: now[0])
    game = Game(day_seconds=120.0)
    now[0] += 15
    assert game.clock() == {"day": 1, "phase": "morning", "fraction": 0.125, "day_seconds": 120.0}
    game.tick()
    now[0] += 60
    assert game.clock()["fraction"] == 0.5


@pytest.mark.asyncio
async def test_no_routine_walks_while_the_only_run_is_away():
    engine, player, feed, _ = await start("v1", "v2")
    engine.players = Players()
    engine.players.add(Player(engine, engine.town, engine.lineage, Ids(), feed, engine.config, player_id="p-away"))
    engine.routine = StubRoutine({"v1": "gym", "v2": "bar"})
    await engine._walk("morning", 0.0)
    assert (engine.town.place_of("v1"), engine.town.place_of("v2")) == ("cafe", "cafe")
    await engine.stop()


def test_game_state_round_trips_with_the_phase_part_elapsed(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(game_mod.time, "time", lambda: now[0])
    game = Game(memory_moves=2, day_seconds=400.0)
    game.tick()
    game.tick()
    game.moved("p-1")
    now[0] += 25.0
    game.moved("p-2")
    state = json.loads(json.dumps(game.to_state()))
    now[0] = 5000.0
    fresh = Game(memory_moves=2, day_seconds=400.0)
    fresh.restore(state)
    assert (fresh.day, fresh.phase) == (game.day, game.phase)
    assert fresh.phase_started == pytest.approx(5000.0 - 25.0)
    assert list(fresh._moves) == [(1000.0, "p-1"), (1025.0, "p-2")]
