from sleuth.actions import ACTIONS, ALIBI, BLAME, available_actions
from sleuth.tests.test_decide import view


def test_no_one_can_leave_town():
    assert "leave_town" not in ACTIONS


def test_alibi_and_blame_only_for_the_culprit():
    assert not {ALIBI, BLAME} & set(available_actions(view(case=None)))
    assert {ALIBI, BLAME} <= set(available_actions(view(case="Someone stole Dana Reyes's bike on elm street last night.")))
