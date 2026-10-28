import re
from dataclasses import replace
from random import Random

import pytest

from sleuth.case import (
    CLIP_TRAITS,
    CRIMES,
    ITEM_PLACES,
    PHASE_MINUTES,
    RECEIPT_BEFORE,
    WHEN,
    Crime,
    Record,
    camera_clip,
    catalog_tiers,
    crime_title,
    clock_at,
    discovery,
    found_it,
    logs,
    make_solvable,
    points_at,
    record_json,
    recall_more,
    scene_clues,
    stage_crime,
    suspects,
    ago,
    misdated,
    motives,
    retime,
    told,
    victim_memory,
    witness_memories,
)
from sleuth.districts import district_of
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.tests.helpers import StubRoutine
from sleuth.town import PLACES, STREETS, Town, at
from sleuth.traits import assign_traits, describe
from sleuth.writer import CLOCK

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


def test_culprit_is_sometimes_a_regular_at_the_scene_and_otherwise_expected_elsewhere():
    town, routine = make_town(), make_routine()
    crimes = [stage_crime(town, routine, Random(seed), 1, "night", "case-1") for seed in range(300)]
    assert all(c.place == routine.place(c.victim, "night") for c in crimes)
    regulars = [c for c in crimes if routine.place(c.culprit, "night") == c.place]
    assert 300 / 6 < len(regulars) < 300 / 2


def test_culprit_and_victim_never_share_a_household():
    town, routine = make_town(), make_routine()
    for seed in range(50):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1")
        assert town.get(crime.culprit).household != town.get(crime.victim).household


def test_stage_crime_honours_exclude():
    town, routine = make_town(), make_routine()
    for seed in range(30):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1", exclude=frozenset({"v1"}))
        assert "v1" not in (crime.culprit, crime.victim)


def test_rival_is_the_likeliest_culprit():
    town, routine = make_town(), make_routine()
    others = frozenset({"v2", "v3", "v4"})
    crimes = [c for seed in range(400)
              if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1", exclude=others)).victim == "v1"]
    rival = [c for c in crimes if c.culprit == "v5"]
    assert len(rival) > len(crimes) / 3 and all(c.motive == "rival" for c in rival)
    assert all(c.motive == "opportunity" for c in crimes if c.culprit != "v5")


def test_grudge_naming_the_victim_is_a_motive():
    town, routine = make_town(), make_routine()
    town.get("v7").grudge = "Fay keeps parking across my driveway."
    crimes = [stage_crime(town, routine, Random(seed), 1, "night", "case-1") for seed in range(200)]
    assert {c.motive for c in crimes if (c.culprit, c.victim) == ("v7", "v3")} == {"grudge"}


def test_returns_none_when_no_pair_fits():
    town = make_town()
    for v in town.villagers:
        v.household = "h1"
    assert stage_crime(town, make_routine(), Random(1), 1, "night", "case-1") is None


def test_news_names_victim_place_and_time_not_culprit():
    town, routine = make_town(), make_routine()
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == "steal" and c.item == "bike")
    culprit = town.get(crime.culprit)
    assert crime.text == f"Someone stole Dana Reyes's bike on Elm Street {WHEN}." and culprit.name not in crime.text
    assert told(crime.text, crime, 2) == "Someone stole Dana Reyes's bike on Elm Street last night."
    assert isinstance(crime, Crime) and crime.id == "case-1" and crime.day == 1 and crime.owner is None
    assert 1320 <= crime.minute < 1740


@pytest.mark.parametrize("template, night, text", [
    ("dog", {}, "Someone let out Dana Reyes's dog on Elm Street last night."),
    ("trailer", {"v1": "school"}, "Someone drove off with Dana Reyes's marching band trailer at the school last night."),
])
def test_dog_and_trailer_crimes_read_like_the_others(template, night, text):
    town, routine = make_town(), make_routine(night)
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == template)
    assert told(crime.text, crime, 2) == text and CRIMES[template].seen


