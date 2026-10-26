from sleuth.actions import ACTIONS


def test_no_one_can_leave_town():
    assert "leave_town" not in ACTIONS
