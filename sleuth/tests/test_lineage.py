import json
from sleuth.lineage import Ids, Lineage


def test_root_follows_parents():
    ln = Lineage()
    ln.record("w-1", None)
    ln.record("u-1", "w-1")
    ln.record("u-2", "u-1")
    assert ln.root("u-2") == "w-1"


def test_ids_are_monotonic_per_prefix():
    ids = Ids()
    assert [ids.next("u"), ids.next("u"), ids.next("w")] == ["u-1", "u-2", "w-1"]


def test_lineage_state_round_trips_as_json():
    ln = Lineage()
    ln.record("w-1", None)
    ln.record("u-1", "w-1")
    fresh = Lineage()
    fresh.restore(json.loads(json.dumps(ln.to_state())))
    assert fresh._parent == ln._parent


def test_ids_state_round_trips_and_can_be_raised():
    ids = Ids()
    ids.next("u")
    ids.next("u")
    ids.next("w")
    fresh = Ids()
    fresh.restore(json.loads(json.dumps(ids.to_state())))
    assert fresh.next("u") == "u-3" and fresh.next("w") == "w-2"
    fresh.ensure_past("u", 10)
    fresh.ensure_past("w", 1)
    fresh.ensure_past("goal", 4)
    assert (fresh.next("u"), fresh.next("w"), fresh.next("goal")) == ("u-11", "w-3", "goal-5")
