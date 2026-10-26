import json
from types import SimpleNamespace

import pytest

import time
from dataclasses import replace

from sleuth.contex_client import Match
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.actions import SPEAK
from sleuth.player import ALREADY_LISTENING, Player, Refusal
from sleuth.players import Players
from sleuth.config import Config
from sleuth.alibi import claim
from sleuth.case import Record
from sleuth.feed import Feed
from sleuth.lineage import Lineage
from sleuth.tests.helpers import PID, FakeEngine, StubClient, StubJev, StubWriter, wait_for
from sleuth.tests.test_cases import culprit_file, make_cases
from sleuth.tests.helpers import make_player as make
from sleuth.town import NEWCOMER
from sleuth.writer import Writer


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


@pytest.mark.asyncio
async def test_walk_refuses_an_unknown_place_and_the_same_place():
    player, _, _, _, _ = make("Marta")
    assert "There's no moon here" in player.walk("moon")
    assert player.walk("cafe") == "You're already at the cafe."


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
async def test_listen_makes_no_model_calls():
    player, _, _, engine, _ = make("Marta")
    client = StubClient()
    player.writer = Writer(client, "haiku-test")
    engine.facts.record(square_line("u-1", "the well is dry"))
    assert player.listen() is None
    assert client.messages.calls == []
    player.close()


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
    return (p.id, p.owner, p.place, p.created_at)


def test_players_round_trip_as_json_with_no_sockets():
    player, town, _, engine, lineage = make("Bert")
    player.place = "bar"
    player.connected()
    other = Player(engine, town, lineage, Ids(), player.feed, player.config, player_id="p-2", owner="o-1")
    players = Players()
    players.add(player)
    players.add(other)
    assert players.any_playing()

    def wire(pid, owner):
        return Player(engine, town, lineage, Ids(), player.feed, player.config, player_id=pid, owner=owner)

    fresh = Players()
    fresh.restore(json.loads(json.dumps(players.to_state())), wire)
    assert [durable(p) for p in fresh] == [durable(p) for p in players]
    assert fresh.live("o-1") is fresh.get("p-2") and fresh.live(PID) is fresh.get(PID)
    assert fresh.get(PID).ever_active() and not fresh.get(PID).listening()
    assert not fresh.any_playing()
    fresh.get(PID).connected()
    assert fresh.any_playing()


@pytest.mark.asyncio
async def test_a_first_visit_is_logged_for_counting(capsys):
    player, *_ = make("Marta")
    player.connected()
    player.disconnected()
    player.connected()
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("analytics")]
    assert lines == [f"analytics visit owner={player.owner} run={player.id}"]
    player.close()


MEMORY = "Around 11:40pm, on elm street, someone tall in a grey hoodie walked off with something."


def interviewing(answer="honest"):
    """A podcaster on elm street, where everyone is, with the shared case open: Fay (v3) stole Dana's (v1) bike."""
    cases, _, town = make_cases()
    file = culprit_file(cases)
    engine = FakeEngine()
    engine.cases, engine.routine, engine.jev = cases, cases.routine, StubJev({"answer": answer})
    lineage, writer = Lineage(), StubWriter()
    feed = Feed(lineage, town, out=None)
    player = Player(engine, town, lineage, cases.ids, feed, Config(), writer, player_id=PID)
    player.place = "elm street"
    return player, file, engine, writer


def memory_of(file, ids, holder="v2", utterance="u-1"):
    m = Record(ids.next("r"), file.crime.id, "memory", "elm street", "11:40pm", MEMORY, holder,
               {"height": "tall", "coat": "grey hoodie"}, utterance=utterance)
    file.records[m.id] = m
    return m


def notebook(player, kind="statement"):
    return [r for r in player.notebook.values() if r.kind == kind]


@pytest.mark.asyncio
async def test_interview_gives_a_witness_their_memory_record():
    player, file, engine, writer = interviewing()
    memory = memory_of(file, player.ids)
    assert await player.interview("v2") is None
    assert player.notebook[memory.id] is memory
    [(vid, topic, heard, _)] = writer.calls
    assert (vid, topic) == ("v2", file.crime.text) and MEMORY in heard
    [event] = [e for e in player.feed.recent if e.kind == "interview"]
    assert (event.player, event.data["villager_id"], event.data["line"]) == (PID, "v2", writer.line)
    assert memory.id in [r["id"] for r in event.data["records"]]
    assert all("sound" not in r for r in event.data["records"])
    assert await player.interview("v2") is None
    assert writer.calls[-1][2] == [] and len(player.notebook) == 2


@pytest.mark.asyncio
async def test_interview_records_an_alibi_claim_with_soundness():
    player, file, *_ = interviewing()
    file.whereabouts = {"v2": ["elm street", "bar"]}
    file.alibi = ["gym"]
    await player.interview("v2")
    await player.interview("v3")
    claims = {r.holder: r for r in notebook(player) if " says they were " in r.text}
    assert claims["v2"].text == "Eli Reyes says they were on elm street then at the bar last night."
    assert claims["v3"].text == "Fay Okafor says they were at the gym last night."
    assert (claims["v2"].sound, claims["v3"].sound) == (True, False)
    assert claim(file, "v3", player.engine.routine)[1] is False


