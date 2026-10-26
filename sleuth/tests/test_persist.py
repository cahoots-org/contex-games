import asyncio
import json
import logging
import os
import random
import time
from types import SimpleNamespace

import httpx
import pytest

from sleuth import engine as engine_mod
from sleuth import persist, web
from sleuth.actions import IGNORE
from sleuth.case import Crime, Record
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.decide import Decision
from sleuth.engine import Engine
from sleuth.facts import Facts
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.persist import components, load_game, restore_game, resume_game, save_every, save_game, state_path, stop
from sleuth.player import Player
from sleuth.players import Players
from sleuth.tests.helpers import FakeMind, StubBaselines, StubContex, wait_for
from sleuth.town import Town
from sleuth.usage import Usage
from sleuth.web import create_app

SESSION = "s1"
NOW = 1_800_000_000.0
SAID = "the miller waters his flour"
RETELLING = "they say the miller waters his flour"
VILLAGERS = [
    Villager("v1", "Marta Hale", "herbalist", "anxious", "none", ["bread"], {}),
    Villager("v2", "Bert Cole", "miller", "jolly", "none", ["flour"], {}),
    Villager("v3", "Ida Fenn", "smith", "grim", "none", ["iron"], {}),
    Villager("v4", "Ned Rowe", "baker", "calm", "none", ["yeast"], {}),
]


async def ignore(jev, view):
    return Decision(IGNORE, None, None, None)


def build(contex=None):
    """A game wired as __main__ wires it, with stub Contex, Jev and writer and no villagers yet."""
    config = Config(session=SESSION)
    contex = contex or StubContex()
    town, lineage, ids, facts = Town(), Lineage(), Ids(), Facts()
    feed = Feed(lineage, town, out=None)
    game, usage, baselines = Game(config.memory_moves, config.day_seconds), Usage(config), StubBaselines(0.5)
    engine = Engine(
        config, town, contex, None, None, lineage, ids, feed, mind_factory=FakeMind, game=game, baselines=baselines,
        facts=facts,
        cases=Cases(config, town, None, random.Random(1), ids),
    )
    players = Players(usage)
    engine.players = players

    def make(pid, owner):
        return Player(engine, town, lineage, ids, feed, config, None, game, player_id=pid, owner=owner)

    return SimpleNamespace(engine=engine, players=players, make=make, parts=components(engine), feed=feed)


