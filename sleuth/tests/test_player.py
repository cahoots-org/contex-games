import asyncio
import json
from types import SimpleNamespace

import pytest

import time
from dataclasses import replace

from sleuth.contex_client import Match
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.actions import SPEAK
from sleuth.player import ALREADY_LISTENING, GUIDED_WRONG, MAX_QUESTION, MESSAGES_PER_PART, Player, Refusal, conveys
from sleuth.players import Players
from sleuth.config import Config
from sleuth.case import Record
from sleuth.cases import CaseFile
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Lineage
from sleuth.tests.helpers import PID, FakeEngine, StubClient, StubJev, StubRoutine, StubWriter, wait_for
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
async def test_listen_leaves_out_talk_rooted_in_testimony():
    player, _, _, engine, _ = make("Marta")
    engine.facts.record(square_line("u-1", "grey hoodie at ten to one"))
    engine.facts.record(square_line("u-2", "someone took a bike"))
    engine.testimony_ids.add("u-1")
    assert player.listen() is None
    event = next(e for e in player.feed.replay(PID) if e.kind == "listen")
    assert [line["text"] for line in event.data["lines"]] == ["someone took a bike"]
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


MEMORY = "Around 11:40pm, on Elm Street, someone tall in a grey hoodie walked off with something."
SEEN = "I saw someone tall in a grey hoodie take it."


def interviewing():
    """A podcaster on Elm Street, where everyone is, with the shared case open: Fay (v3) stole Dana's (v1) bike."""
    cases, _, town = make_cases()
    file = culprit_file(cases)
    engine = FakeEngine()
    engine.cases, engine.routine, engine.jev = cases, cases.routine, StubJev({"kind": "none"})
    lineage, writer = Lineage(), StubWriter()
    feed = Feed(lineage, town, out=None)
    player = Player(engine, town, lineage, cases.ids, feed, Config(), writer, player_id=PID)
    player.place = "elm street"
    return player, file, engine, writer


async def ask(player, vid, kind, question="?", **answers):
    """Ask vid a question that Jev routes to kind, with answers for who, when and household words."""
    player.engine.jev.answers = {"kind": kind, "when": "night", **answers}
    return await player.interview(vid, question)


def memory_of(file, ids, holder="v2", utterance="u-1"):
    m = Record(ids.next("r"), file.crime.id, "memory", "elm street", "11:40pm", MEMORY, holder,
               {"height": "tall", "coat": "grey hoodie"}, utterance=utterance)
    file.records[m.id] = m
    return m


def notebook(player, kind="statement"):
    return [r for r in player.notebook.values() if r.kind == kind]


def replies(player):
    return [e.data["line"] for e in player.feed.recent if e.kind == "interview"]


@pytest.mark.asyncio
async def test_jev_routes_with_the_question_and_recent_thread_once_per_message():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = SEEN
    assert await ask(player, "v2", "what_did_you_see", "Hi, what did you see?") is None
    assert await ask(player, "v2", "what_did_you_see", "Anything else?") is None
    assert engine.jev.calls == 2 and len(writer.calls) == 2
    assert engine.jev.state["podcaster_asks"] == "Anything else?"
    assert engine.jev.state["conversation"] == [{"podcaster": "Hi, what did you see?", "resident": SEEN}]
    assert {"kind", "who", "when"} <= set(engine.jev.questions) and "none" in engine.jev.questions["kind"].criteria
    assert writer.calls[1][2:4] == ("Anything else?", [{"podcaster": "Hi, what did you see?", "resident": SEEN}])
    assert [t["question"] for t in player.thread_json("v2")] == ["Hi, what did you see?", "Anything else?"]


