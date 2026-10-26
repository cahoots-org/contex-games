import importlib.util

import pytest

from sleuth.actions import ACTIONS
from sleuth.town import Town


@pytest.mark.parametrize("name", ["goals", "goal_maker", "judge", "pool", "believability", "rumors", "scenes", "overhear", "hints", "notes", "cli", "suspicion", "rapport"])
def test_rumor_game_module_is_gone(name):
    assert importlib.util.find_spec(f"sleuth.{name}") is None


def test_residents_have_no_groups():
    assert set(ACTIONS) == {"ignore", "retell", "deny", "confront", "speak", "move", "alibi", "blame"}
    assert not hasattr(Town, "found_group")
