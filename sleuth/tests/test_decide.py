import logging
import random

import pytest

from sleuth.actions import (
    CONFRONT, DENY, IGNORE, MOVE, RETELL, SPEAK, WARN,
)
from sleuth.contex_client import Match
from sleuth.decide import (
    GOSSIP_LEVELS, Decision, TurnView, decide, warmth_words,
)
from sleuth.models import Villager
from sleuth.tests.helpers import StubJev


def villager(vid="v1", name="Ada"):
    return Villager(vid, name, "baker", "gossipy", "", [], {})


def match(key, text="x"):
    return Match(key, {"text": text})


def view(**kw):
    base = dict(
        villager=villager(), place="cafe", present=[villager("v2", "Bo")],
        new=[match("m1")], recent=[],
    )
    return TurnView(**{**base, **kw})


@pytest.mark.asyncio
async def test_alone_in_place_excludes_social_actions_and_target_question():
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(present=[]))
    criteria = jev.questions["action"].criteria
    for a in (RETELL, DENY, CONFRONT, SPEAK):
        assert a not in criteria
    assert "villager_target" not in jev.questions


@pytest.mark.asyncio
async def test_no_walking_off_at_night():
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(night=True))
    assert MOVE not in jev.questions["action"].criteria and "place_target" not in jev.questions


@pytest.mark.asyncio
async def test_single_new_item_skips_source_question_and_is_the_source():
    jev = StubJev({"action": RETELL, "villager_target": "v2", "style": "delighted"})
    d = await decide(jev, view())
    assert "source" not in jev.questions
    assert d.source == match("m1")


@pytest.mark.asyncio
async def test_multiple_new_items_ask_source():
    jev = StubJev({"action": RETELL, "source": "m2", "villager_target": "v2", "style": "delighted"})
    d = await decide(jev, view(new=[match("m1"), match("m2")]))
    assert set(jev.questions["source"].criteria) == {"m1", "m2"}
    assert d.source.data_key == "m2"


@pytest.mark.asyncio
async def test_target_options_capped_at_255():
    present = [villager(f"v{i}", f"N{i}") for i in range(300)]
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(present=present))
    assert len(jev.questions["villager_target"].criteria) == 255


@pytest.mark.asyncio
async def test_ignore_returns_empty_decision():
    d = await decide(StubJev({"action": IGNORE}), view())
    assert d == Decision(IGNORE, None, None, None)


@pytest.mark.asyncio
async def test_retell_maps_chosen_target_and_style():
    jev = StubJev({"action": RETELL, "villager_target": "v2", "style": "exaggerated"})
    d = await decide(jev, view())
    assert d == Decision(RETELL, match("m1"), "v2", "exaggerated")


@pytest.mark.asyncio
async def test_move_uses_its_own_target_question():
    jev = StubJev({"action": MOVE, "place_target": "bar"})
    d = await decide(jev, view())
    assert "cafe" not in jev.questions["place_target"].criteria
    assert d.target == "bar"


@pytest.mark.asyncio
async def test_no_new_items_means_no_source():
    d = await decide(StubJev({"action": SPEAK}), view(new=[]))
    assert d.source is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", [DENY, CONFRONT, SPEAK])
async def test_style_kept_for_speech_actions(action):
    jev = StubJev({"action": action, "villager_target": "v2", "style": "soften"})
    assert (await decide(jev, view())).style == "soften"


@pytest.mark.asyncio
async def test_style_none_for_non_speech():
    jev = StubJev({"action": IGNORE, "style": "delighted"})
    assert (await decide(jev, view())).style is None


@pytest.mark.asyncio
async def test_target_descriptions_include_names():
    jev = StubJev({"action": IGNORE})
    await decide(jev, view())
    assert "Bo" in jev.questions["villager_target"].criteria["v2"]


@pytest.mark.asyncio
async def test_relationships_are_named_for_people_present():
    ada = Villager("v1", "Ada", "baker", "gossipy", "", [], {"v2": "rival", "v9": "spouse"})
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(villager=ada))
    assert jev.state["relationships_here"] == {"Bo": "rival, cool"}
    assert jev.questions["villager_target"].criteria["v2"] == "Bo, baker, their rival"


@pytest.mark.asyncio
async def test_turn_state_shows_tie_warmth_in_words():
    ada = Villager("v1", "Ada", "baker", "gossipy", "", [], {"v2": "spouse"}, warmth={"v2": 0.8})
    dana = Villager("v2", "Dana", "baker", "calm", "", [], {})
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(villager=ada, present=[dana]))
    assert jev.state["relationships_here"] == {"Dana": "spouse, close"}


