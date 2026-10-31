from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth import falsehoods
from sleuth.alibi import accomplice_word
from sleuth.case import Crime, Record, minute_of, motives, record_json, suspects
from sleuth.falsehoods import LEFT_BEFORE
from sleuth.tests.test_case import feuding, make_routine
from sleuth.tests.test_cases import make_cases, podcaster, tick, tiered
from sleuth.tests.test_tutorial import case, practice
from sleuth.traits import fits


# Who is out at a logging place at night rather than home.
NIGHT_OUT = {"v2": "bar", "v4": "gym", "v6": "gym", "v7": "bar", "v8": "gym"}


async def serious_cases(seeds=range(100), feud=False, night=None, **config):
    """The serious case opened on each seed, with its town; night says who is out at night."""
    opened = []
    for seed in seeds:
        cases, engine, town = make_cases(offenders=8, **config)
        cases.routine = make_routine(night)
        if feud:
            feuding(town)
        cases.rng = Random(seed)
        engine.players.add(podcaster("serious"))
        tiered(cases, "petty", opened=2.0)
        await tick(cases, engine)
        opened += [(f, town) for f in cases.open_shared("serious")]
    return opened


def fakes(file):
    return [r for r in file.records.values() if not r.sound]


@pytest.mark.asyncio
async def test_every_fake_has_a_disproof_on_file():
    staged = await serious_cases() + await serious_cases(night=NIGHT_OUT)
    assert len(staged) > 50 and all(fakes(f) for f, _ in staged)
    for file, town in staged:
        for fake in fakes(file):
            disproof = file.records[fake.disproof]
            assert disproof.sound and disproof.kind in ("clue", "clip", "log", "memory")
            if fake.kind == "memory":
                assert disproof.place == file.crime.place and not fits(fake.traits, disproof.traits)
            else:
                assert fake.kind == "clue" and disproof.kind == "log" and disproof.place == file.crime.place
                assert fits(fake.traits, town.sighting(disproof.who, file.crime.day))
                assert not fits(fake.traits, town.sighting(file.crime.culprit, file.crime.day))


@pytest.mark.asyncio
async def test_fakes_never_change_who_the_true_evidence_points_to():
    for file, town in await serious_cases() + await serious_cases(night=NIGHT_OUT):
        sound = [r for r in file.records.values() if r.sound]
        assert suspects(file.crime, sound, town) == {file.crime.culprit}


@pytest.mark.asyncio
async def test_a_leftover_was_left_before_the_crime():
    leftovers = [(fake, f) for f, _ in await serious_cases(night=NIGHT_OUT) for fake in fakes(f) if fake.kind == "clue"]
    assert leftovers
    for fake, file in leftovers:
        log = file.records[fake.disproof]
        assert minute_of(log.clock, file.crime.phase) <= file.crime.minute - LEFT_BEFORE
        assert log.who not in (file.crime.culprit, file.crime.victim)


@pytest.mark.asyncio
async def test_an_aimed_fake_fits_an_innocent_with_a_motive_when_there_is_one(monkeypatch):
    monkeypatch.setattr(falsehoods, "AIMED_CHANCE", 1.0)
    aimed = 0
    for file, town in await serious_cases(feud=True):
        crime = file.crime
        culprit = town.sighting(crime.culprit, crime.day)
        for fake in fakes(file):
            if fake.kind != "memory":
                continue
            [(category, value)] = fake.traits.items()
            decoys = [m for m in motives(town, crime.victim) if m != crime.culprit
                      and town.sighting(m, crime.day).get(category) not in (None, culprit[category])]
            if decoys:
                aimed += 1
                assert any(value == town.sighting(m, crime.day)[category] for m in decoys)
    assert aimed


@pytest.mark.asyncio
async def test_a_case_that_cannot_disprove_its_fakes_does_not_open(monkeypatch):
    tried = []
    monkeypatch.setattr(cases_mod, "stage_false", lambda *a, **k: tried.append(a[-1]))
    for seed in range(20):
        cases, engine, _ = make_cases()
        cases.rng = Random(seed)
        crime = Crime(f"case-{seed}", "mug", "wallet", "v5", "v1", "elm street", 1, "night", 1400, "opportunity", "",
                      tier="serious")
        assert not await cases._open(engine, crime, set())
        assert cases.files == {} and engine.delivered == []
    assert tried and all(tried)


def test_the_tutorial_case_has_no_fakes():
    assert all(r.sound and r.disproof is None for r in case(practice()).records.values())


@pytest.mark.asyncio
async def test_an_accomplice_s_word_is_disproved_by_a_record_on_file():
    covered = 0
    for file, town in await serious_cases(night=NIGHT_OUT, accomplice_chance=1.0):
        if file.accomplice is None:
            continue
        covered += 1
        text, sound, disproof = accomplice_word(file, town.get(file.accomplice), town.get(file.crime.culprit))
        place = (file.whereabouts.get(file.accomplice) or [town.get(file.accomplice).home])[0]
        log = file.records[disproof]
        assert not sound and log.sound and log.kind == "log" and log.place == place and log.who != file.crime.culprit
    assert covered


def test_record_json_never_says_whether_a_record_is_sound():
    cases, _, town = make_cases()
    r = Record("r-1", "case-1", "clue", "elm street", "", "A thread.", sound=False, disproof="r-2")
    assert not {"sound", "disproof"} & set(record_json(r, town))