def test_every_item_is_only_ever_staged_at_its_places_and_no_line_uses_a_pronoun():
    town = make_town()
    for i, place in enumerate(PLACES):
        routine = make_routine({vid: place if n % 2 else PLACES[i - 1] for n, (vid, *_) in enumerate(RESIDENTS)})
        for seed in range(60):
            crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1")
            if crime is None:
                continue
            assert crime.place in ITEM_PLACES[crime.item]
            found = discovery(crime, town, Random(seed), Ids())
            for line in (crime.text, found.text):
                assert not re.search(r"\b(their|his|her)\b", line, re.IGNORECASE), line
    assert {i for i, p in ITEM_PLACES.items() if "bar" in p} == {"car", "till", "cash box", "wallet", "phone", ""}


@pytest.mark.parametrize("today, said", [(2, "this afternoon"), (3, "yesterday afternoon"),
                                         (4, "two days ago, in the afternoon")])
def test_a_time_is_said_from_the_day_it_is_told(today, said):
    assert ago(2, "afternoon", today) == said


def test_a_night_is_tonight_then_last_night():
    assert [ago(2, "night", today) for today in (2, 3, 4, 9)] == [
        "tonight", "last night", "two days ago, at night", "7 days ago, at night"]


def test_an_evening_read_after_midnight_is_last_night():
    assert [ago(2, "evening", today) for today in (2.5, 2.75, 3)] == ["this evening", "last night", "yesterday evening"]
    assert ago(2, "night", 2.75) == "tonight" and ago(2, "afternoon", 2.75) == "this afternoon"


def test_told_says_the_crime_time_from_today_or_its_own_day():
    crime = Crime("case-1", "steal", "bike", "v3", "v1", "gym", 2, "afternoon", 800, "rival", f"Gone {WHEN}.")
    assert [told(crime.text, crime, today) for today in (None, 2, 3, 4)] == [
        "Gone this afternoon.", "Gone this afternoon.", "Gone yesterday afternoon.", "Gone two days ago, in the afternoon."]


def test_retime_swaps_any_said_time_for_the_given_one():
    said = "I was at the gym this afternoon. Tonight? Yesterday evening, two days ago, at night, last night."
    assert retime(said, WHEN) == "I was at the gym {when}. {when}? {when}, {when}, {when}."
    assert retime("I was home all night, in the afternoon.", WHEN) == "I was home all night, in the afternoon."


def test_misdated_is_a_said_time_the_allowed_text_does_not_give():
    allowed = "Someone stole a bike two days ago, in the afternoon."
    assert misdated("I saw it this afternoon.", allowed) and misdated("Last night, I think.", allowed)
    assert not misdated("It was two days ago, in the afternoon, around 2pm.", allowed)
    assert not misdated("Around 2pm, someone tall.", allowed)


def test_last_night_and_tonight_may_stand_for_the_evening_they_say():
    assert not misdated("It was last night.", "yesterday evening") and not misdated("Tonight, I think.", "this evening")
    assert misdated("It was last night.", "yesterday afternoon") and misdated("Tonight.", "yesterday evening")


def test_clock_at_formats_twelve_hour_time():
    assert clock_at(1422) == "11:42pm" and clock_at(1500) == "1:00am" and clock_at(720) == "12:00pm"
    assert clock_at(0) == "12:00am"


def make_case(place="elm street"):
    """A town with unique looks and a night crime on Elm Street against v1 by v5."""
    town, routine = make_town(), make_routine()
    assign_traits(town.villagers, Random(0))
    town.dress(1, Random(0))
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
    assert len(m.traits) == 2 and m.traits.items() <= town.looks(culprit.id, 1).items() and culprit.name not in m.text
    assert m.id == "r-1" and m.text.startswith(f"Around {m.clock}, on Elm Street, someone ")
    assert m.text.endswith(" walked off with something.")
    assert any(clock_at(minute) == m.clock for minute in range(1402, 1443)) and m.day == crime.day


def test_clip_only_at_camera_places():
    town, _, crime = make_case("cafe")
    assert camera_clip(crime, town, Ids()) is None
    town, _, crime = make_case("bar")
    clip = camera_clip(crime, town, Ids())
    assert clip.kind == "clip" and clip.traits.keys() == set(CLIP_TRAITS) and clip.holder == ""
    assert clip.traits.items() <= town.looks("v5", 1).items()
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
    full = Record("r-1", "case-1", "clip", "elm street", "11:42pm", "", traits=town.looks("v5", 1))
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


