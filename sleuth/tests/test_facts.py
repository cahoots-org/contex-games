import json
from sleuth import facts
from sleuth.facts import Facts
from sleuth.models import Utterance


def test_get_finds_a_kept_line(monkeypatch):
    kept = Facts()
    monkeypatch.setattr(facts.time, "time", lambda: 100.0)
    kept.record(Utterance("u-1", "v1", "Bert", "cafe", "old news", None))
    monkeypatch.setattr(facts.time, "time", lambda: 200.0)
    kept.record(Utterance("u-2", "v1", "Bert", "cafe", "fresh news", None))
    kept.record(Utterance("u-3", "v1", "Bert", "bar", "tavern news", None))
    kept.record(Utterance("u-4", "v2", "Ada", "cafe", "later news", None))
    assert kept.get("u-1").text == "old news"


def test_state_round_trips_as_json_in_order(monkeypatch):
    kept = Facts()
    monkeypatch.setattr(facts.time, "time", lambda: 100.0)
    kept.record(Utterance("u-2", "v1", "Bert", "cafe", "news", "u-1", depth=1, audience="room"))
    kept.record(Utterance("u-1", "v2", "Ada", "bar", "more", None))
    fresh = Facts()
    fresh.restore(json.loads(json.dumps(kept.to_state())))
    assert list(fresh._by_id.items()) == list(kept._by_id.items())