@pytest.mark.asyncio
async def test_what_did_you_see_gives_a_witness_their_memory_record():
    player, file, engine, writer = interviewing()
    memory = memory_of(file, player.ids)
    writer.line = SEEN
    assert await ask(player, "v2", "what_did_you_see") is None
    assert player.notebook[memory.id] == memory and player.notebook[memory.id] is not memory
    assert writer.calls[0][4] == [MEMORY]
    [event] = [e for e in player.feed.recent if e.kind == "interview"]
    assert (event.player, event.data["villager_id"], event.data["question"], event.data["line"]) == (PID, "v2", "?", SEEN)
    assert [r["id"] for r in event.data["records"]] == [memory.id]
    assert all("sound" not in r for r in event.data["records"])
    await ask(player, "v2", "what_did_you_see")
    assert len(player.notebook) == 1 and player.feed.recent[-1].data["records"] == []
    assert [t["records"] for t in player.thread_json("v2")] == [event.data["records"], []]


@pytest.mark.asyncio
async def test_a_trusting_witness_recalls_one_more_of_the_culprit_s_traits():
    player, file, engine, _ = interviewing()
    memory = memory_of(file, player.ids)
    engine.reputation.nudge("v2", PID, player.config.trusted_at)
    await ask(player, "v2", "what_did_you_see")
    [fuller] = notebook(player, "memory")
    assert fuller.id not in (memory.id, "") and fuller.sound and fuller.holder == "v2"
    hair = player.town.get("v3").traits["hair"]
    assert fuller.traits == {"height": "tall", "hair": hair, "coat": "grey hoodie"}


@pytest.mark.asyncio
async def test_where_were_you_at_the_crime_records_the_claim_with_soundness():
    player, file, *_ = interviewing()
    player.game = Game()
    player.game.day = 3
    file.whereabouts = {"v2": ["elm street", "bar"]}
    file.alibi = ["gym"]
    await ask(player, "v2", "where_were_you")
    await ask(player, "v3", "where_were_you")
    claims = {r.holder: r for r in notebook(player)}
    assert claims["v2"].text == "Eli Reyes says they were on Elm Street then at the bar last night."
    assert claims["v3"].text == "Fay Okafor says they were at the gym last night."
    assert (claims["v2"].sound, claims["v3"].sound) == (True, False) and {r.day for r in claims.values()} == {3}


@pytest.mark.asyncio
async def test_where_were_you_at_another_part_of_the_day_is_where_they_usually_are():
    player, file, engine, _ = interviewing()
    engine.routine = StubRoutine({"v2": {"morning": "library"}})
    await ask(player, "v2", "where_were_you", when="morning")
    [said] = notebook(player)
    assert (said.text, said.sound) == ("Eli Reyes says they're usually at the library in the morning.", True)


@pytest.mark.asyncio
async def test_where_was_a_housemate_is_their_household_word_from_the_same_jev_call():
    player, file, engine, _ = interviewing()
    await ask(player, "v4", "where_was", who="v3", **{"word:v3": "cover"})
    assert engine.jev.calls == 1 and "word:v3" in engine.jev.questions
    [word] = notebook(player)
    assert (word.text, word.sound, word.who) == ("Gus Okafor: Fay Okafor was home with me all night.", False, "v3")
    await ask(player, "v4", "where_was", who="v3")
    assert "word:v3" not in engine.jev.questions and len(notebook(player)) == 1


@pytest.mark.asyncio
async def test_where_was_someone_else_is_where_the_log_put_them_together_never_the_crime_place():
    player, file, *_ = interviewing()
    file.whereabouts = {"v2": ["elm street", "bar"], "v5": ["elm street", "bar"], "v6": ["elm street"]}
    await ask(player, "v2", "where_was", who="v5")
    [seen] = notebook(player)
    assert (seen.text, seen.sound) == ("Eli Reyes says they saw Hal Burke at the bar last night.", True)
    await ask(player, "v2", "where_was", who="v6")
    assert len(notebook(player)) == 1 and replies(player)[-1] == "I wouldn't know about that."