async def api_state(g, owner):
    app = create_app(
        players=g.players, join=None, town=g.engine.town, feed=g.feed, usage=g.players.usage, port=8023,
        suspicion=g.engine.suspicion, game=g.engine.game,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8023") as client:
        client.cookies.set(web.COOKIE, owner)
        state = (await client.get("/api/state")).json()
    del state["boot"]
    return state


async def played(monkeypatch):
    """A scripted game: a player walks, a villager says something and another retells it."""
    monkeypatch.setattr(time, "time", lambda: NOW)
    monkeypatch.setattr(engine_mod, "decide", ignore)
    g = build()
    for v in VILLAGERS:
        await g.engine.add_villager(v, "cafe")
    g.engine.town.found_group("v2", "Millers", "flour first")
    player = g.make("p-abc", "o-abc")
    g.players.add(player)
    player.connected()
    assert player.walk("bar") is None
    said = Utterance(g.engine.ids.next("u"), "v2", "Bert Cole", "cafe", SAID, None, action="speak")
    g.engine.lineage.record(said.id, None)
    g.engine.facts.record(said)
    await g.engine.deliver(said, ["v1"])
    retold = Utterance(g.engine.ids.next("u"), "v1", "Marta Hale", "cafe", RETELLING, said.id, "retold",
                       depth=1, action="retell")
    g.engine.lineage.record(retold.id, said.id)
    g.engine.facts.record(retold)
    await g.engine.deliver(retold, ["v2"])
    player.disconnected()
    await g.engine.stop()
    return g, player


def assert_next_ids_are_new(fresh, g, player):
    ids, skip = fresh.engine.ids, persist.ID_MARGIN
    assert ids.next("u") == f"u-{2 + skip + 1}"


@pytest.mark.asyncio
async def test_a_played_game_restores_to_the_same_state_with_fresh_ids(monkeypatch, tmp_path):
    g, player = await played(monkeypatch)
    before = await api_state(g, player.owner)
    path = state_path(SESSION, str(tmp_path))
    save_game(path, g.parts, SESSION)

    fresh = build()
    assert resume_game(path, SESSION, fresh.parts, fresh.make)
    restored = fresh.players.get(player.id)
    assert await api_state(fresh, player.owner) == before
    assert fresh.parts["town"].groups == g.engine.town.groups
    assert not fresh.players.any_playing()
    restored.connected()
    assert fresh.players.any_playing()

    assert_next_ids_are_new(fresh, g, player)
    assert fresh.feed.say("next").id == g.feed.recent[-1].id + 1
    assert fresh.engine.town.found_group("v1", "New", "x").id == "g-2"


@pytest.mark.asyncio
async def test_counters_resume_past_every_id_in_use_even_when_saved_counters_lag(monkeypatch, tmp_path):
    g, player = await played(monkeypatch)
    path = state_path(SESSION, str(tmp_path))
    save_game(path, g.parts, SESSION)
    state = load_game(path, SESSION)
    state["ids"] = {}
    state["feed"]["last_id"] = 0
    state["feed"]["closed"] = {"p-old": 999}

    fresh = build()
    assert restore_game(state, fresh.parts, fresh.make)
    assert_next_ids_are_new(fresh, g, player)
    assert fresh.feed.say("next").id == 1000


def test_a_save_is_written_whole_or_not_at_all(tmp_path, monkeypatch):
    g = build()
    path = state_path(SESSION, str(tmp_path))
    save_game(path, g.parts, SESSION)
    before = open(path).read()

    def torn(state, f):
        f.write('{"version": 1, "sess')
        raise OSError("disk full")

    monkeypatch.setattr(persist.json, "dump", torn)
    with pytest.raises(OSError):
        save_game(path, g.parts, SESSION)
    assert open(path).read() == before
    assert load_game(path, SESSION) is not None


@pytest.mark.parametrize("content", [None, "{not json", json.dumps({"version": 99, "session": SESSION}),
                                     json.dumps({"version": persist.STATE_VERSION, "session": "other"}), "[]"])
def test_a_save_that_cannot_be_used_is_logged_and_set_aside(tmp_path, caplog, monkeypatch, content):
    monkeypatch.setattr(time, "time", lambda: NOW)
    path = state_path(SESSION, str(tmp_path))
    if content is not None:
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write(content)
    with caplog.at_level(logging.INFO, logger="sleuth.persist"):
        assert load_game(path, SESSION) is None
    assert "starting fresh" in caplog.text
    assert not os.path.exists(path)
    if content is not None:
        with open(f"{path}.bad-{int(NOW)}") as f:
            assert f.read() == content


@pytest.mark.asyncio
async def test_a_save_that_fails_to_restore_leaves_the_game_fresh(monkeypatch, tmp_path, caplog):
    g, player = await played(monkeypatch)
    path = state_path(SESSION, str(tmp_path))
    save_game(path, g.parts, SESSION)
    state = load_game(path, SESSION)
    del state["game"]["day"]
    with open(path, "w") as f:
        json.dump(state, f)

    fresh = build()
    for v in VILLAGERS:
        fresh.engine.town.add(v)
    assert not resume_game(path, SESSION, fresh.parts, fresh.make)
    assert "could not be restored" in caplog.text
    assert not os.path.exists(path) and os.path.exists(f"{path}.bad-{int(NOW)}")
    assert fresh.players.get(player.id) is None and not fresh.feed.recent
    assert fresh.engine.ids.next("u") == "u-1"
    assert [v.id for v in fresh.engine.town.villagers] == [v.id for v in VILLAGERS]


@pytest.mark.asyncio
async def test_a_stop_signal_saves_then_cancels_the_game(tmp_path):
    g = build()
    path = state_path(SESSION, str(tmp_path))
    task = asyncio.create_task(asyncio.Event().wait())
    stop(lambda: save_game(path, g.parts, SESSION), task)
    assert load_game(path, SESSION)["session"] == SESSION
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_the_game_is_saved_every_interval():
    saves = []
    task = asyncio.create_task(save_every(0, lambda: saves.append(1)))
    await wait_for(lambda: len(saves) >= 3)
    task.cancel()


def test_setting_aside_a_missing_save_does_nothing(tmp_path):
    persist.set_aside(state_path(SESSION, str(tmp_path)))
    assert not os.listdir(tmp_path)


def test_components_have_no_pressure():
    assert "pressure" not in build().parts


def test_restore_resumes_record_and_case_ids(tmp_path):
    g = build()
    crime = Crime("case-3", "steal", "bike", "v1", "v2", "cafe", 1, "night", 1422, "rival", "Someone stole a bike.")
    record = Record("r-5", "case-3", "clip", "cafe", "11:42pm", "a figure")
    g.engine.cases.files["case-3"] = CaseFile(crime, {"r-5": record}, "open")
    path = state_path(SESSION, str(tmp_path))
    save_game(path, g.parts, SESSION)
    state = load_game(path, SESSION)
    state["ids"] = {}

    fresh = build()
    assert restore_game(state, fresh.parts, fresh.make)
    assert fresh.engine.cases.files == g.engine.cases.files
    assert int(fresh.engine.ids.next("r").split("-")[1]) > 5 and int(fresh.engine.ids.next("case").split("-")[1]) > 3
