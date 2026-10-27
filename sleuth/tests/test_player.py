import json
from types import SimpleNamespace

import pytest

import time
from dataclasses import replace
from random import Random

from sleuth.contex_client import Match
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.player import KNOWN_KEPT, PRACTICE_WRONG, HELD, MAX_QUESTION, MESSAGES_PER_PART, SHRUGS, Player, Refusal, conveys, learned, looks_in, voiced
from sleuth.players import Players
from sleuth.config import Config
from sleuth.case import WHEN, Record
from sleuth.cases import CaseFile
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Lineage
from sleuth.photos import Album
from sleuth.tests.helpers import PID, FakeEngine, StubJev, StubRoutine, StubWriter
from sleuth.tests.test_cases import culprit_file, make_cases
from sleuth.tests.helpers import make_player as make


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
    assert fresh.get(PID).ever_active()
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


MEMORY = "Around 11:40pm, on Elm Street, someone tall in a grey hoodie walked off with something."
SEEN = "I saw someone tall in a grey hoodie take it."


def interviewing():
    """A podcaster on Elm Street, where everyone is, with the shared case open: Fay (v3), tall and in a grey hoodie
    that day, stole Dana's (v1) bike."""
    cases, _, town = make_cases()
    town.worn[1]["v3"] = "grey hoodie"
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
    assert claims["v2"].text == f"Eli Reyes says they were on Elm Street then at the bar {WHEN}."
    assert claims["v3"].text == f"Fay Okafor says they were at the gym {WHEN}."
    assert (claims["v2"].sound, claims["v3"].sound) == (True, False) and {r.day for r in claims.values()} == {3}


@pytest.mark.asyncio
async def test_an_interview_days_later_says_when_from_the_day_it_is():
    player, file, engine, writer = interviewing()
    file.crime = replace(file.crime, day=2, phase="afternoon", text=f"Someone stole Dana Reyes's bike {WHEN}.")
    file.whereabouts = {"v2": ["bar"]}
    player.game = Game()
    player.game.day, player.game.phase = 4, "morning"
    await ask(player, "v2", "where_were_you", when="afternoon")
    assert writer.calls[0][1] == "Someone stole Dana Reyes's bike two days ago, in the afternoon."
    assert writer.calls[0][4] == ["Eli Reyes says they were at the bar two days ago, in the afternoon."]
    assert writer.calls[0][6:] == ("day 4, morning", "two days ago, in the afternoon")
    assert "this afternoon" not in replies(player)[-1]
    player.game.day = 3
    [said] = player.thread_json("v2")[0]["records"]
    assert said["text"] == "Eli Reyes says they were at the bar yesterday afternoon."


@pytest.mark.asyncio
async def test_a_reply_that_says_the_crime_time_as_it_was_then_falls_back():
    player, file, engine, writer = interviewing()
    file.crime = replace(file.crime, day=2, phase="afternoon")
    file.whereabouts = {"v2": ["bar"]}
    player.game = Game()
    player.game.day = 4
    writer.line = "I was at the bar this afternoon."
    await ask(player, "v2", "where_were_you", when="afternoon")
    assert replies(player)[-1] == "I was at the bar two days ago, in the afternoon."


@pytest.mark.asyncio
async def test_hearsay_heard_days_ago_says_when_from_today():
    player, file, engine, writer = interviewing()
    file.crime = replace(file.crime, day=2, phase="afternoon")
    hearsay(player, engine, "memory", file)
    engine.facts.record(Utterance("u-5", "v8", "Kit Tran", "oak street", "Someone tall took a bike this afternoon.",
                                  "u-1"))
    player.game = Game()
    player.game.day = 3
    await ask(player, "v6", "who_told_you")
    [said] = notebook(player)
    assert said.text == f"Ivy Burke heard from Kit Tran: Someone tall took a bike {WHEN}."
    assert writer.calls[0][4] == ["Ivy Burke heard from Kit Tran: Someone tall took a bike yesterday afternoon."]


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
    player, file, _, writer = interviewing()
    file.whereabouts = {"v2": ["elm street", "bar"], "v5": ["elm street", "bar"], "v6": ["elm street"]}
    await ask(player, "v2", "where_was", who="v5")
    [seen] = notebook(player)
    assert (seen.text, seen.sound) == (f"Eli Reyes says they saw Hal Burke at the bar {WHEN}.", True)
    await ask(player, "v2", "where_was", who="v6")
    assert len(notebook(player)) == 1 and writer.calls[-1][4] == []