@pytest.mark.asyncio
async def test_who_had_reason_names_ties_who_feud_with_the_victim():
    player, file, *_ = interviewing()
    player.place = "oak street"
    await ask(player, "v6", "who_had_reason")
    [said] = notebook(player)
    assert (said.text, said.who) == ("Ivy Burke says Hal Burke has never got on with Dana Reyes.", "v5")
    await ask(player, "v5", "who_had_reason")
    assert replies(player)[-1] == "I wouldn't know about that."


@pytest.mark.asyncio
async def test_what_do_you_think_of_someone_is_phrased_from_the_tie_but_not_recorded():
    player, file, engine, writer = interviewing()
    player.place = "oak street"
    await ask(player, "v5", "what_do_you_think_of", who="v1")
    assert player.notebook == {}
    assert writer.calls[0][4] == ["Dana Reyes is Hal Burke's rival, and they are on hostile terms."]
    await ask(player, "v5", "what_do_you_think_of", who="v8")
    assert replies(player)[-1] == "I wouldn't know about that." and len(writer.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["none", "what_did_you_see", "nonsense"])
async def test_none_or_nothing_known_is_an_honest_i_wouldnt_know_without_the_writer(kind):
    player, file, engine, writer = interviewing()
    assert await ask(player, "v2", kind) is None
    assert replies(player) == ["I wouldn't know about that."] and writer.calls == [] and player.notebook == {}
    assert player.thread_json("v2") == [{"question": "?", "line": "I wouldn't know about that.", "records": []}]


@pytest.mark.asyncio
async def test_a_failed_route_is_an_honest_i_wouldnt_know():
    player, file, engine, writer = interviewing()

    async def down(**_):
        raise RuntimeError("jev down")

    engine.jev = SimpleNamespace(system_one=down)
    assert await player.interview("v2", "Hello?") is None
    assert replies(player) == ["I wouldn't know about that."]


@pytest.mark.asyncio
async def test_a_few_messages_per_resident_per_part_of_the_day_then_lets_talk_later():
    player, file, engine, writer = interviewing()
    player.game = Game()
    for _ in range(MESSAGES_PER_PART):
        assert await ask(player, "v2", "none") is None
    refused = await ask(player, "v2", "none")
    assert isinstance(refused, Refusal) and refused == "Eli Reyes: Let's talk later."
    assert engine.jev.calls == MESSAGES_PER_PART
    assert await ask(player, "v1", "none") is None
    player.game.tick()
    assert await ask(player, "v2", "none") is None


@pytest.mark.asyncio
async def test_a_question_must_be_typed_and_short():
    player, *_ = interviewing()
    assert await player.interview("v2", "   ") == "Type a question."
    assert await player.interview("v2", "x" * (MAX_QUESTION + 1)) == f"Keep your question under {MAX_QUESTION} characters."
    assert player.threads == {}


@pytest.mark.asyncio
async def test_threads_and_notebook_round_trip_with_the_run():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = SEEN
    await ask(player, "v2", "what_did_you_see", "What did you see?")
    fresh = Player(engine, player.town, player.lineage, Ids(), player.feed, player.config, writer, player_id=PID)
    fresh.restore(json.loads(json.dumps(player.to_state())))
    assert fresh.thread_json("v2") == player.thread_json("v2") and fresh.thread_json("v2")[0]["records"]


@pytest.mark.asyncio
async def test_a_new_case_records_the_same_words_again():
    player, file, engine, writer = interviewing()
    file.whereabouts = {"v2": ["elm street"]}
    await ask(player, "v2", "where_were_you")
    file.state = "closed"
    second = CaseFile(replace(file.crime, id="case-2"), {}, "open", whereabouts={"v2": ["elm street"]})
    engine.cases.files["case-2"] = second
    await ask(player, "v2", "where_were_you")
    assert {r.case for r in notebook(player)} == {"case-1", "case-2"} and len(notebook(player)) == 2


