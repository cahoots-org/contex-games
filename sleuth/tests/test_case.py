from random import Random

import pytest

from sleuth.case import (
    CLIP_TRAITS,
    WITNESS_ACTION,
    Crime,
    Record,
    camera_clip,
    clock_at,
    logs,
    make_solvable,
    record_json,
    stage_crime,
    suspects,
    witness_memories,
)
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.town import Town
from sleuth.traits import assign_traits

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
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == "steal" and c.item == "bike")
    culprit = town.get(crime.culprit)
    assert crime.text == "Someone stole Dana Reyes's bike on Elm Street last night." and culprit.name not in crime.text
    assert isinstance(crime, Crime) and crime.id == "case-1" and crime.day == 1 and crime.owner is None
    assert 1320 <= crime.minute < 1740


@pytest.mark.parametrize("template, text", [
    ("dog", "Someone let out Dana Reyes's dog on Elm Street last night."),
    ("trailer", "Someone drove off with Dana Reyes's marching band trailer on Elm Street last night."),
])
def test_dog_and_trailer_crimes_read_like_the_others(template, text):
    town, routine = make_town(), make_routine()
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == template)
    assert crime.text == text and WITNESS_ACTION[template]


def test_clock_at_formats_twelve_hour_time():
    assert clock_at(1422) == "11:42pm" and clock_at(1500) == "1:00am" and clock_at(720) == "12:00pm"
    assert clock_at(0) == "12:00am"


def make_case(place="elm street"):
    """A town with unique looks and a night crime on Elm Street against v1 by v5."""
    town, routine = make_town(), make_routine()
    assign_traits(town.villagers, Random(0))
    crime = Crime("case-1", "steal", "bike", "v5", "v1", place, 1, "night", 1422, "rival", "Someone stole a bike.")
    return town, routine, crime


def test_witnesses_are_expected_at_the_crime_place_and_never_culprit_or_victim():
    town, routine, crime = make_case()
    for seed in range(30):
        memories = witness_memories(crime, town, routine, Random(seed), Ids())
        assert len(memories) == 2
        for m in memories:
            assert m.kind == "memory" and m.place == "elm street" and m.case == "case-1"
            assert m.holder in {"v2", "v3", "v4"} and routine.place(m.holder, "night") == crime.place


def test_witness_sees_two_culprit_traits_and_never_a_name():
    town, routine, crime = make_case()
    culprit = town.get(crime.culprit)
    m = witness_memories(crime, town, routine, Random(3), Ids())[0]
    assert len(m.traits) == 2 and m.traits.items() <= culprit.traits.items() and culprit.name not in m.text
    assert m.id == "r-1" and m.text.startswith(f"Around {m.clock}, on Elm Street, someone ")
    assert m.text.endswith(" walked off with something.")
    assert any(clock_at(minute) == m.clock for minute in range(1402, 1443)) and m.day == crime.day


def test_clip_only_at_camera_places():
    town, _, crime = make_case("cafe")
    assert camera_clip(crime, town, Ids()) is None
    town, _, crime = make_case("bar")
    clip = camera_clip(crime, town, Ids())
    assert clip.kind == "clip" and clip.traits.keys() == set(CLIP_TRAITS) and clip.holder == ""
    assert clip.traits.items() <= town.get("v5").traits.items()
    assert clip.text.startswith("11:42pm, bar camera: a") and " figure in a " in clip.text and clip.clock == "11:42pm"
    assert clip.day == crime.day


def test_logs_list_whoever_was_at_a_log_place():
    town, _, crime = make_case()
    records = logs(crime, {"v1": ["elm street", "gym"], "v2": ["cafe"]}, town, Random(1), Ids())
    assert len(records) == 1
    r = records[0]
    assert r.who == "v1" and r.kind == "log" and r.place == "gym" and r.text.startswith("Gym check-in: Dana Reyes, ")
    assert r.day == crime.day


def test_suspects_narrow_by_traits_and_log_alibis():
    town, _, crime = make_case()
    culprit = town.get("v5")
    everyone = {v.id for v in town.villagers} - {"v1"}
    assert suspects(crime, [], town) == everyone
    seen = Record("r-1", "case-1", "memory", "elm street", "11:40pm", "", "v2", {"height": culprit.traits["height"]})
    narrowed = {v.id for v in town.villagers if v.traits["height"] == culprit.traits["height"]} - {"v1"}
    assert suspects(crime, [seen], town) == narrowed
    alibi = Record("r-2", "case-1", "log", "bar", "11:00pm", "", who="v6")
    present = Record("r-3", "case-1", "log", "elm street", "11:30pm", "", who="v7")
    elsewhere = Record("r-4", "case-1", "log", "gym", "11:10pm", "", who="v7")
    assert suspects(crime, [alibi, present, elsewhere], town) == everyone - {"v6"}


def test_make_solvable_returns_empty_when_already_singled_out():
    town, _, crime = make_case()
    full = Record("r-1", "case-1", "clip", "elm street", "11:42pm", "", traits=dict(town.get("v5").traits))
    assert make_solvable(crime, [full], town, make_routine(), Random(1), Ids()) == []


def test_make_solvable_adds_a_witness_when_evidence_is_ambiguous():
    town, routine, crime = make_case()
    added = make_solvable(crime, [], town, routine, Random(1), Ids())
    assert len(added) == 1 and suspects(crime, added, town) == {crime.culprit}
    assert added[0].kind == "memory" and added[0].holder == "v2"


def test_make_solvable_returns_none_when_the_culprit_is_logged_elsewhere():
    town, routine, crime = make_case()
    alibi = Record("r-1", "case-1", "log", "gym", "11:00pm", "", who="v5")
    assert make_solvable(crime, [alibi], town, routine, Random(1), Ids()) is None


def test_make_solvable_returns_none_when_traits_cannot_single_out_the_culprit():
    town, routine, crime = make_town(), make_routine(), make_case()[2]
    assert make_solvable(crime, [], town, routine, Random(1), Ids()) is None


def test_record_json_hides_soundness_and_traits():
    town, routine, crime = make_case()
    m = witness_memories(crime, town, routine, Random(3), Ids())[0]
    assert record_json(m, town) == {"id": m.id, "kind": "memory", "place": "elm street", "day": 1, "clock": m.clock,
                                    "text": m.text, "from": town.get(m.holder).name}
    log = Record("r-9", "case-1", "log", "gym", "11:00pm", "Gym check-in: Hal Burke, 11:00pm", who="v5")
    assert record_json(log, town)["from"] == ""


def test_make_solvable_skips_residents_who_are_already_witnesses():
    town, routine, crime = make_case()
    culprit = town.get(crime.culprit).traits
    first = Record("r-1", "case-1", "memory", "elm street", "11:40pm", "", "v2", {"height": culprit["height"]})
    added = make_solvable(crime, [first], town, routine, Random(1), Ids())
    assert len(added) == 1 and added[0].holder not in ("v2", crime.culprit, crime.victim)
    assert suspects(crime, [first, *added], town) == {crime.culprit}