@pytest.mark.asyncio
async def test_who_had_reason_names_ties_who_feud_with_the_victim():
    player, file, *_ = interviewing()
    player.place = "oak street"
    await ask(player, "v6", "who_had_reason")
    [said] = notebook(player)
    assert (said.text, said.who) == ("Ivy Burke says Hal Burke has never got on with Dana Reyes.", "v5")
    await ask(player, "v5", "who_had_reason")
    assert len(notebook(player)) == 1


@pytest.mark.asyncio
async def test_the_victim_knows_who_is_cold_to_them_and_others_know_only_their_rivals():
    player, file, engine, _ = interviewing()
    town = player.town
    town.get("v7").grudge = "Dana never gave back my ladder."
    town.get("v1").relationships["v8"], town.get("v8").relationships["v1"] = "neighbor", "neighbor"
    town.get("v1").warmth["v8"] = town.get("v8").warmth["v1"] = -0.2
    await ask(player, "v1", "who_had_reason", "Do you have any idea who may have taken it?")
    assert [(r.who, r.sound) for r in notebook(player)] == [("v5", True), ("v7", True), ("v8", True)]
    assert "who may have taken it" in engine.jev.questions["kind"].criteria["who_had_reason"]
    player.notebook.clear()
    await ask(player, "v2", "who_had_reason")
    [said] = notebook(player)
    assert (said.text, said.who) == ("Eli Reyes says Hal Burke has never got on with Dana Reyes.", "v5")


@pytest.mark.asyncio
async def test_what_do_you_think_of_someone_is_phrased_from_the_tie_but_not_recorded():
    player, file, engine, writer = interviewing()
    player.place = "oak street"
    await ask(player, "v5", "what_do_you_think_of", who="v1")
    assert player.notebook == {}
    assert writer.calls[0][4] == ["Dana Reyes is my rival, and we are on hostile terms."]
    await ask(player, "v5", "what_do_you_think_of", who="v8")
    assert writer.calls[-1][4] == [] and len(writer.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["none", "what_did_you_see", "nonsense"])
async def test_none_or_nothing_known_is_still_a_reply_in_character_with_no_facts(kind):
    player, file, engine, writer = interviewing()
    writer.line = "Oh dear, I really couldn't tell you."
    assert await ask(player, "v2", kind) is None
    assert replies(player) == [writer.line] and player.notebook == {}
    assert len(writer.calls) == 1 and writer.calls[0][4] == [] and engine.jev.calls == 1
    assert player.thread_json("v2") == [{"question": "?", "line": writer.line, "records": []}]


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["Ask Hal, he'd know.", "Try the bar.", "Around 11pm, maybe.", "It was last night.",
                                  "Someone in a grey hoodie, I think.", "Someone tall, I think.", ""])
async def test_a_reply_with_no_facts_that_adds_a_name_place_time_or_look_falls_back_to_a_shrug(line):
    player, file, engine, writer = interviewing()
    writer.line = line
    await ask(player, "v2", "none")
    assert replies(player)[-1] in SHRUGS and player.notebook == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["I didn't see anything, and I wasn't there when it went missing.",
                                  "I was home all evening.", "I’m usually nowhere near there."])
async def test_a_reply_with_no_facts_says_nothing_of_where_the_resident_was(line):
    player, file, engine, writer = interviewing()
    writer.line = line
    await ask(player, "v2", "none")
    assert replies(player)[-1] in SHRUGS


@pytest.mark.asyncio
async def test_a_witness_tells_their_own_sighting_first_hand():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = "I wasn't there myself, but I was told someone tall in a grey hoodie walked off with it."
    await ask(player, "v2", "what_did_you_see")
    assert replies(player)[-1] == f"I saw it myself. {MEMORY}"
    writer.line = "I was there, and I saw someone tall in a grey hoodie walk off with it."
    await ask(player, "v2", "what_did_you_see")
    assert replies(player)[-1] == writer.line


@pytest.mark.asyncio
async def test_a_reply_says_where_the_resident_was_only_when_a_record_does():
    player, file, engine, writer = interviewing()
    player.place = "oak street"
    writer.line = "Hal Burke has never got on with Dana Reyes, and I was at home all night."
    await ask(player, "v6", "who_had_reason")
    assert replies(player)[-1] == "Hal Burke has never got on with Dana Reyes."
    file.whereabouts = {"v2": ["bar"]}
    writer.line = "I was at the bar last night."
    await ask(player, "v2", "where_were_you")
    assert replies(player)[-1] == writer.line


