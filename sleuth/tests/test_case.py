from random import Random

from sleuth.case import Crime, clock_at, stage_crime
from sleuth.models import Villager
from sleuth.town import Town

RESIDENTS = [
    ("v1", "Dana Reyes", "h1", "elm street"),
    ("v2", "Eli Reyes", "h1", "elm street"),
    ("v3", "Fay Okafor", "h2", "elm street"),
    ("v4", "Gus Okafor", "h2", "elm street"),
    ("v5", "Hal Burke", "h3", "oak street"),
    ("v6", "Ivy Burke", "h3", "oak street"),
    ("v7", "Jo Tran", "h4", "oak street"),
    ("v8", "Kit Tran", "h4", "oak street"),
]


class StubRoutine:
    """Each resident's place per phase, from a dict."""

    def __init__(self, places):
        self.places = places

    def place(self, vid, phase):
        return self.places.get(vid, {}).get(phase)


def make_town():
    town = Town()
    traits = {"height": "tall", "hair": "bald", "coat": "grey hoodie", "car": "bicycle"}
    for vid, name, household, street in RESIDENTS:
        town.add(Villager(vid, name, "clerk", "calm", "", [], {}, dict(traits), street, household), street)
    rival, victim = town.get("v5"), town.get("v1")
    rival.relationships["v1"], victim.relationships["v5"] = "rival", "rival"
    rival.warmth["v1"] = victim.warmth["v5"] = -0.6
    return town


def make_routine(night=None):
    """Everyone home on their street at night unless night says otherwise."""
    return StubRoutine({vid: {"night": (night or {}).get(vid, street)} for vid, _, _, street in RESIDENTS})


def test_stage_crime_is_deterministic_for_a_seed():
    town, routine = make_town(), make_routine()
    assert stage_crime(town, routine, Random(7), 1, "night", "case-1") == stage_crime(town, routine, Random(7), 1, "night", "case-1")


def test_crime_is_at_the_victims_expected_place_and_the_culprit_is_expected_elsewhere():
    town, routine = make_town(), make_routine()
    for seed in range(50):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1")
        assert crime.place == routine.place(crime.victim, "night")
        assert routine.place(crime.culprit, "night") != crime.place


def test_culprit_and_victim_never_share_a_household():
    town, routine = make_town(), make_routine()
    for seed in range(50):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1")
        assert town.get(crime.culprit).household != town.get(crime.victim).household


def test_stage_crime_honours_places_and_exclude():
    town, routine = make_town(), make_routine()
    for seed in range(30):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1", places={"elm street"}, exclude=frozenset({"v1"}))
        assert crime.place == "elm street" and "v1" not in (crime.culprit, crime.victim)


def test_rival_is_the_likeliest_culprit():
    town, routine = make_town(), make_routine()
    others = frozenset({"v2", "v3", "v4"})
    crimes = [stage_crime(town, routine, Random(seed), 1, "night", "case-1", places={"elm street"}, exclude=others)
              for seed in range(200)]
    rival = [c for c in crimes if c.culprit == "v5"]
    assert len(rival) > 200 / 3 and all(c.motive == "rival" for c in rival)
    assert all(c.motive == "opportunity" for c in crimes if c.culprit != "v5")


def test_grudge_naming_the_victim_is_a_motive():
    town, routine = make_town(), make_routine()
    town.get("v7").grudge = "Fay keeps parking across my driveway."
    crimes = [stage_crime(town, routine, Random(seed), 1, "night", "case-1") for seed in range(200)]
    assert {c.motive for c in crimes if (c.culprit, c.victim) == ("v7", "v3")} == {"grudge"}


def test_returns_none_when_no_pair_fits():
    town = make_town()
    routine = make_routine({vid: "bar" for vid, *_ in RESIDENTS})
    assert stage_crime(town, routine, Random(1), 1, "night", "case-1") is None


def test_news_names_victim_place_and_time_not_culprit():
    town, routine = make_town(), make_routine()
    crime = next(c for seed in range(200)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == "steal" and c.item == "bike")
    culprit = town.get(crime.culprit)
    assert crime.text == "Someone stole Dana Reyes's bike on elm street last night." and culprit.name not in crime.text
    assert isinstance(crime, Crime) and crime.id == "case-1" and crime.day == 1 and crime.owner is None
    assert 1320 <= crime.minute < 1740


def test_clock_at_formats_twelve_hour_time():
    assert clock_at(1422) == "11:42pm" and clock_at(1500) == "1:00am" and clock_at(720) == "12:00pm"
    assert clock_at(0) == "12:00am"
