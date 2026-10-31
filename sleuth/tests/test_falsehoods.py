from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth import falsehoods
from sleuth.alibi import accomplice_word
from sleuth.case import NO_WITNESS, Crime, Record, minute_of, motives, record_json, suspects
from sleuth.falsehoods import LEFT_BEFORE, cover_place
from sleuth.tests.test_case import feuding, make_routine
from sleuth.tests.test_cases import make_cases, podcaster, tick, tiered
from sleuth.tests.test_tutorial import case, practice
from sleuth.traits import fits


# Who is out at a logging place at night rather than home: a crowd at the bar, so a mistake has bystanders left.
NIGHT_OUT = {"v1": "bar", "v2": "bar", "v4": "bar", "v6": "bar", "v7": "bar", "v8": "gym"}


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


@pytest.fixture
def witnessed(monkeypatch):
    """Every serious case truly witnessed, so mistakes can be staged."""
    monkeypatch.setitem(NO_WITNESS, "serious", 0.0)


@pytest.mark.asyncio
async def test_every_fake_has_a_disproof_on_file(witnessed):
    staged = await serious_cases() + await serious_cases(night=NIGHT_OUT)
    staged_fakes = [r for f, _ in staged for r in fakes(f)]
    assert {r.kind for r in staged_fakes} == {"memory", "clue"}
    for file, town in staged:
        crime = file.crime
        for fake in fakes(file):
            disproof = file.records[fake.disproof]
            assert disproof.sound and disproof.kind in ("clue", "clip", "log", "memory")
            if fake.kind == "memory":
                assert disproof.place == crime.place and not fits(fake.traits, disproof.traits)
            else:
                assert fake.kind == "clue" and disproof.kind == "log" and disproof.place == file.crime.place
                assert fits(fake.traits, town.sighting(disproof.who, crime.day))
                assert not fits(fake.traits, town.sighting(crime.culprit, crime.day))


@pytest.mark.asyncio
async def test_a_mistaken_witness_is_a_bystander_in_a_case_a_bystander_truly_witnessed(witnessed):
    mistakes = 0
    for night in (None, NIGHT_OUT):
        routine = make_routine(night)
        for file, _ in await serious_cases(night=night):
            crime = file.crime
            memories = [r for r in file.records.values() if r.kind == "memory" and r.holder != crime.victim]
            at_scene = {m.holder for m in memories if routine.place(m.holder, crime.phase) == crime.place}
            for fake in [m for m in memories if not m.sound]:
                mistakes += 1
                assert fake.holder in at_scene and any(m.sound and m.holder in at_scene for m in memories)
    assert mistakes


@pytest.mark.asyncio
async def test_fakes_never_change_who_the_true_evidence_points_to(witnessed):
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
async def test_an_aimed_fake_fits_an_innocent_with_a_motive_when_there_is_one(monkeypatch, witnessed):
    monkeypatch.setattr(falsehoods, "AIMED_CHANCE", 1.0)
    aimed = 0
    for file, town in await serious_cases(feud=True, night=NIGHT_OUT):
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
    stray = Record("r-99", "", "clue", "elm street", "", "A thread.", sound=False, disproof="r-404")
    tried = []
    monkeypatch.setattr(cases_mod, "stage_false", lambda *a, **k: tried.append(a) or [stray])
    for seed in range(20):
        cases, engine, _ = make_cases()
        cases.rng = Random(seed)
        crime = Crime(f"case-{seed}", "mug", "wallet", "v5", "v1", "elm street", 1, "night", 1400, "opportunity", "",
                      tier="serious")
        assert not await cases._open(engine, crime, set())
        assert cases.files == {} and engine.delivered == []
    assert tried


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
        place = cover_place(file.whereabouts, town.get(file.accomplice))
        log = file.records[disproof]
        assert not sound and log.sound and log.kind == "log" and log.place == place and log.who != file.crime.culprit
    assert covered


@pytest.mark.asyncio
async def test_an_accomplice_dropped_for_want_of_a_disproof_is_not_kept_away(monkeypatch):
    chosen, barred = [], []
    accomplice, pick = cases_mod.Cases._accomplice, cases_mod.pick_liar

    def choose(self, *args):
        chosen.append(accomplice(self, *args))
        return chosen[-1]

    def picking(crime, whereabouts, town, routine, rng, bar, *args):
        barred.append(set(bar))
        return pick(crime, whereabouts, town, routine, rng, bar, *args)

    monkeypatch.setattr(cases_mod, "LIAR_CHANCE", 1.0)
    monkeypatch.setattr(cases_mod, "cover_disproof", lambda *a: None)
    monkeypatch.setattr(cases_mod.Cases, "_accomplice", choose)
    monkeypatch.setattr(cases_mod, "pick_liar", picking)
    for seed in range(20):
        cases, engine, town = make_cases(accomplice_chance=1.0)
        cases.rng = Random(seed)
        cases.routine = make_routine({"v7": "gym"})
        town.get("v5").warmth["v7"] = 0.7
        crime = Crime(f"case-{seed}", "mug", "wallet", "v5", "v1", "elm street", 1, "night", 1400, "opportunity", "",
                      tier="serious")
        if await cases._open(engine, crime, set()):
            assert cases.files[crime.id].accomplice is None
            assert chosen[-1] == "v7" and "v7" not in barred[-1]
    assert barred


def test_record_json_never_says_whether_a_record_is_sound():
    cases, _, town = make_cases()
    r = Record("r-1", "case-1", "clue", "elm street", "", "A thread.", sound=False, disproof="r-2")
    assert not {"sound", "disproof"} & set(record_json(r, town))