@pytest.mark.asyncio
async def test_a_reply_with_no_facts_may_echo_a_name_from_the_question_but_no_other():
    player, file, engine, writer = interviewing()
    writer.line = "I don't really know Hal."
    await ask(player, "v2", "none", "What do you think of Hal?")
    assert replies(player)[-1] == writer.line
    await ask(player, "v2", "none", "What do you think of Dana?")
    assert replies(player)[-1] in SHRUGS


@pytest.mark.asyncio
async def test_a_reply_with_facts_may_echo_a_name_from_the_question_but_no_other():
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = "I saw someone tall in a grey hoodie, not Hal."
    await ask(player, "v2", "what_did_you_see", "Was Hal involved?")
    assert replies(player)[-1] == writer.line
    await ask(player, "v3", "what_did_you_see", "Who was it?")
    assert replies(player)[-1] != writer.line


@pytest.mark.asyncio
async def test_a_failed_route_or_writer_is_still_a_shrug():
    player, file, engine, writer = interviewing()

    async def down(*_, **__):
        raise RuntimeError("down")

    engine.jev = SimpleNamespace(system_one=down)
    writer.reply = down
    assert await player.interview("v2", "Hello?") is None
    assert replies(player)[-1] in SHRUGS
    player.writer = None
    assert await player.interview("v2", "Hello?") is None
    assert replies(player)[-1] in SHRUGS and player.notebook == {}


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
    assert notebook(player) == [] and writer.calls[0][4] == ["Kit Tran told me: someone tall took a bike"]


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
async def test_interview_reaches_a_resident_from_anywhere():
    player, file, engine, writer = interviewing()
    player.place = "gym"
    assert await ask(player, "v2", "none") is None
    assert replies(player) == [writer.line]


@pytest.mark.asyncio
async def test_interview_requires_an_open_case():
    player, file, engine, writer = interviewing()
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
    assert replies(player)[-1] == f"I saw it myself. {MEMORY}"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["I didn’t see anything, someone tall in a grey hoodie or not.",
                                   "I saw someone tall.", "It was Fay Okafor, someone tall in a grey hoodie."])
async def test_a_reply_that_denies_drops_or_names_beyond_its_records_falls_back(reply):
    player, file, _, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = reply
    await ask(player, "v2", "what_did_you_see", "Who was it?")
    assert replies(player)[-1] == f"I saw it myself. {MEMORY}"




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


def practising():
    """A new podcaster in the practice town; the real town (from interviewing) has its shared case open."""
    player, shared, engine, writer = interviewing()
    player.game = Game()
    engine.players.add(player)
    player.begin_tutorial()
    return player, shared, engine, writer


def test_a_new_podcaster_starts_in_the_practice_town():
    player, shared, engine, _ = practising()
    assert player.practising and PID in player.feed.practising
    assert player.town is not engine.cases.town and "t1" in player.town and "v1" not in player.town
    assert player.engine.cases.private(PID).crime.owner == PID and player.game.phase == "afternoon"


