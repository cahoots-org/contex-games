import pytest

from sleuth.alibi import claim, household_word
from sleuth.tests.helpers import StubJev
from sleuth.tests.test_case import make_routine
from sleuth.tests.test_cases import culprit_file, make_cases


def test_innocent_claim_is_their_logged_whereabouts_and_sound():
    cases, _, _ = make_cases()
    file = culprit_file(cases)
    file.whereabouts = {"v2": ["elm street", "bar"]}
    assert claim(file, "v2", make_routine()) == (["elm street", "bar"], True)


def test_culprit_claim_omits_the_crime_place_and_is_unsound():
    cases, _, _ = make_cases()
    file = culprit_file(cases)
    file.whereabouts = {"v3": ["gym", "elm street"]}
    assert claim(file, "v3", make_routine(night={"v3": "gym"})) == (["gym"], False)
    file.alibi = ["library"]
    assert claim(file, "v3", make_routine()) == (["library"], False)


async def word(answer, speaker, about, phase="night"):
    cases, _, town = make_cases()
    file = culprit_file(cases, phase=phase)
    jev = StubJev({"answer": answer})
    return await household_word(jev, file, town.get(speaker), town.get(about), town), jev


@pytest.mark.asyncio
async def test_household_cover_for_the_culprit_is_unsound():
    result, jev = await word("cover", "v4", "v3")
    assert result == ("Fay Okafor was home with me all night.", False)
    assert set(jev.questions["answer"].criteria) == {"honest", "cover"}
    assert jev.state["crime"] == "Someone stole Dana Reyes's bike on elm street last night."


@pytest.mark.asyncio
async def test_household_cover_for_an_innocent_is_sound():
    result, _ = await word("cover", "v1", "v2")
    assert result == ("Eli Reyes was home with me all night.", True)


@pytest.mark.asyncio
async def test_household_honest_answer_is_sound():
    result, _ = await word("honest", "v4", "v3")
    assert result == ("I was asleep. I can't say where Fay Okafor was.", True)


@pytest.mark.asyncio
async def test_no_household_word_by_day_or_for_people_living_alone():
    assert (await word("cover", "v4", "v3", phase="evening"))[0] is None
    assert (await word("cover", "v5", "v3"))[0] is None
