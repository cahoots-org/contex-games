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


def test_unrooted_announcements_reach_sinks_but_not_the_terminal():
    feed, lines = make()
    seen = []
    feed.sinks.append(seen.append)
    feed.on_delivery(Utterance("u-2", "v1", "Bert", "cafe", "Bert joined The Watch", None, "announced"), [])
    feed.on_delivery(utt("u-2"), ["v2"])
    assert [e.kind for e in seen] == ["announcement"]
    assert lines == []


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
    assert lines == ["Day 2 dawns over the village.", "Evening falls, and lamps are lit."]
    assert [(e.kind, e.data["day"], e.data["phase"]) for e in feed.recent] == [("time", 2, "morning"), ("time", 2, "evening")]


def test_a_view_passes_only_what_its_player_sees():
    feed, seen = Feed(Lineage(), Town(), out=None), []
    feed.sinks.append(feed.view("p-a", seen.append))
    feed.emit("system", "mine", player="p-a")
    feed.emit("system", "theirs", player="p-b")
    feed.say("everyone")
    assert [e.line for e in seen] == ["mine", "everyone"]


def test_listen_events_reach_only_the_listener_and_print_the_lines():
    feed, lines = make()
    said = Utterance("u-9", "v3", "Ada", "cafe", "the well is dry", None)
    feed.on_listen("cafe", [said], 123.0, player=PID)
    event = feed.recent[-1]
    assert (event.kind, event.player, event.data["ended"], event.data["until"]) == ("listen", PID, False, 123.0)
    assert event.data["lines"] == [{"speaker": "v3", "speaker_name": "Ada", "text": "the well is dry"}]
    assert lines == ["Recently said at the cafe:\nAda: \"the well is dry\""]
    assert not feed.sees("p-2", event)
    feed.on_listen("gym", [], 124.0, player=PID)
    assert lines[-1] == "Nothing has been said at the gym lately."
    feed.on_listen_end("gym", player=PID)
    assert (feed.recent[-1].data["ended"], feed.recent[-1].player, len(lines)) == (True, PID, 2)


def test_an_interview_reaches_only_the_podcaster():
    feed, lines = make()
    records = [{"id": "r-1", "kind": "memory", "place": "cafe", "clock": "9:00am", "text": "I saw it.", "from": "Marta"}]
    feed.on_interview("v2", "Marta", "I saw someone tall.", records, player=PID)
    event = feed.recent[-1]
    assert (event.kind, event.player) == ("interview", PID)
    assert event.data == {"villager_id": "v2", "name": "Marta", "line": "I saw someone tall.", "records": records}
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