@pytest.mark.asyncio
async def test_the_checklist_walks_the_practice_case_from_victim_to_witness_to_a_name():
    player, *_ = practising()
    steps = player.steps()
    assert [s["text"] for s in steps] == [
        "Ask Ruth Okafor, the victim, what happened", "Ask Tess Moreno what they saw",
        "Ask Ruth Okafor who they know that's tall and red-haired", "Talk to Cal Hughes",
        "Search the scene at the library", "Publish an episode naming who did it"]
    assert steps[1]["why"] == ("Tess Moreno is usually at the library in the morning, when it happened. "
                               "People nearby may have seen something.")
    assert steps[2]["why"] == "Tess Moreno saw looks, not a name. People can tell you who they know that matches."
    assert steps[3]["why"] == "Meet them yourself to see what they're wearing."
    assert steps[5]["why"] == ("Name who the evidence points to, and cite what backs it. Only cite what you can trust: "
                               "a lie in your evidence sinks the episode.")
    assert [(s.get("person"), s.get("about"), s.get("action")) for s in steps] == [
        ("t1", None, None), ("t3", None, None), ("t1", "t5", None), ("t5", None, None), (None, None, "search"),
        (None, None, "publish")]
    assert [s.get("beat") for s in steps] == [
        "Ruth Okafor told you what they found. Anything useful goes into your notebook.",
        "That's your first clue: what Tess Moreno saw. Now find who matches it.",
        "Ruth Okafor named Cal Hughes. Their row now shows how they look.",
        "Now you've seen what Cal Hughes is wearing today.",
        "The search turned up a clue. It's in your notebook now, with everything you've learned so far.", None]
    await ask(player, "t1", "what_happened", when="morning")
    assert done(steps_sent(player)[-1]) == [True, False, False, False, False, False] and notebook(player, "discovery")
    await ask(player, "t3", "what_did_you_see", when="morning")
    assert done(steps_sent(player)[-1]) == [True, True, False, False, False, False]
    await ask(player, "t1", "who_looks_like", "Do you know anyone tall with red hair?")
    assert done(steps_sent(player)[-1]) == [True, True, True, False, False, False]
    await ask(player, "t5", "what_did_you_see", when="morning")
    assert done(steps_sent(player)[-1]) == [True, True, True, True, False, False]
    assert player.search() == "There's nothing to search for here."
    player.walk("library")
    assert player.search() is None
    assert done(steps_sent(player)[-1]) == [True, True, True, True, True, False]
    assert all(e.player == PID for e in player.feed.recent)


@pytest.mark.asyncio
async def test_the_first_case_names_cal_only_once_he_is_described_and_met():
    player, *_ = practising()
    await ask(player, "t1", "what_do_they_look_like", who="t2")
    await ask(player, "t4", "none")
    assert not any(done(player.steps())[2:4])
    await ask(player, "t4", "what_do_they_look_like", who="t5")
    assert done(player.steps())[2:4] == [True, False]
    await ask(player, "t5", "none")
    assert done(player.steps())[2:4] == [True, True]


@pytest.mark.asyncio
async def test_the_whole_first_case_played_through_holds_naming_cal():
    player, shared, engine, _ = practising()
    seen = []
    player.feed.sinks.append(seen.append)
    await ask(player, "t1", "what_happened", "What happened?", when="morning")
    await ask(player, "t3", "what_did_you_see", "What did you see?", when="morning")
    await ask(player, "t1", "who_looks_like", "Do you know anyone tall with red hair?")
    await ask(player, "t5", "none", "Hi Cal, got a minute?")
    assert player.known["t5"][-1]["looks"]["coat"] == "green raincoat"
    player.walk("library")
    assert player.search() is None
    assert all(done(player.steps())[:5])
    cited = [r.id for r in player.notebook.values() if r.kind in ("memory", "clue", "statement")]
    assert len(cited) == 3
    assert await player.publish("t5", cited) is None
    assert [e.data["verdict"] for e in seen if e.kind == "episode"] == [HELD]
    assert player.handoff["head"] == "You got it. It was Cal Hughes." and not player.practising


@pytest.mark.asyncio
async def test_a_practice_question_costs_at_most_one_jev_and_one_writer_call_and_reaches_no_mind():
    player, _, engine, writer = practising()
    await ask(player, "t3", "what_did_you_see", when="morning")
    await ask(player, "t2", "none")
    assert engine.jev.calls == 2 and len(writer.calls) == 2
    assert engine.pressed == engine.delivered == engine.recalls == []


async def solve(player):
    """Ask the witness and search the scene; the ids of the sighting and the clue."""
    await ask(player, "t3", "what_did_you_see", when="morning")
    player.walk("library")
    player.search()
    return [r.id for r in player.notebook.values() if r.kind in ("memory", "clue")]


