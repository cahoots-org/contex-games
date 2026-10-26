import json
import asyncio
from types import SimpleNamespace

import pytest

import time
from dataclasses import replace

from sleuth.contex_client import Match
from sleuth.game import Summary
from sleuth.lineage import Ids
from sleuth.models import Utterance, Villager
from sleuth.actions import SPEAK
from sleuth.player import ALREADY_LISTENING, GAME_OVER, MAX_ASK_CHARS, Player, Refusal
from sleuth.players import Players
from sleuth.config import Config
from sleuth.tests.helpers import PID, StubClient, wait_for
from sleuth.tests.helpers import make_player as make
from sleuth.town import NEWCOMER
from sleuth.usage import Usage
from sleuth.writer import Writer


def test_someone_is_playing_only_while_a_connected_player_is_not_over():
    players = Players()
    assert not players.any_playing()
    p = make("Ann")[0]
    players.add(p)
    p.connected()
    assert players.any_playing()
    p.end(Summary("lost", []))
    assert not players.any_playing()


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def run_of(player, pid):
    """Another run in the player's world, with its own id and owner."""
    return Player(
        player.engine, player.town, player.lineage, Ids(), player.feed, player.config, player_id=pid, owner=f"o-{pid}",
    )


def test_a_run_that_only_loaded_the_page_never_plays(clock):
    players = Players()
    p = make("Ann")[0]
    players.add(p)
    assert not players.any_playing() and players.at(p.place) == []
    clock[0] += 10 * p.config.idle_after_seconds
    assert not players.any_playing()


def test_a_run_plays_while_connected_and_for_idle_after_seconds_after_it_disconnects(clock):
    players = Players()
    p = make("Ann")[0]
    players.add(p)
    p.connected()
    p.connected()
    clock[0] += 10 * p.config.idle_after_seconds
    p.disconnected()
    assert players.any_playing() and players.at(p.place) == [p]
    p.disconnected()
    clock[0] += p.config.idle_after_seconds - 1
    assert players.any_playing()
    clock[0] += 1
    assert not players.any_playing() and players.at(p.place) == []


@pytest.mark.parametrize("act", [lambda p: p.walk("library"), lambda p: p.touch()])
def test_a_run_plays_for_idle_after_seconds_after_an_action(clock, act):
    players = Players()
    p = make("Ann")[0]
    players.add(p)
    act(p)
    clock[0] += p.config.idle_after_seconds - 1
    assert players.any_playing() and players.at(p.place) == [p]
    clock[0] += 1
    assert not players.any_playing() and players.at(p.place) == []


def test_a_new_run_prunes_only_stale_runs_that_never_played(clock):
    first = make("Ann")[0]
    players = Players()
    stale, played = (run_of(first, pid) for pid in ("p-stale", "p-played"))
    played.touch()
    for p in (stale, played):
        players.add(p)
    clock[0] += first.config.idle_after_seconds
    recent = run_of(first, "p-recent")
    players.add(recent)
    assert players.prune() == [stale]
    assert [p.id for p in players] == ["p-played", "p-recent"]
    assert players.live(stale.owner) is None and players.get("p-stale") is None


@pytest.mark.asyncio
async def test_walk_moves_the_player_and_tells_only_them():
    player, town, _, engine, _ = make("Marta")
    assert player.walk("gym") is None
    assert player.place == "gym"
    last = player.feed.replay(PID)[-1]
    assert (last.kind, last.player, last.data["place"]) == ("place", PID, "gym")
    assert all(engine.suspicion.score(v.id, PID) == 0 for v in town.find(""))


@pytest.mark.asyncio
async def test_walk_refuses_an_unknown_place_the_same_place_and_a_finished_game():
    player, _, _, _, _ = make("Marta")
    assert "There's no moon here" in player.walk("moon")
    assert player.walk("cafe") == "You're already at the cafe."
    player.end(Summary("lost", []))
    assert player.walk("gym") == GAME_OVER


def square_line(uid, text, speaker="v1", place="cafe", action=SPEAK):
    return Utterance(uid, speaker, speaker.upper(), place, text, None, action=action)


@pytest.mark.asyncio
async def test_listen_opens_with_the_last_five_lines_of_this_part_of_the_day(monkeypatch):
    player, _, _, engine, _ = make("Marta")
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: 1.0)
        engine.facts.record(square_line("u-0", "long ago"))
    for i in range(1, 7):
        engine.facts.record(square_line(f"u-{i}", f"line {i}"))
    engine.facts.record(square_line("t-1", "tavern talk", place="bar"))
    engine.facts.record(square_line("n-1", "psst", speaker=NEWCOMER))
    engine.facts.record(square_line("x-1", "beware", action="warn"))
    assert player.listen() is None
    event = next(e for e in player.feed.replay(PID) if e.kind == "listen")
    assert event.player == PID and event.data["ended"] is False and event.data["place"] == "cafe"
    assert [line["text"] for line in event.data["lines"]] == [f"line {i}" for i in range(2, 7)]
    assert event.data["lines"][0] == {"speaker": "v1", "speaker_name": "V1", "text": "line 2"}
    player.close()