def hearsay(player, engine, root_kind, file):
    """Ivy (v6), on Oak Street with the podcaster, heard Kit retell a line rooted in root_kind."""
    player.place = "oak street"
    memory = memory_of(file, player.ids, holder="v7", utterance="u-1")
    file.roots["u-1"] = root_kind
    player.lineage.record("u-5", "u-1")
    engine.facts.record(Utterance("u-5", "v8", "Kit Tran", "oak street", "someone tall took a bike", "u-1"))
    engine.heard = [Match("utt:u-5", {"id": "u-5"}, 0.9)]
    return memory


@pytest.mark.asyncio
async def test_who_told_you_traced_to_a_memory_is_sound_and_names_the_teller():
    player, file, engine, _ = interviewing()
    memory = hearsay(player, engine, "memory", file)
    await ask(player, "v6", "who_told_you")
    [said] = notebook(player)
    assert said.text == "Ivy Burke heard from Kit Tran: someone tall took a bike"
    assert (said.sound, said.utterance, said.holder) == (True, memory.id, "v6")
    assert engine.recalls == [("v6", file.crime.text)]


@pytest.mark.asyncio
async def test_who_told_you_from_a_cover_story_is_unsound():
    player, file, engine, _ = interviewing()
    hearsay(player, engine, "cover", file)
    await ask(player, "v6", "who_told_you")
    [said] = notebook(player)
    assert said.sound is False


@pytest.mark.asyncio
async def test_news_hearsay_is_phrased_but_not_recorded():
    player, file, engine, writer = interviewing()
    hearsay(player, engine, "news", file)
    await ask(player, "v6", "who_told_you")
    assert notebook(player) == [] and writer.calls[0][4] == ["Kit Tran: someone tall took a bike"]


@pytest.mark.asyncio
async def test_the_writer_never_gets_the_culprits_name_from_a_witness():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    file.whereabouts = {"v2": ["elm street"]}
    await ask(player, "v2", "what_did_you_see")
    await ask(player, "v2", "where_were_you")
    assert "Fay" not in json.dumps(writer.calls) and "Okafor" not in json.dumps(writer.calls)


@pytest.mark.asyncio
async def test_guarded_resident_turns_the_podcaster_away():
    player, file, engine, writer = interviewing()
    engine.reputation.nudge("v2", PID, player.config.guarded_at - 0.1)
    refused = await ask(player, "v2", "what_did_you_see")
    assert isinstance(refused, Refusal) and "Eli Reyes" in refused
    assert writer.calls == [] and engine.pressed == [] and player.notebook == {} and engine.jev.calls == 0


@pytest.mark.asyncio
async def test_interview_requires_an_open_case_and_the_same_place():
    player, file, engine, writer = interviewing()
    player.place = "gym"
    assert await ask(player, "v2", "none") == "Eli Reyes is on Elm Street. Walk there to talk to them."
    assert await ask(player, "v99", "none") == "No one in town has that id."
    file.state = "closed"
    assert await ask(player, "v2", "none") == "There's no open case."
    assert writer.calls == [] and engine.jev.calls == 0


@pytest.mark.asyncio
async def test_interview_presses_the_culprit():
    player, file, engine, _ = interviewing()
    await ask(player, "v2", "none")
    assert engine.pressed == [file]


@pytest.mark.asyncio
async def test_a_reply_falls_back_to_the_records_text_when_phrasing_fails():
    player, file, _, _ = interviewing()
    memory_of(file, player.ids)

    async def down(*_):
        raise RuntimeError("haiku down")

    player.writer = SimpleNamespace(reply=down)
    await ask(player, "v2", "what_did_you_see")
    assert replies(player)[-1] == f"Eli Reyes says: {MEMORY}"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["I didn’t see anything, someone tall in a grey hoodie or not.",
                                   "I saw someone tall.", "It was Fay Okafor, someone tall in a grey hoodie."])