@pytest.mark.parametrize("named, held", [("t5", True), ("t4", False)])
@pytest.mark.asyncio
async def test_publishing_the_practice_case_moves_the_player_into_the_real_town(named, held):
    player, shared, engine, _ = practising()
    file = player.engine.cases.private(PID)
    ids = await solve(player)
    seen = []
    player.feed.sinks.append(seen.append)
    assert await player.publish(named, ids) is None
    assert (file.state, file.solved_by) == ("closed", PID if held else None)
    verdict = HELD if held else f"{PRACTICE_WRONG} It was Cal Hughes."
    assert [e.data["verdict"] for e in seen if e.kind == "episode"] == [verdict]
    closing = "Your episode held up." if held else "Your episode didn't hold up. It was Cal Hughes."
    assert [e.data["text"] for e in seen if e.kind == "case_closed"] == [closing]
    assert not player.practising and PID not in player.feed.practising
    assert (player.engine, player.town) == (engine, engine.cases.town)
    assert (player.notebook, player.threads, player.searched, player.place) == ({}, {}, [], "cafe")
    assert engine.players.onboarded == {player.owner}
    assert [(e.kind, e.player) for e in player.feed.recent] == [("case", PID), ("post", PID)]
    assert player.feed.recent[0].data["case"]["id"] == shared.crime.id
    assert all(regard(engine, v.id) == 0 for v in player.town.villagers) and engine.delivered == []


@pytest.mark.asyncio
async def test_skipping_the_tutorial_moves_the_player_into_the_real_town():
    player, shared, engine, _ = practising()
    file = player.engine.cases.private(PID)
    seen = []
    player.feed.sinks.append(seen.append)
    assert player.skip() is None
    assert (file.state, file.solved_by) == ("closed", None) and not player.practising
    assert [e.data["text"] for e in seen if e.kind == "case_closed"] == [""]
    assert engine.players.onboarded == {player.owner} and player.engine is engine
    assert player.skip() == "There's no case to skip."


@pytest.mark.asyncio
async def test_a_player_mid_tutorial_comes_back_after_a_restart():
    player, shared, engine, writer = practising()
    await solve(player)
    state = json.loads(json.dumps(player.to_state()))
    feed = Feed(Lineage(), engine.cases.town, out=None)
    back = Player(engine, engine.cases.town, Lineage(), player.ids, feed, player.config, writer, Game(), player_id=PID)
    back.restore(state)
    assert back.practising and PID in feed.practising
    assert back.engine.cases.private(PID) == player.engine.cases.private(PID)
    assert back.notebook == player.notebook and back.steps() == player.steps()
    assert await back.publish("t5", [r.id for r in back.notebook.values() if r.kind == "memory"]) is None
    assert back.engine is engine


def steps_sent(player):
    return [e.data["steps"] for e in player.feed.recent if e.kind == "steps"]


def done(steps):
    return [s["done"] for s in steps]


@pytest.mark.asyncio
async def test_no_checklist_off_the_practice_case():
    player, file, engine, _ = interviewing()
    memory_of(file, player.ids)
    await ask(player, "v2", "what_did_you_see")
    assert player.steps() is None and steps_sent(player) == []


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
async def test_publish_refuses_a_repeated_citation_without_spending_the_episode():
    player, file, engine, _ = interviewing()
    ids = cite(player, file, memory_of(file, player.ids))
    assert await player.publish("v3", ids * 2) == "Cite each entry once."
    assert file.published == [] and engine.delivered == []


@pytest.mark.parametrize("text, said", [
    ("Eli Reyes says they were at the bar last night.", "I was at the bar last night."),
    ("Eli Reyes says they're usually at the library in the morning.", "I'm usually at the library in the morning."),
    ("Eli Reyes says they saw Hal Burke at the bar last night.", "I saw Hal Burke at the bar last night."),
    ("Eli Reyes says Hal Burke has never got on with Eli Reyes.", "Hal Burke has never got on with me."),
    ("Eli Reyes: Fay Okafor was home with me all night.", "Fay Okafor was home with me all night."),
    ("Eli Reyes heard from Kit Tran: someone tall took a bike", "Kit Tran told me: someone tall took a bike"),
    ("Around 11:58pm, Eli Reyes found the bike missing on Elm Street.",
     "Around 11:58pm, I found my bike missing on Elm Street."),
    ("Kit Tran told me: someone tall took a bike", "Kit Tran told me: someone tall took a bike"),
])
def test_a_fallback_line_is_said_in_the_resident_s_own_voice(text, said):
    assert voiced(text, "Eli Reyes") == said


@pytest.mark.parametrize("line", ["Someone tall in a gray hoodie walked off with it.",
                                  "Someone TALL, in a grey-hoodie, walked off."])