@pytest.mark.asyncio
async def test_one_listen_at_a_time_and_it_ends_after_listen_seconds():
    player, _, _, _, _ = make("Marta")
    player.config = Config(listen_seconds=0.05)
    assert player.listen() is None
    assert player.listening()
    assert player.listen() == ALREADY_LISTENING
    await wait_for(lambda: any(e.kind == "listen" and e.data["ended"] for e in player.feed.replay(PID)))
    assert not player.listening()
    assert player.listen() is None
    player.close()


@pytest.mark.asyncio
async def test_walking_away_stops_listening():
    player, _, _, _, _ = make("Marta")
    player.listen()
    player.walk("gym")
    *_, ended, moved = player.feed.replay(PID)
    assert (ended.kind, ended.data["ended"], ended.data["place"]) == ("listen", True, "cafe")
    assert (moved.kind, moved.data["place"]) == ("place", "gym")
    assert not player.listening()
    player.close()


@pytest.mark.asyncio
async def test_a_listen_ending_after_game_over_sends_nothing():
    player, _, _, _, _ = make("Marta")
    player.config = Config(listen_seconds=0.05)
    player.listen()
    player.end(Summary("lost", []))
    assert player.listen() == GAME_OVER
    await asyncio.sleep(0.1)
    assert not any(e.kind == "listen" and e.data["ended"] for e in player.feed.recent)


@pytest.mark.asyncio
async def test_listen_makes_no_model_calls_and_raises_no_suspicion():
    player, _, _, engine, _ = make("Marta")
    client = StubClient()
    player.writer = Writer(client, "haiku-test")
    engine.facts.record(square_line("u-1", "the well is dry"))
    assert player.listen() is None
    assert client.messages.calls == []
    assert engine.suspicion.level(PID) == 0
    player.close()


def asking(*names):
    """A player at the tavern with the villagers, where make_player puts them."""
    player, town, lines, engine, lineage = make(*names)
    player.place = "bar"
    return player, town, lines, engine, lineage


def asked_user_text(client):
    return client.messages.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_ask_answers_from_what_the_villager_heard():
    player, _, _, engine, _ = asking("Marta")
    engine.facts.record(Utterance("u-3", "v2", "Tom", "gym", "the mill is haunted", None, action=SPEAK))
    engine.heard = [Match("utt:u-3", {"id": "u-3"}, 0.9)]
    client = StubClient("Tom told me so.")
    player.writer = Writer(client, "haiku-test")
    assert await player.ask("v1", "the mill") is None
    assert engine.recalls == [("v1", "the mill")]
    assert "Tom at the gym: the mill is haunted" in asked_user_text(client)
    [event] = [e for e in player.feed.recent if e.kind == "asked"]
    assert (event.player, event.data["line"]) == (PID, "Tom told me so.")


@pytest.mark.asyncio
async def test_ask_about_a_neighbour_tells_the_writer_who_they_are():
    player, _, _, engine, _ = asking("Marta")
    engine.heard = []
    player.town.add(Villager("v9", "Everard Coke", "tanner", "dour", "", [], {}), "gym")
    player.town.add(Villager("v8", "Ida Coke", "baker", "warm", "", [], {}), "gym")
    player.town.remove("v8")
    player.town.get("v1").relationships["v9"] = "rival"
    client = StubClient("Everard? The tanner. Nothing new of him.")
    player.writer = Writer(client, "haiku-test")
    assert await player.ask("v1", "what of Everard Coke and Ida?") is None
    user = asked_user_text(client)
    assert "Everard Coke, the tanner (your rival)" in user
    assert "Ida Coke, the baker, who has left the village" in user


@pytest.mark.asyncio
async def test_ask_falls_back_to_a_plain_line_when_the_writer_says_nothing():
    player, _, _, engine, _ = asking("Marta")
    engine.heard = []
    player.writer = SimpleNamespace(answer=lambda *args: _blank())
    assert await player.ask("v1", "the mill") is None
    [event] = [e for e in player.feed.recent if e.kind == "asked"]
    assert event.data["line"] == "Marta hasn't heard anything about that."


async def _blank():
    return ""


@pytest.mark.asyncio
async def test_ask_needs_the_villager_at_your_place():
    player, _, _, engine, _ = asking("Marta")
    player.place = "cafe"
    assert await player.ask("v1", "the mill") == "Marta is at the bar. Walk there to ask them."
    assert engine.recalls == []
    assert engine.suspicion.score("v1", PID) == 0