@pytest.mark.asyncio
async def test_interview_records_a_housemates_word_but_not_the_culprits():
    player, *_ = interviewing(answer="cover")
    await player.interview("v4")
    [word] = notebook(player)
    assert (word.text, word.sound) == ("Gus Okafor: Fay Okafor was home with me all night.", False)
    await player.interview("v3")
    assert not [r for r in notebook(player) if r.holder == "v3" and r.text.startswith("Fay Okafor: ")]


def hearsay(player, engine, root_kind, file):
    """Ivy (v6), on oak street with the podcaster, heard Kit retell a line rooted in root_kind."""
    player.place = "oak street"
    memory = memory_of(file, player.ids, holder="v7", utterance="u-1")
    file.roots["u-1"] = root_kind
    player.lineage.record("u-5", "u-1")
    engine.facts.record(Utterance("u-5", "v8", "Kit Tran", "oak street", "someone tall took a bike", "u-1"))
    engine.heard = [Match("utt:u-5", {"id": "u-5"}, 0.9)]
    return memory


@pytest.mark.asyncio
async def test_interview_hearsay_traced_to_a_memory_is_sound_and_names_the_teller():
    player, file, engine, _ = interviewing()
    memory = hearsay(player, engine, "memory", file)
    await player.interview("v6")
    [said] = [r for r in notebook(player) if " heard from " in r.text]
    assert said.text == "Ivy Burke heard from Kit Tran: someone tall took a bike"
    assert (said.sound, said.utterance, said.holder) == (True, memory.id, "v6")
    assert engine.recalls == [("v6", file.crime.text)]


@pytest.mark.asyncio
async def test_interview_hearsay_from_a_cover_story_is_unsound():
    player, file, engine, _ = interviewing()
    hearsay(player, engine, "cover", file)
    await player.interview("v6")
    [said] = [r for r in notebook(player) if " heard from " in r.text]
    assert said.sound is False


@pytest.mark.asyncio
async def test_news_hearsay_is_phrased_but_not_recorded():
    player, file, engine, writer = interviewing()
    hearsay(player, engine, "news", file)
    await player.interview("v6")
    assert not [r for r in notebook(player) if " heard from " in r.text]
    assert "Kit Tran: someone tall took a bike" in writer.calls[0][2]


@pytest.mark.asyncio
async def test_interview_never_hands_the_writer_the_culprits_name_from_a_witness():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    file.whereabouts = {"v2": ["elm street"]}
    await player.interview("v2")
    assert "Fay" not in json.dumps(writer.calls) and "Okafor" not in json.dumps(writer.calls)


@pytest.mark.asyncio
async def test_guarded_resident_turns_the_podcaster_away():
    player, file, engine, writer = interviewing()
    engine.reputation.nudge("v2", PID, player.config.guarded_at - 0.1)
    refused = await player.interview("v2")
    assert isinstance(refused, Refusal) and "Eli Reyes" in refused
    assert writer.calls == [] and engine.pressed == [] and player.notebook == {}


@pytest.mark.asyncio
async def test_interview_requires_an_open_case_and_the_same_place():
    player, file, engine, writer = interviewing()
    player.place = "gym"
    assert await player.interview("v2") == "Eli Reyes is at the elm street. Walk there to talk to them."
    assert await player.interview("v99") == "No one in town has that id."
    file.state = "closed"
    assert await player.interview("v2") == "There's no open case."
    assert writer.calls == [] and engine.recalls == []


@pytest.mark.asyncio
async def test_interview_presses_the_culprit():
    player, file, engine, _ = interviewing()
    await player.interview("v2")
    assert engine.pressed == [file]


@pytest.mark.asyncio
async def test_interview_falls_back_to_the_first_records_text_when_phrasing_fails():
    player, file, _, _ = interviewing()
    memory_of(file, player.ids)

    async def down(*_):
        raise RuntimeError("haiku down")

    player.writer = SimpleNamespace(answer=down)
    await player.interview("v2")
    assert player.feed.recent[-1].data["line"] == f"Eli Reyes says: {MEMORY}"
    await player.interview("v2")
    assert player.feed.recent[-1].data["line"] == "Eli Reyes doesn't know anything about it."


@pytest.mark.asyncio
async def test_notebook_round_trips():
    player, file, *_ = interviewing()
    memory_of(file, player.ids)
    file.whereabouts = {"v2": ["elm street"]}
    await player.interview("v2")
    fresh = run_of(player, PID)
    fresh.restore(json.loads(json.dumps(player.to_state())))
    assert fresh.notebook == player.notebook and len(fresh.notebook) == 3