def test_a_reply_conveys_a_look_in_a_close_spelling(line):
    memory = Record("r-1", "case-1", "memory", "elm street", "11:40pm", MEMORY, "v2",
                    {"height": "tall", "coat": "grey hoodie"})
    assert conveys(line, [memory])
    hair = replace(memory, traits={"hair": "dark-haired"})
    assert conveys("Someone with dark hair.", [hair]) and not conveys("Someone with red hair.", [hair])


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
async def test_what_happened_is_a_routed_kind_for_telling_the_case():
    player, file, engine, writer = interviewing()
    await ask(player, "v2", "none", "Tell me what happened to your thermos")
    criterion = engine.jev.questions["kind"].criteria["what_happened"]
    assert "tell me what happened to your" in criterion.lower()


@pytest.mark.asyncio
async def test_what_happened_gives_the_victim_their_discovery_and_a_witness_their_memory():
    player, file, engine, writer = interviewing()
    found = Record(player.ids.next("r"), file.crime.id, "discovery", "elm street", "11:58pm",
                   "Around 11:58pm, Dana Reyes found the bike missing on Elm Street.", "v1")
    file.records[found.id] = found
    memory = memory_of(file, player.ids)
    await ask(player, "v1", "what_happened", "Tell me what happened to your bike")
    await ask(player, "v2", "what_happened")
    assert player.notebook[found.id] == found and player.notebook[memory.id] == memory


@pytest.mark.asyncio
async def test_what_happened_gives_anyone_else_what_they_heard():
    player, file, engine, writer = interviewing()
    hearsay(player, engine, "memory", file)
    await ask(player, "v6", "what_happened")
    [said] = notebook(player)
    assert said.text == "Ivy Burke heard from Kit Tran: someone tall took a bike"
    hearsay(player, engine, "news", file)
    await ask(player, "v6", "what_happened")
    assert writer.calls[-1][4] == ["Kit Tran told me: someone tall took a bike"]


@pytest.mark.parametrize("named, head, line", [
    ("t5", "You got it. It was Cal Hughes.", "Your episode is out. By morning, half the town has heard it, and Ruth Okafor has the tote bag back."),
    ("t4", "Not quite. It was Cal Hughes, not Gus Moreno.",
     "By morning, half the town is talking about it, and Ruth Okafor is still missing the tote bag."),
])
@pytest.mark.asyncio
async def test_leaving_the_first_case_hands_off_with_its_outcome_until_dismissed(named, head, line):
    player, *_ = practising()
    assert player.handoff is None
    assert await player.publish(named, await solve(player)) is None
    assert player.handoff == {"head": head, "line": line}
    back = run_of(player, PID)
    back.restore(json.loads(json.dumps(player.to_state())))
    assert back.handoff == player.handoff
    player.dismiss_handoff()
    assert player.handoff is None


def test_skipping_the_first_case_hands_off_with_no_payoff():
    player, *_ = practising()
    player.skip()
    assert player.handoff == {"head": None, "line": None}


async def in_town_with_progress():
    """A podcaster in the town with a notebook entry, a conversation and a searched scene, and the town's events."""
    player, file, engine, writer = interviewing()
    player.game = Game()
    engine.players.add(player)
    memory = memory_of(file, player.ids)
    await ask(player, "v2", "what_did_you_see")
    player.notebook[memory.id] = memory
    player.searched.append(file.crime.id)
    player.feed.say("Only you heard this.", player=PID)
    return player, file, engine


@pytest.mark.parametrize("close", ["skip", "publish"])
@pytest.mark.asyncio
async def test_replaying_the_first_case_starts_it_fresh_and_gives_the_town_back_with_a_handoff(close):
    player, file, engine = await in_town_with_progress()
    before = json.loads(json.dumps(player.to_state()))
    events = [e.id for e in player.feed.replay(PID)]
    assert player.replay() is None and player.practising
    assert player.notebook == {} and player.threads == {} and player.place == "cafe"
    assert not any(done(player.steps())) and player.replay() == "That case is already open."
    if close == "skip":
        player.skip()
    else:
        await player.publish("t5", await solve(player))
    after = json.loads(json.dumps(player.to_state()))
    assert not player.practising and player.engine is engine
    assert player.handoff["head"] == (None if close == "skip" else "You got it. It was Cal Hughes.")
    assert player.handoff["back"] is True
    assert {k: after[k] for k in ("place", "notebook", "threads", "searched")} == \
        {k: before[k] for k in ("place", "notebook", "threads", "searched")}
    assert [e.id for e in player.feed.replay(PID)][:len(events)] == events and file.state == "open"