def test_warmth_words():
    assert [warmth_words(w) for w in (0.6, 0.59, 0.2, 0.19, -0.19, -0.2, -1)] == [
        "close", "friendly", "friendly", "cool", "cool", "hostile", "hostile",
    ]


@pytest.mark.asyncio
async def test_action_is_drawn_from_jev_probabilities():
    jev = StubJev({"action": SPEAK})
    real = jev.system_one

    async def system_one(state, questions):
        resp = await real(state, questions)
        resp.choices["action"].probabilities = {SPEAK: 0.0, MOVE: 1.0}
        return resp

    jev.system_one = system_one
    decision = await decide(jev, view())
    assert decision.action == MOVE


def with_odds(odds):
    jev = StubJev({"action": max(odds, key=odds.get)})
    real = jev.system_one

    async def system_one(state, questions):
        resp = await real(state, questions)
        resp.choices["action"].probabilities = odds
        return resp

    jev.system_one = system_one
    return jev


@pytest.mark.asyncio
async def test_options_below_the_floor_are_never_drawn():
    random.seed(7)
    jev = with_odds({SPEAK: 0.57, RETELL: 0.40, MOVE: 0.03})
    drawn = {(await decide(jev, view())).action for _ in range(500)}
    assert drawn == {SPEAK, RETELL}


@pytest.mark.asyncio
async def test_argmax_chosen_when_every_option_is_below_the_floor():
    jev = with_odds({SPEAK: 0.09, RETELL: 0.05, MOVE: 0.04})
    assert {(await decide(jev, view())).action for _ in range(50)} == {SPEAK}


@pytest.mark.asyncio
async def test_odds_and_drawn_action_are_logged_at_debug(caplog):
    jev = with_odds({SPEAK: 1.0})
    with caplog.at_level(logging.DEBUG):
        await decide(jev, view())
    assert "v1" in caplog.text and SPEAK in caplog.text


@pytest.mark.asyncio
async def test_warm_styles_are_offered_and_kept():
    jev = StubJev({"action": SPEAK, "style": "worried"})
    d = await decide(jev, view())
    assert {"delighted", "worried"} <= set(jev.questions["style"].criteria)
    assert "conspiratorial" not in jev.questions["style"].criteria
    assert d.style == "worried"


@pytest.mark.asyncio
async def test_gossip_is_asked_only_when_requested_and_scaled():
    jev = StubJev({"action": IGNORE}, scores={"gossip": 3.0})
    assert (await decide(jev, view())).gossip is None and "gossip" not in jev.questions
    d = await decide(jev, view(ask_gossip=True))
    assert list(jev.questions["gossip"].criteria) == GOSSIP_LEVELS
    assert d.gossip == 1.0


@pytest.mark.asyncio
async def test_a_move_keeps_its_manner_for_sharing_on_arrival():
    jev = StubJev({"action": MOVE, "place_target": "bar", "style": "worried"})
    d = await decide(jev, view())
    assert (d.action, d.target, d.style) == (MOVE, "bar", "worried")


@pytest.mark.asyncio
async def test_a_culprits_state_holds_their_crime_and_no_one_elses_does():
    news = "Someone stole Dana Reyes's bike on Elm Street last night."
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(case=news))
    assert news in jev.state["your_secret"]
    await decide(jev, view())
    assert "your_secret" not in jev.state and news not in str(jev.state)


@pytest.mark.asyncio
async def test_warning_is_offered_only_to_a_pressed_culprit_with_someone_nearby():
    jev = StubJev({"action": IGNORE})
    await decide(jev, view(case="x"))
    assert WARN not in jev.questions["action"].criteria
    await decide(jev, view(case="x", warn=True, present=[]))
    assert WARN not in jev.questions["action"].criteria
    await decide(jev, view(case="x", warn=True))
    assert WARN in jev.questions["action"].criteria


@pytest.mark.asyncio
async def test_residents_feel_their_district_s_mood():
    jev = StubJev({"action": IGNORE})
    ada = villager()
    ada.home = "elm street"
    await decide(jev, view(villager=ada, mood="rattled, but the Elm Street Group Chat is on it"))
    assert jev.state["neighborhood_mood"] == "Elm Street is rattled, but the Elm Street Group Chat is on it"
    await decide(jev, view(villager=ada))
    assert "neighborhood_mood" not in jev.state
