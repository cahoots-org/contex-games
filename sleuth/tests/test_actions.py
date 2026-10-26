import pytest

from sleuth.actions import ACTIONS, ALIBI, BLAME, CONFRONT, DENY, IGNORE, MOVE, RETELL, SPEAK, available_actions
from sleuth.decide import decide
from sleuth.tests.helpers import StubJev
from sleuth.tests.test_decide import view

NEWS = "Someone stole Dana Reyes's bike on Elm Street last night."


def test_no_one_can_leave_town():
    assert "leave_town" not in ACTIONS


def test_victims_and_bystanders_only_pass_news_on_react_move_or_ignore():
    assert set(available_actions(view(case=None))) == {IGNORE, RETELL, SPEAK, MOVE}


def test_only_the_culprit_covers_tracks():
    assert {ALIBI, BLAME, DENY, CONFRONT} <= set(available_actions(view(case=NEWS)))


@pytest.mark.asyncio
async def test_only_the_culprit_is_offered_the_shift_blame_manner():
    jev = StubJev({"action": IGNORE})
    await decide(jev, view())
    assert "shift_blame" not in jev.questions["style"].criteria
    await decide(jev, view(case=NEWS))
    assert "shift_blame" in jev.questions["style"].criteria