def test_make_solvable_adds_a_pointing_record_when_only_logs_elsewhere_narrow_the_case():
    town, routine, crime = make_case()
    elsewhere = [Record(f"r-{i}", "case-1", "log", "gym", "11:00pm", "", who=v.id)
                 for i, v in enumerate(town.villagers) if v.id not in (crime.culprit, crime.victim)]
    assert suspects(crime, elsewhere, town) == {crime.culprit}
    added = make_solvable(crime, elsewhere, town, routine, Random(1), Ids())
    culprit = town.looks(crime.culprit, 1)
    assert added and any(points_at(crime, crime.culprit, culprit, r) for r in added)


def test_every_crime_says_what_was_done_as_a_gerund():
    assert all(kind.doing.split()[0].endswith("ing") for kind in CRIMES.values() if kind.tier != "major")
    assert CRIMES["trailer"].doing == "driving off with"


def test_notebook_entries_from_someone_who_left_still_show_their_name():
    town = make_town()
    said = Record("r-1", "case-1", "statement", "gym", "9:00pm", "Hal Burke says they were at the gym.", "v5")
    town.remove("v5")
    assert record_json(said, town)["from"] == "Hal Burke"


def test_record_json_hides_soundness_and_traits():
    town, routine, crime = make_case()
    m = witness_memories(crime, town, routine, Random(3), Ids())[0]
    assert record_json(m, town) == {"id": m.id, "kind": "memory", "place": "elm street", "day": 1, "clock": m.clock,
                                    "text": m.text, "from": town.get(m.holder).name, "holder": m.holder}
    log = Record("r-9", "case-1", "log", "gym", "11:00pm", "Gym check-in: Hal Burke, 11:00pm", who="v5")
    assert record_json(log, town)["from"] == ""
    said = Record("r-8", "case-1", "statement", "gym", "9:00am", f"Hal Burke says they were at the gym {WHEN}.", "v5")
    assert record_json(said, town, crime, 2)["text"] == "Hal Burke says they were at the gym last night."


def test_make_solvable_skips_residents_who_are_already_witnesses():
    town, routine, crime = make_case()
    culprit = town.looks(crime.culprit, 1)
    first = Record("r-1", "case-1", "memory", "elm street", "11:40pm", "", "v2", {"height": culprit["height"]})
    added = make_solvable(crime, [first], town, routine, Random(1), Ids())
    assert len(added) == 1 and added[0].holder not in ("v2", crime.culprit, crime.victim)
    assert suspects(crime, [first, *added], town) == {crime.culprit}


def test_the_victim_finds_the_crime_after_it_and_names_no_one():
    town, routine = make_town(), make_routine()
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == "steal" and c.item == "bike")
    found = discovery(crime, town, Random(0), Ids())
    assert (found.kind, found.holder, found.case, found.place, found.day) == ("discovery", "v1", "case-1", "elm street", 1)
    assert found.text == f"Around {found.clock}, Dana Reyes found the bike missing on Elm Street."
    assert found_it(crime, found.clock) == f"Around {found.clock}, I found my bike missing on Elm Street."
    assert found.traits == {} and found.sound and not points_at(crime, crime.culprit, town.looks(crime.culprit, 1), found)
    assert crime.minute < [m for m in range(1320, 1740) if clock_at(m) == found.clock][0] < 1740
    assert not any(v.name in found.text for v in town.villagers if v.id != "v1")


def test_scene_clues_are_one_or_two_traces_or_a_dropped_receipt_with_a_store_log():
    town, routine, crime = make_case()
    culprit = town.looks(crime.culprit, 1)
    there = {crime.culprit, *(v.id for v in town.villagers if routine.place(v.id, "night") == crime.place)} - {crime.victim}
    shapes = set()
    for seed in range(60):
        records = scene_clues(crime, town, routine, Random(seed), Ids())
        clues = [r for r in records if r.kind == "clue"]
        assert 1 <= len(clues) <= 2 and len({r.id for r in records}) == len(records)
        for r in clues:
            assert (r.kind, r.place, r.case, r.holder, r.day, r.sound, r.who) == ("clue", crime.place, "case-1", "", 1, True, None)
            assert not any(v.name in r.text for v in town.villagers)
            if r.traits:
                [(trait, value)] = r.traits.items()
                assert culprit[trait] == value and value in r.text
                shapes.add(trait)
            else:
                [store] = [r2 for r2 in records if r2.kind == "log"]
                assert store.place == "grocery" and "grocery" in r.text and store.clock == r.clock and store.clock in r.text
                assert store.who in there and town.get(store.who).name in store.text and store.trail
                assert not points_at(crime, crime.culprit, culprit, r)
                assert points_at(crime, crime.culprit, culprit, store) == (store.who == crime.culprit)
                shapes.add("receipt" + ("-culprit" if store.who == crime.culprit else "-bystander"))
        assert len(records) == len(clues) + sum(not r.traits for r in clues)
    assert shapes == {"height", "coat", "car", "receipt-culprit", "receipt-bystander"}


