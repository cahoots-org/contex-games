import json

import pytest

from sleuth.config import Config
from sleuth.reputation import Reputation


def test_nudge_clamps_and_decay_moves_toward_zero():
    rep = Reputation(Config(reputation_decay=0.1))
    assert rep.get("v1", "p-1") == 0
    rep.nudge("v1", "p-1", -0.8)
    rep.nudge("v1", "p-1", -0.8)
    assert rep.get("v1", "p-1") == -1
    rep.nudge_all("p-1", 0.05, ["v2", "v3"])
    assert rep.get("v2", "p-1") == pytest.approx(0.05)
    rep.decay()
    assert rep.get("v1", "p-1") == pytest.approx(-0.9) and rep.get("v2", "p-1") == 0
    assert rep.get("v1", "p-2") == 0


def test_reputation_round_trips():
    rep = Reputation(Config())
    rep.nudge("v1", "p-1", 0.3)
    rep.nudge("v2", "p-2", -0.4)
    fresh = Reputation(Config())
    fresh.restore(json.loads(json.dumps(rep.to_state())))
    assert fresh.to_state() == rep.to_state()
    assert (fresh.get("v1", "p-1"), fresh.get("v2", "p-2")) == (0.3, -0.4)
