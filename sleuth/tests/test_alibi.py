from sleuth.alibi import claim, household_question, household_word
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


def word(answer, speaker, about, phase="night"):
    cases, _, town = make_cases()
    file = culprit_file(cases, phase=phase)
    return household_word(file, town.get(speaker), town.get(about), answer), file


def test_household_cover_for_the_culprit_is_unsound():
    cases, _, town = make_cases()
    file = culprit_file(cases)
    question = household_question(file, town.get("v4"), town.get("v3"))
    assert set(question.criteria) == {"honest", "cover"} and "Fay Okafor" in question.instructions
    assert household_word(file, town.get("v4"), town.get("v3"), "cover") == ("Fay Okafor was home with me all night.", False)


def test_household_cover_for_an_innocent_is_sound():
    assert word("cover", "v1", "v2")[0] == ("Eli Reyes was home with me all night.", True)


def test_household_honest_answer_is_sound():
    assert word("honest", "v4", "v3")[0] == ("I was asleep. I can't say where Fay Okafor was.", True)


def test_no_household_word_by_day_or_for_people_living_alone():
    assert word("cover", "v4", "v3", phase="evening")[0] is None
    assert word("cover", "v5", "v3")[0] is None


def test_the_culprit_vouches_for_a_housemate_like_anyone():
    assert word("cover", "v3", "v4")[0] == ("Gus Okafor was home with me all night.", True)


def test_a_household_word_is_asked_once_per_case_speaker_and_housemate():
    cases, _, town = make_cases()
    file = culprit_file(cases)
    gus, fay = town.get("v4"), town.get("v3")
    assert household_word(file, gus, fay) is None
    first = household_word(file, gus, fay, "cover")
    assert household_word(file, gus, fay, "honest") == first and household_question(file, gus, fay) is None
    assert household_word(file, fay, gus, "honest")[0].startswith("I was asleep")