@pytest.mark.asyncio
async def test_a_replay_survives_a_restart_and_still_gives_the_town_back():
    player, file, engine = await in_town_with_progress()
    place, notebook = player.place, dict(player.notebook)
    player.replay()
    back = Player(engine, engine.cases.town, Lineage(), player.ids, player.feed, player.config, StubWriter(), Game(),
                  player_id=PID)
    back.restore(json.loads(json.dumps(player.to_state())))
    assert back.practising
    back.skip()
    assert (back.place, back.notebook) == (place, notebook)


@pytest.mark.asyncio
async def test_an_episode_is_judged_on_what_the_accused_wore_that_day():
    player, file, engine, _ = interviewing()
    player.town.worn = {1: {"v3": "green raincoat"}, 2: {"v3": "plaid flannel"}}
    clip = Record(player.ids.next("r"), file.crime.id, "clip", "elm street", "11:40pm", "", traits={"coat": "green raincoat"},
                  day=1)
    file.records[clip.id] = clip
    assert await player.publish("v3", cite(player, file, clip)) is None
    assert file.solved_by == PID


@pytest.mark.asyncio
async def test_talking_shows_how_they_look_today():
    player, file, engine, _ = interviewing()
    player.game = Game()
    for _ in range(4):
        player.game.tick()
    player.town.worn[2] = {"v1": "plaid flannel"}
    seen = []
    player.feed.sinks.append(seen.append)
    assert await ask(player, "v1", "none") is None
    traits = player.town.get("v1").traits
    assert player.known["v1"][-1] == {"looks": {"height": traits["height"], "hair": traits["hair"], "coat": "plaid flannel"},
                                      "how": "talked", "by": None, "day": 2, "phase": player.game.phase}
    [known] = [e for e in seen if e.kind == "known"]
    assert known.player == PID and known.data["villager"] == player.person("v1")
    assert player.person("v1")["how"] == "you talked, day 2"
    await ask(player, "v1", "none")
    assert len(player.known["v1"]) == 1


@pytest.mark.asyncio
async def test_a_refused_question_teaches_nothing():
    player, file, engine, _ = interviewing()
    player.game = Game()
    engine.reputation.nudge("v2", PID, player.config.guarded_at - 0.1)
    assert isinstance(await ask(player, "v2", "none"), Refusal)
    player._talked["v1"] = ((player.game.day, player.game.phase), MESSAGES_PER_PART)
    assert isinstance(await ask(player, "v1", "none"), Refusal)
    assert player.known == {}


def test_known_round_trips_and_resets_on_leaving_the_first_case():
    player, *_ = practising()
    player.learn("t1", {"height": "tall"}, "talked")
    back = Player(player.engine, player.town, Lineage(), player.ids, player.feed, player.config, None, Game(), player_id=PID)
    back.restore(json.loads(json.dumps(player.to_state())))
    assert back.known == player.known and back.known["t1"][0]["looks"] == {"height": "tall"}
    player.skip()
    assert player.known == {}


def test_known_keeps_the_newest_few_and_says_how_each_was_learned():
    player, *_ = interviewing()
    for day in range(1, KNOWN_KEPT + 3):
        player.learn("v1", {"height": "tall"}, "described", by="v2", day=day)
    assert [e["day"] for e in player.known["v1"]] == list(range(3, KNOWN_KEPT + 3))
    first = player.town.get("v2").name.split()[0]
    assert player.person("v1")["how"] == f"{first} described, day {KNOWN_KEPT + 2}"
    assert learned({"how": "photo", "by": None, "day": 2}, player.town) == "in a photo, day 2"
    assert player.person("v2") == {**player.person("v2"), "looks": "", "how": "", "face": None}


@pytest.mark.asyncio
async def test_a_resident_describes_someone_they_know():
    player, *_ = practising()
    await ask(player, "t1", "what_do_they_look_like", who="t5")
    [said] = notebook(player)
    assert said.text == "Ruth Okafor says Cal Hughes is tall, red-haired, with a red pickup."
    assert said.traits == {"height": "tall", "hair": "red-haired", "car": "red pickup"}
    assert (said.who, said.holder, said.sound) == ("t5", "t1", True)
    assert (player.known["t5"][-1]["how"], player.known["t5"][-1]["by"]) == ("described", "t1")
    assert player.person("t5")["how"] == "Ruth described, day 1"