async def test_a_reply_that_denies_drops_or_names_beyond_its_records_falls_back(reply):
    player, file, _, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = reply
    await ask(player, "v2", "what_did_you_see", "Was it Fay?")
    assert replies(player)[-1] == f"Eli Reyes says: {MEMORY}"




@pytest.mark.asyncio
async def test_notebook_round_trips():
    player, file, *_ = interviewing()
    memory_of(file, player.ids)
    file.whereabouts = {"v2": ["elm street"]}
    await ask(player, "v2", "what_did_you_see")
    await ask(player, "v2", "where_were_you")
    fresh = run_of(player, PID)
    fresh.restore(json.loads(json.dumps(player.to_state())))
    assert fresh.notebook == player.notebook and len(fresh.notebook) == 2


def place_record(file, kind, place, rid):
    r = Record(rid, file.crime.id, kind, place, "11:42pm", f"{kind} at the {place}")
    file.records[r.id] = r
    return r


def test_pull_adds_the_clip_and_logs_at_the_place():
    player, file, *_ = interviewing()
    clip, log = place_record(file, "clip", "grocery", "r-11"), place_record(file, "log", "grocery", "r-12")
    memory_of(file, player.ids).place = "grocery"
    player.place = "gym"
    assert player.pull() == "There's no footage or log for the case here."
    player.place = "grocery"
    assert player.pull() is None
    assert set(player.notebook) == {clip.id, log.id} and player.notebook[clip.id] is not clip
    [event] = [e for e in player.feed.recent if e.kind == "pulled"]
    assert event.player == PID and [r["id"] for r in event.data["records"]] == [clip.id, log.id]
    assert all("sound" not in r for r in event.data["records"])
    assert player.pull() is None
    assert [e.data["records"] for e in player.feed.recent if e.kind == "pulled"][-1] == []
    file.state = "closed"
    assert player.pull() == "There's no open case."


def test_search_finds_the_clues_at_the_crime_place_once_per_case():
    player, file, *_ = interviewing()
    clue = place_record(file, "clue", "elm street", "r-11")
    place_record(file, "clip", "elm street", "r-12")
    player.place = "gym"
    assert player.search() == "There's nothing to search for here."
    player.place = "elm street"
    assert player.search() is None
    assert list(player.notebook) == [clue.id] and player.notebook[clue.id] is not clue
    [event] = [e for e in player.feed.recent if e.kind == "searched"]
    assert event.player == PID and event.data["text"] == "You searched Elm Street."
    assert [r["id"] for r in event.data["records"]] == [clue.id] and "sound" not in event.data["records"][0]
    assert player.search() == "You've already searched here."
    fresh = run_of(player, PID)
    fresh.restore(json.loads(json.dumps(player.to_state())))
    assert fresh.search() == "You've already searched here."
    file.state = "closed"
    assert player.search() == "There's no open case."


def test_pull_refused_when_no_one_who_lives_on_the_street_trusts_you():
    player, file, engine, _ = interviewing()
    place_record(file, "clip", "elm street", "r-11")
    engine.reputation.nudge_all(PID, player.config.guarded_at - 0.1, ["v1", "v2", "v3", "v4"])
    engine.reputation.nudge_all(PID, 0.5, ["v5", "v6", "v7", "v8"])
    assert player.pull() == "No one who keeps the records here will share them with you."
    assert player.notebook == {}
    engine.reputation.nudge("v2", PID, 0.5)
    assert player.pull() is None and "r-11" in player.notebook


def test_a_place_s_records_are_kept_by_those_who_work_there():
    player, file, engine, _ = interviewing()
    engine.routine = StubRoutine({"v5": {"morning": "grocery"}})
    place_record(file, "log", "grocery", "r-11")
    player.place = "grocery"
    engine.reputation.nudge_all(PID, player.config.guarded_at - 0.1, ["v1", "v2", "v3", "v4", "v6", "v7", "v8"])
    assert player.pull() is None
    player.notebook.clear()
    engine.reputation.nudge("v5", PID, player.config.guarded_at - 0.1)
    assert player.pull() == "No one who keeps the records here will share them with you."