@pytest.mark.asyncio
async def test_ask_checks_the_game_the_villager_and_the_topic():
    player, town, _, engine, _ = asking("Marta")
    assert await player.ask("v1", "  ") == "Ask about what? Try: the gym"
    too_long = await player.ask("v1", "x" * (MAX_ASK_CHARS + 1))
    assert too_long == f"Too long: a question is at most {MAX_ASK_CHARS} characters."
    assert await player.ask("v9", "the mill") == "No one in town has that id."
    town.remove("v1")
    assert await player.ask("v1", "the mill") == "Marta has left town."
    player.end(Summary("lost", []))
    assert await player.ask("v1", "the mill") == GAME_OVER
    assert engine.recalls == []


@pytest.mark.asyncio
async def test_asking_raises_half_a_whisper_bump_and_charges_the_asker():
    player, _, _, engine, _ = asking("Marta")
    usage = Usage(Config())
    player.writer = Writer(StubClient("Not a word."), "haiku-test", usage)
    await player.ask("v1", "the mill")
    assert engine.suspicion.score("v1", PID) == pytest.approx(player.config.suspicion_whisper_bump / 2)
    assert [e.reason for e in engine.suspicion.top_evidence(PID)] == ["asked questions"]
    assert usage.cost(PID) > 0


@pytest.mark.asyncio
async def test_a_villager_who_heard_nothing_says_so():
    player, _, _, _, _ = asking("Marta")
    client = StubClient("Not a word.")
    player.writer = Writer(client, "haiku-test")
    await player.ask("v1", "the mill")
    assert "nothing about it" in asked_user_text(client)
    player.writer = None
    await player.ask("v1", "the mill")
    assert player.feed.recent[-1].data["line"] == "Marta hasn't heard anything about that."


@pytest.mark.asyncio
async def test_a_wary_villager_turns_the_question_away():
    player, _, _, engine, _ = asking("Marta")
    engine.suspicion.bump("v1", PID, 0.9, "whispered to them directly")
    assert await player.ask("v1", "the mill") == Refusal("Marta turns away from you.")
    assert isinstance(await player.ask("v1", "the mill"), Refusal)
    assert [e.player for e in player.feed.recent if e.kind == "refusal"] == [PID, PID]
    assert engine.recalls == []
    assert engine.suspicion.score("v1", PID) == pytest.approx(0.9)


def test_past_max_idle_runs_the_oldest_never_played_runs_go_whatever_their_age(clock):
    first = make("Ann")[0]
    first.config = replace(first.config, max_idle_runs=2)
    players = Players()
    runs = []
    for pid in ("p-1", "p-2", "p-played", "p-3"):
        clock[0] += 1
        runs.append(run_of(first, pid))
        players.add(runs[-1])
    runs[2].touch()
    assert players.prune() == [runs[0]]
    assert [p.id for p in players] == ["p-2", "p-played", "p-3"]


def durable(p):
    return (p.id, p.owner, p.place, p.state, p.ended_at, p.created_at, p.summary, p.over())


def test_players_round_trip_as_json_with_no_sockets():
    player, town, _, engine, lineage = make("Bert")
    player.place = "bar"
    player.connected()
    ended = Player(engine, town, lineage, Ids(), player.feed, player.config, player_id="p-2", owner="o-1")
    ended.end(Summary("lost", ["ran out"]))
    players = Players()
    players.add(player)
    players.add(ended)
    assert players.any_playing()

    def wire(pid, owner):
        return Player(engine, town, lineage, Ids(), player.feed, player.config, player_id=pid, owner=owner)

    fresh = Players()
    fresh.restore(json.loads(json.dumps(players.to_state())), wire)
    assert [durable(p) for p in fresh] == [durable(p) for p in players]
    assert fresh.get("p-2").finished.is_set() and fresh.get("p-2").summary.reasons == ["ran out"]
    assert fresh.live("o-1") is fresh.get("p-2") and fresh.live(PID) is fresh.get(PID)
    assert fresh.get(PID).ever_active() and not fresh.get(PID).listening()
    assert not fresh.any_playing()
    fresh.get(PID).connected()
    assert fresh.any_playing()


@pytest.mark.asyncio
async def test_a_first_visit_and_the_end_are_logged_for_counting(capsys):
    player, *_ = make("Marta")
    player.connected()
    player.disconnected()
    player.connected()
    player.end(Summary("lost", []))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("analytics")]
    tag = f"owner={player.owner} run={player.id}"
    assert lines == [f"analytics visit {tag}", f"analytics end {tag} outcome=lost"]
    player.close()
