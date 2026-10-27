from types import SimpleNamespace

import pytest

from sleuth.case import ITEM_PLACES, TEMPLATES, suspects
from sleuth.config import Config
from sleuth.episode import holds
from sleuth.lineage import Ids
from sleuth.player import acquainted
from sleuth.players import Players
from sleuth.town import PUBLIC_PLACES, STREETS
from sleuth.traits import TRAITS
from sleuth.tutorial import Practice


def practice(saved=None, ids=None):
    engine = SimpleNamespace(jev="jev", players=Players())
    return Practice(engine, ids or Ids(), Config(), "p-1", saved)


def case(p):
    [file] = p.cases.files.values()
    return file


def kinds(file, *wanted):
    return [r for r in file.records.values() if r.kind in wanted]


def test_the_practice_case_is_open_and_owned_by_its_player():
    p = practice()
    file = case(p)
    assert file.state == "open" and file.crime.owner == "p-1"
    assert p.cases.private("p-1") is file and p.cases.for_player("p-1") is file
    assert p.jev == "jev"


def test_only_the_witness_and_the_clue_together_narrow_it_to_the_culprit():
    p = practice()
    file = case(p)
    crime, [memory], [clue] = file.crime, kinds(file, "memory"), kinds(file, "clue")
    assert suspects(crime, [memory], p.town) == {"t4", "t5"}
    assert suspects(crime, [clue], p.town) == {"t5", "t6"}
    assert suspects(crime, list(file.records.values()), p.town) == {crime.culprit}
    assert holds(crime, crime.culprit, p.town.looks(crime.culprit, 1), [memory, clue])
    assert not holds(crime, "t4", p.town.looks("t4", 1), [memory])


def test_cal_is_the_only_one_the_victim_knows_who_matches_the_sighting():
    p = practice()
    file = case(p)
    [memory] = kinds(file, "memory")
    victim = p.town.get(file.crime.victim)
    known = [v.id for v in p.town.villagers if acquainted(victim, v)
             and memory.traits.items() <= p.town.looks(v.id, 1).items()]
    assert known == [file.crime.culprit] == ["t5"]


def test_the_practice_town_keeps_the_town_s_rules():
    p = practice()
    file, villagers = case(p), p.town.villagers
    assert len(villagers) == 6 and all(v.home in STREETS for v in villagers)
    assert {len([v for v in villagers if v.household == h]) for h in {v.household for v in villagers}} == {2}
    looks = [p.town.looks(v.id, 1) for v in villagers]
    assert all(set(lk) == set(TRAITS) and all(lk[c] in TRAITS[c] for c in TRAITS) for lk in looks)
    assert all(p.routine.place(v.id, ph) in PUBLIC_PLACES for v in villagers for ph in ("morning", "evening"))
    crime = file.crime
    assert p.town.get(crime.culprit).household != p.town.get(crime.victim).household
    assert crime.template in TEMPLATES and crime.place in ITEM_PLACES[crime.item]
    assert p.routine.place(crime.victim, crime.phase) == crime.place
    [memory] = kinds(file, "memory")
    assert p.routine.place(memory.holder, crime.phase) == crime.place
    assert p.town.get(crime.victim).warmth[crime.culprit] < 0


def test_practice_residents_own_three_outfits_and_wear_the_first_on_day_one():
    p = practice()
    assert all(len(set(v.wardrobe)) == 3 and set(v.traits) == {"height", "hair", "car"} for v in p.town.villagers)
    assert all(p.town.outfit(v.id, 1) == v.wardrobe[0] for v in p.town.villagers)
    assert p.town.outfit("t5", 1) == p.town.outfit("t6", 1) == "green raincoat"


def test_the_clock_stands_still():
    p = practice()
    assert (p.game.day, p.game.phase) == (1, "afternoon")
    p.game.phase_started -= 3600
    assert p.game.clock()["fraction"] == pytest.approx(0.25 + 0.3 / 4, abs=1e-4)


def test_each_practice_town_is_its_own_and_takes_fresh_ids():
    ids = Ids()
    ids.ensure_past("r", 40)
    a, b = practice(ids=ids), practice(ids=ids)
    a.town.get("t1").warmth["t5"] = 1.0
    assert b.town.get("t1").warmth["t5"] < 0
    assert not set(case(a).records) & set(case(b).records) and min(case(a).records) > "r-40"


def test_a_saved_practice_case_comes_back():
    a = practice()
    case(a).published.append("p-1")
    b = practice(saved=a.cases.to_state())
    assert case(b) == case(a)


@pytest.mark.asyncio
async def test_nobody_in_the_practice_town_hears_or_is_pressed():
    p = practice()
    await p.press(case(p), "p-1")
    assert await p.recall_heard("t1", "anything") == []