def cite(player, file, *records):
    for r in records:
        player.notebook[r.id] = replace(r)
    return [r.id for r in records]


def regard(engine, vid):
    return engine.reputation.get(vid, PID)


@pytest.mark.asyncio
async def test_publish_right_closes_the_case_and_raises_reputation():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    assert await player.publish("v3", ids) is None
    assert (file.state, file.solved_by, file.published) == ("closed", PID, [PID])
    assert engine.cases.last_closed == engine.cases.now
    assert all(regard(engine, v.id) == pytest.approx(player.config.reputation_right) for v in player.town.villagers)
    [(u, listeners, _)] = engine.delivered
    assert (u.speaker, u.speaker_name, u.verb) == ("podcast", "A true-crime podcast", "reported")
    assert u.text == "Fay Okafor stole Dana Reyes's bike, and the evidence holds up."
    assert set(listeners) == {"v1", "v2", "v3", "v4"} and file.roots[u.id] == "episode"
    [episode] = [e for e in player.feed.recent if e.kind == "episode"]
    assert episode.player is None and episode.line == "A podcaster's episode names Fay Okafor, and it holds up. Case closed."
    assert (episode.data["by"], episode.data["verdict"]) == (PID, "It holds up. Case closed.")
    assert [e.data["case_id"] for e in player.feed.recent if e.kind == "case_closed"] == [file.crime.id]


@pytest.mark.asyncio
async def test_publish_wrong_spreads_the_accusation_and_lowers_reputation():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    player.place = "gym"
    assert await player.publish("v5", ids) is None
    assert file.state == "open" and file.solved_by is None and file.published == [PID]
    config = player.config
    assert regard(engine, "v1") == pytest.approx(config.reputation_wrong)
    assert regard(engine, "v5") == pytest.approx(config.reputation_wrong + config.reputation_accused)
    [(u, listeners, _)] = engine.delivered
    assert u.text == "Hal Burke stole Dana Reyes's bike." and set(listeners) == {"v5", "v6"}
    assert file.roots[u.id] == "episode"
    [episode] = [e for e in player.feed.recent if e.kind == "episode"]
    assert episode.player is None and episode.line == "A podcaster's episode names Hal Burke."
    assert (episode.data["by"], episode.data["cited"]) == (PID, len(ids))
    assert episode.data["verdict"] == "Your episode didn't hold up. The town now believes it, and people are warier of you."
    assert not [e for e in player.feed.recent if e.kind == "system"]


@pytest.mark.asyncio
async def test_one_episode_per_player_per_case():
    player, file, *_ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    await player.publish("v5", ids)
    assert await player.publish("v3", ids) == "You've already published on this case."
    assert file.state == "open"


@pytest.mark.asyncio
async def test_publish_rejects_ids_not_in_the_notebook():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    assert await player.publish("v3", ids + ["r-99"]) == "Cite only entries from your notebook."
    assert await player.publish("v3", []) == "Cite between 1 and 5 notebook entries."
    assert await player.publish("v3", ids * 6) == "Cite between 1 and 5 notebook entries."
    assert await player.publish("v99", ids) == "No one in town has that id."
    assert file.published == [] and engine.delivered == []


@pytest.mark.asyncio
async def test_publish_after_case_closed_is_refused():
    player, file, engine, _ = interviewing()
    rival = Player(engine, player.town, player.lineage, player.ids, player.feed, player.config, player_id="p-2")
    memory = memory_of(file, player.ids)
    assert await rival.publish("v3", cite(rival, file, memory)) is None
    assert await player.publish("v3", cite(player, file, memory)) == "That case is closed."
    assert all(regard(engine, v.id) == 0 for v in player.town.villagers) and file.published == ["p-2"]
    player.notebook = {}
    assert await player.publish("v3", ["r-1"]) == "There's no open case."