@pytest.mark.asyncio
async def test_a_resident_names_who_they_know_that_matches_a_look():
    player, *_ = practising()
    question = "Who do you know that's tall with red hair?"
    await ask(player, "t1", "who_looks_like", question)
    assert "tall with red hair" in player.engine.jev.questions["kind"].criteria["who_looks_like"]
    [said] = notebook(player)
    assert said.text == "Ruth Okafor says Cal Hughes is tall, red-haired, with a red pickup."
    assert (said.who, said.traits["hair"]) == ("t5", "red-haired") and player.known["t5"][-1]["by"] == "t1"
    await ask(player, "t4", "who_looks_like", question)
    assert [(r.holder, r.who) for r in notebook(player)] == [("t1", "t5"), ("t4", "t5")]
    await ask(player, "t3", "who_looks_like", "Anyone you know drive a white sedan?")
    assert [r.who for r in notebook(player)][-1] == "t4"


@pytest.mark.parametrize("question", ["Do you know any redheads?", "Know a redhead?", "Anyone ginger?"])
def test_a_redhead_or_ginger_asks_for_red_hair(question):
    assert looks_in(question) == {"hair": {"red-haired"}}


@pytest.mark.asyncio
async def test_a_look_question_with_no_look_or_no_match_names_no_one():
    player, *_ = practising()
    await ask(player, "t1", "who_looks_like", "Who do you know that looks odd?")
    await ask(player, "t6", "who_looks_like", "Anyone you know that's bald?")
    assert notebook(player) == [] and set(player.known) == {"t1", "t6"}


@pytest.mark.asyncio
async def test_a_stranger_cannot_describe_them():
    player, *_ = practising()
    await ask(player, "t3", "what_do_they_look_like", who="t6")
    assert notebook(player) == [] and "t6" not in player.known


@pytest.mark.asyncio
async def test_a_housemate_with_no_tie_can_describe_them():
    player, *_ = interviewing()
    await ask(player, "v4", "what_do_they_look_like", who="v1")
    assert notebook(player) == [] and "v1" not in player.known
    await ask(player, "v4", "what_do_they_look_like", who="v3")
    [said] = notebook(player)
    assert said.who == "v3" and player.known["v3"][-1]["by"] == "v4"


@pytest.mark.asyncio
async def test_a_description_that_adds_a_look_falls_back_to_the_plain_line():
    player, _, _, writer = practising()
    writer.line = "Cal? Tall, red-haired, drives a red pickup, always in a green raincoat."
    await ask(player, "t1", "what_do_they_look_like", who="t5")
    assert replies(player)[-1] == "Cal Hughes is tall, red-haired, with a red pickup."
    writer.line = "Cal's tall, red-haired, and drives a red pickup."
    await ask(player, "t1", "what_do_they_look_like", who="t5")
    assert replies(player)[-1] == writer.line


@pytest.mark.asyncio
async def test_saving_a_photo_teaches_looks_and_adds_a_notebook_entry():
    player, file, engine, _ = interviewing()
    player.town.dress(2, Random(0))
    whereabouts = {v.id: ["bar"] for v in player.town.villagers}
    engine.album = Album(Random(1))
    photo = engine.album.take(player.town, 2, "evening", whereabouts, player.ids)
    assert player.save_photo(photo.id) is None
    for vid in photo.people:
        assert player.known[vid][-1] == {"looks": photo.people[vid], "how": "photo", "by": None, "day": photo.day,
                                         "phase": photo.phase}
        assert player.person(vid)["how"] == "in a photo, day 2"
    saved = player.notebook[photo.id]
    assert (saved.kind, saved.case, saved.text, saved.day) == ("photo", file.crime.id, photo.caption, 2)
    event = player.feed.recent[-1]
    assert (event.kind, event.player, event.data["photo_id"], event.data["case_id"]) == (
        "photo_saved", PID, photo.id, file.crime.id)
    assert player.save_photo("r-999") == "That photo isn't on the app any more."


def test_a_photo_saved_with_no_case_open_only_teaches_looks():
    player, *_ = make("Ann", "Bo")
    player.engine.album = Album(Random(1))
    photo = player.engine.album.take(player.town, 1, "evening", {"v1": ["bar"], "v2": ["bar"]}, player.ids)
    assert player.save_photo(photo.id) is None
    assert player.notebook == {} and set(player.known) == {"v1", "v2"}
