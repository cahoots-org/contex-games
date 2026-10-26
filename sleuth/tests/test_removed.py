import importlib.util

import pytest


@pytest.mark.parametrize("name", ["goals", "goal_maker", "judge", "pool", "believability", "rumors", "scenes", "overhear", "hints", "notes", "cli", "suspicion", "rapport"])
def test_rumor_game_module_is_gone(name):
    assert importlib.util.find_spec(f"sleuth.{name}") is None