@pytest.mark.asyncio
async def test_publish_rejects_duplicate_and_other_case_citations_without_spending_the_episode():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    other = Record("r-50", "case-9", "clip", "grocery", "9:00am", "a clip from another case")
    player.notebook[other.id] = other
    assert await player.publish("v3", ids + [other.id]) == "Cite only evidence from this case."
    assert file.published == [] and engine.delivered == []
    assert await player.publish("v3", ids) is None and file.state == "closed"


@pytest.mark.asyncio
async def test_publish_citing_a_cover_story_statement_is_accepted_but_does_not_hold():
    player, file, engine, _ = interviewing()
    cover = Record("r-60", file.crime.id, "statement", "elm street", "9:00am", "Fay Okafor: I was home.", "v3",
                   sound=False)
    assert await player.publish("v3", cite(player, file, cover)) is None
    assert file.published == [PID] and file.state == "open"
    [episode] = [e for e in player.feed.recent if e.kind == "episode"]
    assert episode.data["held"] is False


@pytest.mark.parametrize("named", ["v3", "v5"])
@pytest.mark.asyncio
async def test_publishing_the_guided_case_onboards_the_owner_and_costs_no_regard(named):
    player, file, engine, _ = interviewing()
    file.crime.owner = PID
    ids = cite(player, file, memory_of(file, player.ids))
    assert await player.publish(named, ids) is None
    assert file.state == "closed" and engine.players.onboarded == {player.owner}
    assert engine.cases.last_closed == float("-inf")
    [closed] = [e for e in player.feed.recent if e.kind == "case_closed"]
    assert closed.player == PID
    assert all(regard(engine, v.id) == 0 for v in player.town.villagers)
    [episode] = [e for e in player.feed.recent if e.kind == "episode"]
    assert episode.data["verdict"] == ("It holds up. Case closed." if episode.data["held"] else GUIDED_WRONG)
    assert not [e for e in player.feed.recent if e.kind == "system"]


def guides(player):
    return [e.line for e in player.feed.recent if e.kind == "guide"]


def guided():
    """A new podcaster on Elm Street whose guided case is open: Fay (v3) stole Dana's (v1) bike there."""
    player, file, engine, writer = interviewing()
    file.crime.owner = PID
    player.game = Game()
    opened = []

    async def open_guided(*args):
        opened.append(args[1:])
        return file

    engine.cases.open_guided = open_guided
    engine.opened = opened
    return player, file, engine


@pytest.mark.asyncio
async def test_guide_walks_a_new_player_through_interview_pull_and_publish():
    player, file, engine = guided()
    memory = memory_of(file, player.ids)
    place_record(file, "clip", "elm street", "r-11")
    await player.start()
    await ask(player, "v2", "what_did_you_see")
    await ask(player, "v2", "what_did_you_see")
    assert player.pull() is None
    assert player.pull() is None
    assert await player.publish("v3", [memory.id]) is None
    assert guides(player) == [
        "This one's yours. Walk to Elm Street and ask Eli Reyes what they saw.",
        "Your notebook keeps what people tell you. Witnesses describe what they saw, never a name. Ask anyone where "
        "they were last night, or who'd have a reason. Pull records where a place has a camera or keeps logs, and "
        "search the crime scene once for anything left behind.",
        "When the evidence points to one person, publish an episode. Name them and cite what backs it up.",
        "The town's open case is yours to crack too. Other podcasters are on it, and the first episode that holds up "
        "wins.",
    ]
    assert all(e.player == PID for e in player.feed.recent if e.kind == "guide")


@pytest.mark.asyncio
async def test_guide_skips_steps_out_of_order():
    player, file, engine = guided()
    place_record(file, "clip", "elm street", "r-11")
    await player.start()
    assert player.pull() is None
    assert len(guides(player)) == 1 and player.guide_step == 1


