import json

import pytest

from sleuth.case import Crime
from sleuth.config import Config
from sleuth.districts import HIT, PLACE_DISTRICT, RELIEF, Districts, district_of
from sleuth.tests.test_cases import make_cases, shared, tick
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
