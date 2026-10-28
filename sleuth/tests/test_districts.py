import json

import pytest

from sleuth.case import Crime
from sleuth.config import Config
from sleuth.districts import (
    FORMED, HIT, PLACE_DISTRICT, RELIEF, TOLD, WATCH_SIZE, WOUND_DOWN, Districts, Watch, district_of,
)
from sleuth.models import Villager
from sleuth.tests.test_cases import kinds, make_cases, shared, tick
from sleuth.town import PLACES, STREETS


def crime(place="cafe", tier="petty"):
    return Crime("case-1", "steal", "bike", "v5", "v1", place, 1, "night", 1400, "rival", "Someone stole a bike.",
                 tier=tier)


def test_every_place_and_resident_belongs_to_one_district():
    assert set(PLACE_DISTRICT) == set(PLACES) and set(PLACE_DISTRICT.values()) == set(STREETS)
    assert district_of("gym") == "oak street" and district_of("maple street") == "maple street"


def test_a_crime_raises_crime_and_fear_in_its_district():
    districts = Districts(Config())
    districts.on_crime(crime("bar", "serious"))
    elm = districts.by_street["elm street"]
    assert (elm.crime, elm.fear) == (HIT["serious"], HIT["serious"])
    assert districts.by_street["oak street"].crime == 0.0
    for _ in range(3):
        districts.on_crime(crime("bar", "major"))
    assert (elm.crime, elm.fear) == (1.0, 1.0)


def test_district_state_decays_each_part_of_the_day():
    districts = Districts(Config(district_crime_decay=0.1, district_fear_decay=0.05))
    districts.on_crime(crime("gym"))
    oak = districts.by_street["oak street"]
    districts.tick(morning=False)
    assert oak.crime == pytest.approx(0.15) and oak.fear == pytest.approx(0.2) and oak.was == [0.0, 0.0]
    districts.tick(morning=True)
    assert oak.was == [pytest.approx(0.05), pytest.approx(0.15)]
    for _ in range(10):
        districts.tick(morning=False)
    assert (oak.crime, oak.fear) == (0.0, 0.0)


def test_an_exposure_lowers_crime_in_the_district():
    districts = Districts(Config())
    districts.on_crime(crime("grocery", "major"))
    districts.on_exposed(crime("grocery", "major"))
    maple = districts.by_street["maple street"]
    assert maple.crime == pytest.approx(HIT["major"] - RELIEF[0]) and maple.fear == pytest.approx(HIT["major"] - RELIEF[1])
    assert maple.exposures == 1
    districts.on_exposed(crime("grocery"))
    districts.on_exposed(crime("grocery"))
    districts.on_exposed(crime("grocery"))
    districts.on_exposed(crime("grocery"))
    assert maple.crime == 0.0 and maple.exposures == 5


def test_districts_round_trip():
    districts = Districts(Config())
    districts.on_crime(crime("library"))
    districts.on_exposed(crime("library"))
    districts.tick(morning=True)
    districts.by_street["oak street"].watch = Watch("Oak Street Group Chat", "v5", ["v5", "v6"], 2.25)
    fresh = Districts(Config())
    fresh.restore(json.loads(json.dumps(districts.to_state())))
    assert fresh.by_street == districts.by_street


@pytest.mark.asyncio
async def test_opening_a_case_and_holding_it_move_its_district():
    cases, engine, _ = make_cases()
    cases.districts = Districts(Config())
    await tick(cases, engine)
    case = shared(cases)
    district = cases.districts.by_street[district_of(case.crime.place)]
    assert district.crime == HIT["petty"]
    await cases.on_held(engine, case, "p-1")
    assert district.crime == pytest.approx(HIT["petty"] - RELIEF[0]) and district.exposures == 1


class NoModels:
    def __getattr__(self, name):
        raise AssertionError(f"a model was used: {name}")


def watched(fear=0.5, exposures=1):
    cases, engine, town = make_cases()
    cases.districts = Districts(Config())
    elm = cases.districts.by_street["elm street"]
    elm.fear, elm.crime, elm.exposures = fear, 0.3, exposures
    return cases, engine, town, elm


@pytest.mark.asyncio
async def test_fear_and_an_exposure_organize_a_watch_announced_on_the_app():
    cases, engine, town = make_cases()
    cases.districts = Districts(Config())
    await tick(cases, engine)
    case = shared(cases)
    district = cases.districts.by_street[district_of(case.crime.place)]
    district.fear = 0.9
    await cases.on_held(engine, case, "p-1")
    watch = district.watch
    assert watch is not None and district.exposures == 0
    founder = town.get(watch.founder)
    if town.get(case.crime.victim).home == district_of(case.crime.place):
        assert watch.founder == case.crime.victim
    assert watch.members[0] == watch.founder and all(town.get(m).home == founder.home for m in watch.members)
    street = founder.home.title()
    assert any(e.data["text"] == FORMED.format(street=street, first=founder.name.split()[0]) and e.data["app"]
               for e in kinds(engine, "post"))


@pytest.mark.asyncio
async def test_watch_members_hear_of_it_through_their_minds():
    cases, engine, town, elm = watched()
    for i in range(9, 15):
        town.add(Villager(f"v{i}", f"Extra {i}", "clerk", "calm", "", [], {}, {}, "elm street", f"h{i}"), "elm street")
    town.get("v1").warmth.update({"v9": 0.9, "v10": 0.8, "v11": 0.7, "v12": 0.6, "v3": -0.5})
    await cases.rally(engine, "elm street", "v1")
    assert elm.watch.founder == "v1" and len(elm.watch.members) == WATCH_SIZE
    assert elm.watch.members[:5] == ["v1", "v9", "v10", "v11", "v12"] and "v3" not in elm.watch.members
    [(told, listeners, _)] = engine.delivered
    assert told.speaker == "v1" and told.text == TOLD.format(name=elm.watch.name, street="Elm Street")
    assert listeners == elm.watch.members[1:] and len(listeners) <= WATCH_SIZE - 1


@pytest.mark.asyncio
async def test_a_watch_never_forms_without_an_exposure():
    cases, engine, _, elm = watched(fear=0.9, exposures=0)
    await cases.rally(engine, "elm street", None)
    assert elm.watch is None and not engine.delivered and not kinds(engine, "post")
    cases, engine, _, elm = watched(fear=0.3)
    await cases.rally(engine, "elm street", None)
    assert elm.watch is None


@pytest.mark.asyncio
async def test_forming_a_watch_makes_no_model_calls():
    cases, engine, _, elm = watched()
    engine.writer = engine.jev = NoModels()
    await cases.rally(engine, "elm street", "v9")
    assert elm.watch is not None and elm.watch.founder in ("v1", "v2", "v3", "v4")
    assert sum(len(listeners) for _, listeners, _ in engine.delivered) <= WATCH_SIZE


@pytest.mark.asyncio
async def test_a_watch_winds_down_once_crime_and_fear_fade():
    cases, engine, _, elm = watched()
    await cases.rally(engine, "elm street", "v1")
    name = elm.watch.name
    assert cases.districts.organized("cafe") and not cases.districts.organized("gym")
    elm.crime, elm.fear = 0.04, 0.06
    assert cases.districts.wind_down() == []
    elm.fear = 0.04
    await tick(cases, engine)
    assert elm.watch is None and not cases.districts.organized("cafe")
    assert any(e.data["text"] == WOUND_DOWN.format(name=name, street="Elm Street") for e in kinds(engine, "post"))