@pytest.mark.asyncio
async def test_no_guide_without_a_guided_case():
    player, file, engine = guided()
    async def nothing(*args):
        return None

    engine.cases.open_guided = nothing
    await player.start()
    await ask(player, "v2", "none")
    assert guides(player) == [] and player.guide_step == 0


def test_guide_step_round_trips():
    player, *_ = make()
    player.guide_step = 2
    fresh, *_ = make()
    fresh.restore(json.loads(json.dumps(player.to_state())))
    assert fresh.guide_step == 2


@pytest.mark.asyncio
async def test_rival_hears_the_case_was_cracked_first():
    player, file, engine, _ = interviewing()
    rival, bystander = run_of(player, "p-2"), run_of(player, "p-3")
    for p in (player, rival, bystander):
        engine.players.add(p)
    memory = memory_of(file, player.ids)
    cite(rival, file, memory)
    assert await player.publish("v3", cite(player, file, memory)) is None
    told = [e for e in player.feed.recent if e.kind in ("system", "episode")]
    assert [(e.kind, e.player) for e in told] == [("system", "p-2"), ("episode", None)]
    assert told[0].line == "Another podcaster cracked the case first."


@pytest.mark.asyncio
async def test_onboarded_owner_gets_no_guided_case():
    player, file, engine = guided()
    engine.players.onboarded.add(player.owner)
    await player.start()
    assert engine.opened == [] and guides(player) == []


@pytest.mark.asyncio
async def test_no_guided_case_while_the_town_rests():
    player, file, engine = guided()
    engine.players.usage = SimpleNamespace(resting=lambda: True)
    await player.start()
    assert engine.opened == [] and guides(player) == []


@pytest.mark.asyncio
async def test_the_first_connect_opens_the_guided_case_in_the_background():
    player, file, engine = guided()
    player.connected()
    assert engine.opened == []
    await wait_for(lambda: player.guide_step == 1)
    player.disconnected()
    player.connected()
    await asyncio.sleep(0)
    assert engine.opened == [(PID, 1, "morning")]


@pytest.mark.asyncio
async def test_publish_refuses_a_repeated_citation_without_spending_the_episode():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    assert await player.publish("v3", ids * 2) == "Cite each entry once."
    assert file.published == [] and engine.delivered == []


@pytest.mark.asyncio
async def test_with_no_witness_at_the_scene_the_first_line_points_to_the_records():
    player, file, engine = guided()
    memory_of(file, player.ids, holder="v5")
    await player.start()
    assert guides(player) == [
        "This one's yours. Walk to Elm Street and pull the records there."]


def test_a_hedge_the_records_make_themselves_still_conveys_them():
    hedge = Record("r-1", "case-1", "statement", "elm street", "9:00am", "Eli Reyes: I can't say where Dana was.", "v2")
    assert conveys("I can't say where Dana was, honestly.", [hedge])
    assert not conveys("I can't say I saw anything.", [replace(hedge, text="Eli Reyes says they were at the bar.")])
    assert not conveys("No idea, I can't say where Dana was.", [hedge])


@pytest.mark.asyncio
async def test_interviewing_the_victim_gives_what_they_found():
    player, file, engine, writer = interviewing()
    found = Record(player.ids.next("r"), file.crime.id, "discovery", "elm street", "11:58pm",
                   "Around 11:58pm, Dana Reyes found the bike missing on Elm Street.", "v1")
    file.records[found.id] = found
    engine.reputation.nudge_all(PID, 1.0, ["v1"])
    assert await ask(player, "v1", "what_did_you_see") is None
    assert player.notebook[found.id] == found
    assert found.text in writer.calls[-1][4]


@pytest.mark.asyncio
async def test_a_search_brings_the_publish_hint():
    player, file, engine = guided()
    await player.start()
    await ask(player, "v2", "what_did_you_see")
    assert player.search() is None
    assert guides(player)[-1].startswith("When the evidence points to one person")