@pytest.mark.parametrize("phase", ["morning", "afternoon", "evening", "night"])
def test_a_receipt_is_stamped_shortly_before_the_crime_in_its_part_of_the_day(phase):
    town, routine, crime = make_case()
    lo, hi = PHASE_MINUTES[phase]
    for minute in (lo, lo + 15, (lo + hi) // 2, hi - 1):
        crime = replace(crime, phase=phase, minute=minute)
        for seed in range(30):
            for r in scene_clues(crime, town, routine, Random(seed), Ids()):
                if r.kind == "clue" and not r.traits:
                    [stamped] = [m for m in range(lo, minute + 1) if clock_at(m) == r.clock]
                    assert minute - stamped <= RECEIPT_BEFORE[1]


def test_a_culprits_receipt_log_alone_solves_the_case():
    town, routine, crime = make_case()
    culprit = town.looks(crime.culprit, 1)
    seeds = (Random(s) for s in range(200))
    records = next(r for r in (scene_clues(crime, town, routine, g, Ids()) for g in seeds)
                   if len(r) == 2 and r[1].who == crime.culprit and not r[0].traits)
    assert crime.culprit in suspects(crime, records, town)
    assert make_solvable(crime, records, town, routine, Random(1), Ids()) is not None
    assert not any(points_at(crime, crime.culprit, culprit, r) for r in records if r.kind == "clue")
    assert any(points_at(crime, crime.culprit, culprit, r) for r in records if r.kind == "log")


def test_clues_point_and_narrow_like_sightings_and_logs():
    town, _, crime = make_case()
    culprit = town.looks(crime.culprit, 1)
    thread = Record("r-1", "case-1", "clue", "elm street", "", "", traits={"coat": culprit["coat"]})
    mine = Record("r-2", "case-1", "log", "grocery", "10:02pm", "", who=crime.culprit, trail=True)
    theirs = Record("r-3", "case-1", "log", "grocery", "10:02pm", "", who="v2", trail=True)
    assert points_at(crime, crime.culprit, culprit, thread) and points_at(crime, crime.culprit, culprit, mine)
    assert not points_at(crime, crime.culprit, culprit, theirs)
    assert crime.culprit in suspects(crime, [mine], town)
    assert suspects(crime, [thread], town) == {v.id for v in town.villagers
                                               if town.looks(v.id, 1)["coat"] == culprit["coat"]} - {crime.victim}
    full = Record("r-4", "case-1", "clue", "elm street", "", "", traits=dict(culprit))
    assert make_solvable(crime, [full], town, make_routine(), Random(1), Ids()) == []


def test_witness_and_clip_report_the_outfit_worn_on_the_crime_day():
    town, routine, crime = make_case("bar")
    town.get("v5").wardrobe = ["green raincoat", "plaid flannel"]
    town.worn = {1: {"v5": "green raincoat"}, 2: {"v5": "plaid flannel"}}
    assert camera_clip(crime, town, Ids()).traits["coat"] == "green raincoat"
    crime = replace(crime, place="elm street")
    for seed in range(20):
        for m in witness_memories(crime, town, routine, Random(seed), Ids()):
            assert m.traits.get("coat", "green raincoat") == "green raincoat"


def test_suspects_match_what_each_wore_on_the_crime_day():
    town, _, crime = make_case()
    town.get("v3").traits = dict(town.get("v5").traits)
    town.worn = {1: {"v5": "green raincoat", "v3": "grey hoodie"}, 2: {"v3": "green raincoat"}}
    clip = Record("r-1", "case-1", "clip", "elm street", "11:42pm", "", traits={"coat": "green raincoat"})
    left = suspects(crime, [clip], town)
    assert "v5" in left and "v3" not in left


def test_make_solvable_narrows_on_the_crime_day_outfit():
    town, routine, crime = make_town(), make_routine(), make_case()[2]
    town.worn = {1: {v.id: "grey hoodie" for v in town.villagers}, 2: {}}
    town.worn[1]["v5"] = "green raincoat"
    added = make_solvable(crime, [], town, routine, Random(1), Ids())
    assert added and added[0].traits.get("coat") == "green raincoat"


def test_every_crime_kind_has_places_for_its_items():
    assert all(item in ITEM_PLACES for k in CRIMES.values() for item in k.items)


def test_the_catalog_has_petty_serious_and_major_crimes():
    assert catalog_tiers() == ("petty", "serious", "major")


def feuding(town):
    """Dana (v1) is on cold terms with Hal (v5), Jo (v7) and Kit (v8)."""
    town.get("v7").warmth["v1"] = -0.3
    town.get("v1").warmth["v8"] = -0.2
    return town


def test_the_news_gives_a_window_not_a_time():
    town, routine = feuding(make_town()), make_routine()
    crime = next(c for seed in range(20)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1", tier="major")).window[0] == "evening")
    assert crime.template == "death" and crime.window == ["evening", "night"]
    text = told(crime.text, crime, 2.0)
    assert text == (f"{town.get(crime.victim).name} was found dead on Elm Street. It happened sometime between "
                    "yesterday evening and last night. Police are treating it as suspicious.")
    assert not CLOCK.search(text)
    first = replace(crime, window=["night", "morning"])
    assert told(first.text, first, 2.0).endswith("sometime between last night and this morning. Police are treating "
                                                 "it as suspicious.")
    morning = Crime("case-2", "death", "", "v5", "v1", "cafe", 2, "morning", 500, "rival", "It happened {span}.",
                    tier="major", window=["night", "morning"])
    assert told(morning.text, morning, 2.25) == "It happened sometime between last night and this morning."
    assert told(morning.text, morning, 3.0) == "It happened sometime between two days ago, at night and yesterday morning."


def test_the_true_part_of_the_day_is_sometimes_first_in_the_window():
    town, routine = feuding(make_town()), make_routine()
    windows = {tuple(stage_crime(town, routine, Random(seed), 1, "night", "case-1", tier="major").window)
               for seed in range(30)}
    assert windows == {("evening", "night"), ("night", "morning")}


def test_a_span_is_one_said_time():
    span = "sometime between last night and this morning"
    assert retime(f"It happened {span}.", "yesterday morning") == "It happened yesterday morning."
    assert not misdated(f"Awful, {span}.", f"It happened {span}.")
    assert misdated("Awful, yesterday evening.", f"It happened {span}.")


def test_a_death_s_victim_has_at_least_two_others_with_reason():
    town, routine = make_town(), make_routine()
    assert all(stage_crime(town, routine, Random(s), 1, "night", "case-1", tier="major") is None for s in range(20))
    feuding(town)
    for seed in range(20):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1", tier="major")
        assert crime.victim == "v1" and len(set(motives(town, "v1")) - {crime.culprit}) >= 2
    assert motives(town, "v1") == ["v5", "v7", "v8"]


def test_a_grudge_either_way_is_a_motive():
    town = make_town()
    town.get("v7").grudge = "Dana never returned my ladder."
    town.get("v1").grudge = "Kit's dog digs up my roses."
    assert motives(town, "v1") == ["v5", "v7", "v8"]


def test_a_till_is_robbed_from_someone_who_works_at_the_scene():
    town = make_town()
    routine = StubRoutine({vid: {"morning": "school", "evening": "gym"} for vid, *_ in RESIDENTS})
    routine.places["v6"] = {"morning": "bar", "evening": "bar"}
    for seed in range(30):
        crime = stage_crime(town, routine, Random(seed), 1, "evening", "case-1", tier="serious")
        assert crime.item not in ("till", "cash box") or crime.victim == "v6"
    tills = [c for seed in range(30) if (c := stage_crime(town, routine, Random(seed), 1, "evening", "case-1",
                                                          tier="serious")).item in ("till", "cash box")]
    assert tills


def test_a_death_never_happens_at_the_school():
    assert "school" not in ITEM_PLACES[""] and "cafe" in ITEM_PLACES[""]


def test_a_serious_culprit_is_never_a_regular_at_the_scene():
    town, routine = make_town(), make_routine()
    for seed in range(50):
        crime = stage_crime(town, routine, Random(seed), 1, "night", "case-1", tier="serious")
        assert CRIMES[crime.template].tier == crime.tier == "serious"
        assert routine.place(crime.culprit, "night") != crime.place


def test_a_serious_crime_has_up_to_three_witnesses():
    town, routine = make_town(), make_routine()
    assign_traits(town.villagers, Random(0))
    crime = stage_crime(town, routine, Random(0), 1, "night", "case-1", tier="serious")
    crime.place, crime.culprit, crime.victim = "oak street", "v1", "v5"
    assert len(witness_memories(crime, town, routine, Random(0), Ids())) == 3


def test_a_mugging_victim_remembers_one_trait_of_the_mugger():
    town, routine = make_town(), make_routine()
    assign_traits(town.villagers, Random(0))
    crime = next(c for seed in range(200)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1", tier="serious")).template == "mug")
    m = victim_memory(crime, town, Random(0), Ids())
    assert (m.kind, m.holder, m.case) == ("memory", crime.victim, crime.id) and len(m.traits) == 1
    assert m.traits.items() <= town.looks(crime.culprit, 1).items()
    assert crime_title(crime, town) == f"The mugging of {town.name_of(crime.victim)}"
    said = f"Around {m.clock}, {at(crime.place)}, someone {describe(m.traits)} grabbed at me and took my {crime.item}."
    assert m.text == said
    more = recall_more(crime, m, town.looks(crime.culprit, 1))
    assert len(more.traits) == 2 and more.text.endswith(f"grabbed at me and took my {crime.item}.")


def test_the_goose_case_reads_well():
    town, routine = make_town(), make_routine({"v1": "dog park"})
    crime = next(c for seed in range(400)
                 if (c := stage_crime(town, routine, Random(seed), 1, "night", "case-1")).victim == "v1"
                 and c.template == "goose")
    assert crime.text == f"Someone made off with Dana Reyes's goose at the dog park {WHEN}."
    assert crime_title(crime, town) == "Dana Reyes's goose"


def test_the_practice_crime_still_reads_as_today():
    town = make_town()
    crime = Crime("case-1", "steal", "tote bag", "v5", "v1", "library", 1, "morning", 590, "rival",
                  f"Someone stole Dana Reyes's tote bag at the library {WHEN}.")
    assert CRIMES["steal"].news.format(did="stole", victim="Dana Reyes", item="tote bag", at="at the library",
                                       when=WHEN) == crime.text
    assert crime_title(crime, town) == "Dana Reyes's tote bag"


def test_crimes_move_away_from_organized_districts():
    town, routine = make_town(), make_routine()

    def elm_share(weight):
        crimes = [stage_crime(town, routine, Random(seed), 1, "night", "case-1", weight=weight) for seed in range(300)]
        return sum(c.place == "elm street" for c in crimes) / len(crimes)

    assert elm_share(lambda place: 0.25 if place == "elm street" else 1.0) < elm_share(None) / 2


def test_a_watch_also_steers_which_kind_of_crime_happens():
    """A crime that could only happen in the watched district is drawn less, not just placed elsewhere within it."""
    town = make_town()
    routine = StubRoutine({vid: {"morning": "cafe" if street == "elm street" else "gym"}
                           for vid, _, _, street in RESIDENTS})

    def cafe_share(weight):
        crimes = [stage_crime(town, routine, Random(seed), 1, "morning", "case-1", weight=weight) for seed in range(300)]
        return sum(c.place == "cafe" for c in crimes) / len(crimes)

    assert cafe_share(lambda place: 0.01 if place == "cafe" else 1.0) < 0.05 < cafe_share(None)


def test_every_district_has_somewhere_by_day_for_each_serious_crime_but_a_car_theft():
    """So a watch can push serious crime out of a district by day, not only at night."""
    by_day = [p for p in PLACES if p not in STREETS]
    for kind in ("rob", "mug"):
        for item in CRIMES[kind].items:
            assert {district_of(p) for p in ITEM_PLACES[item] if p in by_day} == set(STREETS), (kind, item)
