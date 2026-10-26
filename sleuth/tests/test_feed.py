import json

from sleuth.feed import REPLAY_EVENTS, Feed
from sleuth.lineage import Lineage
from sleuth.models import Utterance, Villager
from sleuth.tests.helpers import PID
from sleuth.town import Town


def make():
    town, lines, lineage = Town(), [], Lineage()
    for vid, name in (("v1", "Bert"), ("v2", "Marta")):
        town.add(Villager(vid, name, "baker", "calm", "none", [], {}))
    lineage.record("w-1", None)
    lineage.record("u-1", "w-1")
    lineage.record("u-2", None)
    return Feed(lineage, town, out=lines.append), lines


def utt(uid):
    return Utterance(uid, "v1", "Bert", "bar", "the miller waters his flour", "w-1")


def test_replay_is_bounded():
    feed, _ = make()
    for _ in range(REPLAY_EVENTS):
        feed.say("x")
    assert len(feed.recent) == REPLAY_EVENTS
    assert feed.recent[-1].id == REPLAY_EVENTS


def test_time_lines_name_the_day_at_dawn():
    feed, lines = make()
    feed.on_time(2, "morning")
    feed.on_time(2, "evening")
    assert lines == ["Day 2: morning in town.", "Evening: people head home from work."]
    assert [(e.kind, e.data["day"], e.data["phase"]) for e in feed.recent] == [("time", 2, "morning"), ("time", 2, "evening")]


def test_a_view_passes_only_what_its_player_sees():
    feed, seen = Feed(Lineage(), Town(), out=None), []
    feed.sinks.append(feed.view("p-a", seen.append))
    feed.emit("system", "mine", player="p-a")
    feed.emit("system", "theirs", player="p-b")
    feed.say("everyone")
    assert [e.line for e in seen] == ["mine", "everyone"]




def test_an_interview_reaches_only_the_podcaster():
    feed, lines = make()
    records = [{"id": "r-1", "kind": "memory", "place": "cafe", "clock": "9:00am", "text": "I saw it.", "from": "Marta"}]
    feed.on_interview("v2", "Marta", "What did you see?", "I saw someone tall.", records, case_id="case-1", player=PID)
    event = feed.recent[-1]
    assert (event.kind, event.player) == ("interview", PID)
    assert event.data == {"villager_id": "v2", "name": "Marta", "question": "What did you see?",
                          "line": "I saw someone tall.", "records": records, "case_id": "case-1"}
    assert lines == ['Marta: "I saw someone tall."']
    assert not feed.sees("p-2", event)


def test_state_round_trips_as_json_and_ids_go_on_past_it():
    feed, _ = make()
    feed.say("hello")
    feed.say("for one", player="p-2")
    fresh, _ = make()
    fresh.restore(json.loads(json.dumps(feed.to_state())))
    assert list(fresh.recent) == list(feed.recent)
    assert fresh.say("next").id == feed.say("next").id
    fresh.ensure_past(40)
    assert fresh.say("later").id == 41


def test_pulled_records_carry_the_line_the_page_shows():
    feed, lines = make()
    feed.on_pulled("bar", [], case_id="case-1", player=PID)
    feed.on_pulled("elm street", [], case_id="case-1", player=PID)
    assert {e.data["case_id"] for e in feed.recent} == {"case-1"}
    assert [e.data["text"] for e in feed.recent] == lines == ["You pulled the records at the bar.",
                                                              "You pulled the records on Elm Street."]


def test_a_player_in_the_practice_town_sees_only_their_own_events_and_the_town_s_rest():
    feed, _ = make()
    feed.practising.add(PID)
    feed.on_case({"id": "case-1", "text": "Someone stole a bike."})
    feed.on_post(utt("u-1"), "case-1")
    feed.on_case({"id": "case-2", "text": "Someone let out a dog."}, player=PID)
    feed.on_time(1, "evening")
    feed.on_rest(True)
    assert [e.kind for e in feed.replay(PID)] == ["case", "rest"] and feed.replay(PID)[0].player == PID
    assert [e.kind for e in feed.replay("p-2")] == ["case", "post", "time", "rest"]


def test_forgetting_a_player_drops_only_their_own_events():
    feed, _ = make()
    feed.say("for everyone")
    feed.say("for you", player=PID)
    feed.say("for them", player="p-2")
    feed.forget(PID)
    assert [e.data["text"] for e in feed.recent] == ["for everyone", "for them"]


def test_only_the_apps_own_posts_are_marked_as_the_app():
    feed, _ = make()
    feed.on_post(utt("u-1"), "case-1")
    feed.on_post(Utterance("u-3", "app", "The neighborhood app", "bar", "Someone stole a bike.", None), "case-1")
    assert [e.data["app"] for e in feed.recent] == [False, True]


def test_only_its_author_sees_an_episode_as_theirs_with_its_verdict():
    feed, lines = make()
    feed.on_episode("case-1", "Bert", False, by=PID, cited=2, verdict="It didn't hold up.")
    assert lines == ["A podcaster's episode names Bert."]
    event = feed.recent[-1]
    mine, theirs = event.to_json(PID), event.to_json("p-2")
    assert (mine["mine"], mine["cited"], mine["verdict"]) == (True, 2, "It didn't hold up.")
    assert theirs["mine"] is False and "verdict" not in theirs
    assert "by" not in mine and "by" not in theirs


def test_a_search_says_where_it_was():
    feed, lines = make()
    feed.on_searched("bar", [], case_id="case-1", player=PID)
    assert feed.recent[-1].data["text"] == lines[-1] == "You searched the bar."
