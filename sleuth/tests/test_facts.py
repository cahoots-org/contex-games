import json
from sleuth import facts
from sleuth.facts import Facts
from sleuth.models import Utterance


def test_recent_lists_lines_said_at_a_place_since_a_time(monkeypatch):
    kept = Facts()
    monkeypatch.setattr(facts.time, "time", lambda: 100.0)
    kept.record(Utterance("u-1", "v1", "Bert", "cafe", "old news", None))
    monkeypatch.setattr(facts.time, "time", lambda: 200.0)
    kept.record(Utterance("u-2", "v1", "Bert", "cafe", "fresh news", None))
    kept.record(Utterance("u-3", "v1", "Bert", "bar", "tavern news", None))
    kept.record(Utterance("u-4", "v2", "Ada", "cafe", "later news", None))
    assert [u.id for u in kept.recent("cafe", 150)] == ["u-2", "u-4"]
    assert kept.get("u-1").text == "old news"


def test_state_round_trips_as_json_in_order(monkeypatch):
    kept = Facts()
    monkeypatch.setattr(facts.time, "time", lambda: 100.0)
    kept.record(Utterance("u-2", "v1", "Bert", "cafe", "news", "u-1", names_newcomer=True, about="p-1"))
    kept.record(Utterance("u-1", "v2", "Ada", "bar", "more", None))
    fresh = Facts()
    fresh.restore(json.loads(json.dumps(kept.to_state())))
    assert list(fresh._by_id.items()) == list(kept._by_id.items())
