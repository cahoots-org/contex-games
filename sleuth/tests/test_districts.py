import json

import pytest

from sleuth.case import Crime, crime_title
from sleuth.cases import BREATHES, ON_EDGE, THANKS
from sleuth.config import Config
from sleuth.districts import (
    FORMED, HIT, PLACE_DISTRICT, RELIEF, TOLD, WATCH_SIZE, WOUND_DOWN, Districts, Watch, district_of,
)
from sleuth.engine import Engine
from sleuth.lineage import Ids, Lineage
from sleuth.models import Villager
from sleuth.offenders import Offender
from sleuth.tests.helpers import PID
from sleuth.tests.test_cases import kinds, make_cases, shared, tick
from sleuth.tests.test_player import cite, interviewing, memory_of
from sleuth.town import PLACES, STREETS, Town


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


def test_a_district_s_mood_follows_its_fear_and_its_watch():
    districts = Districts(Config())
    elm = districts.by_street["elm street"]
    assert districts.mood("elm street") is None
    elm.fear = 0.3
    assert districts.mood("elm street") == "on edge"
    elm.fear, elm.watch = 0.6, Watch("Elm Street Group Chat", "v1", ["v1"], 1.0)
    assert districts.mood("elm street") == "rattled, but the Elm Street Group Chat is on it"


def test_only_districts_without_a_watch_are_neglected():
    districts = Districts(Config())
    for d in districts.by_street.values():
        d.crime = d.fear = 0.5
    districts.by_street["oak street"].fear = 0.3
    districts.by_street["maple street"].watch = Watch("Maple Street Group Chat", "v1", ["v1"], 1.0)
    assert districts.neglected() == ["elm street"]


def neglected(**config):
    cases, engine, town = make_cases(**config)
    cases.districts = Districts(cases.config)
    elm = cases.districts.by_street["elm street"]
    elm.crime = elm.fear = 0.9
    return cases, engine, town, elm


ELM = {"v1", "v2", "v3", "v4"}


@pytest.mark.asyncio
async def test_a_neglected_district_can_turn_a_resident_into_an_offender():
    cases, engine, _, _ = neglected(turn_chance=1.0, min_offenders=0)
    cases.offenders.exposed["v5"] = "stole Dana Reyes's bike"
    await cases.on_tick(engine, 2, "morning", {})
    assert len(cases.offenders.active) == 1 and set(cases.offenders.active) <= ELM
    await cases.on_tick(engine, 2, "afternoon", {})
    assert len(cases.offenders.active) == 1


@pytest.mark.asyncio
async def test_organized_districts_never_produce_offenders():
    cases, engine, _, elm = neglected(turn_chance=1.0)
    elm.watch = Watch("Elm Street Group Chat", "v1", ["v1"], 1.0)
    cases.offenders.active["v5"] = Offender()
    for day in range(2, 202):
        await cases.on_tick(engine, day, "morning", {})
        elm.crime = elm.fear = 0.9
        assert not set(cases.offenders.active) & ELM


@pytest.mark.asyncio
async def test_the_floor_refills_from_unorganized_districts_only():
    cases, engine, _, elm = neglected(min_offenders=3, turn_chance=0.0)
    elm.watch = Watch("Elm Street Group Chat", "v1", ["v1"], 1.0)
    cases.offenders.exposed["v8"] = "stole Dana Reyes's bike"
    await cases.on_tick(engine, 2, "morning", {})
    assert set(cases.offenders.active) == {"v5", "v6", "v7"}


def test_the_engine_gives_each_resident_their_own_street_s_mood():
    districts = Districts(Config())
    districts.by_street["elm street"].fear = 0.3
    engine = Engine(Config(), Town(), None, None, None, Lineage(), Ids(), None, districts=districts)
    elm = Villager("v1", "Ada", "baker", "calm", "", [], {}, home="elm street")
    oak = Villager("v2", "Bo", "baker", "calm", "", [], {}, home="oak street")
    assert engine.mood(elm) == "on edge" and engine.mood(oak) is None
    assert Engine(Config(), Town(), None, None, None, Lineage(), Ids(), None).mood(elm) is None


def test_district_json_carries_levels_not_internals():
    _, _, town = make_cases()
    districts = Districts(Config())
    elm = districts.by_street["elm street"]
    elm.crime, elm.fear, elm.was, elm.exposures = 0.2, 0.5, [0.0, 0.6], 2
    elm.watch = Watch("Elm Street Group Chat", "v1", ["v1", "v2"], 1.5)
    levels = districts.levels(town)
    assert [d["street"] for d in levels] == list(STREETS)
    assert levels[0] == {"street": "elm street", "name": "Elm Street", "crime": 1, "fear": 2, "crime_trend": 1,
                         "fear_trend": -1, "watch": "Elm Street Group Chat", "founder": "Dana Reyes"}
    assert levels[1] == {"street": "oak street", "name": "Oak Street", "crime": 0, "fear": 0, "crime_trend": 0,
                         "fear_trend": 0, "watch": None, "founder": None}
    elm.crime = 0.04
    assert districts.levels(town)[0]["crime_trend"] == 0
    assert not [v for d in json.loads(json.dumps(levels)) for v in d.values() if isinstance(v, float)]


def district_events(engine):
    return [e for e in engine.feed.recent if e.kind == "districts"]


@pytest.mark.asyncio
async def test_a_crime_that_rattles_a_street_is_noticed_on_the_app():
    cases, engine, town = make_cases()
    cases.districts = Districts(cases.config)
    await tick(cases, engine)
    case = shared(cases)
    street = district_of(case.crime.place)
    title = crime_title(case.crime, town)
    assert [e.data["text"] for e in kinds(engine, "post") if e.data["text"].endswith(f"after {title}.")] == [
        ON_EDGE.format(street=street.title(), title=title)]
    levels = district_events(engine)[-1].data["districts"]
    assert next(d for d in levels if d["street"] == street)["fear"] == 1
    calm, _, _ = make_cases()
    calm.districts = Districts(calm.config)
    for d in calm.districts.by_street.values():
        d.fear = 1.0
    calm_engine = make_cases()[1]
    await tick(calm, calm_engine)
    assert not [e for e in kinds(calm_engine, "post") if "on edge" in e.data["text"]]


@pytest.mark.asyncio
async def test_a_first_held_case_changes_the_town_at_once():
    player, file, engine, _ = interviewing()
    cases = engine.cases
    cases.districts = Districts(cases.config)
    elm = cases.districts.by_street["elm street"]
    elm.crime, elm.fear = 0.6, 0.6
    before = elm.crime
    cases.now = 2.0
    ids = cite(player, file, memory_of(file, player.ids))
    await player.publish("v3", ids)
    assert player.person("v3")["known_for"] == "stole Dana Reyes's bike"
    assert engine.reputation.get("v1", PID) > 0
    posts = [e.data["text"] for e in player.feed.recent if e.kind == "post"]
    assert THANKS.format(item="bike") in posts and BREATHES.format(street="Elm Street", name="Fay Okafor") in posts
    [after] = [d for d in [e for e in player.feed.recent if e.kind == "districts"][-1].data["districts"]
               if d["street"] == "elm street"]
    assert after["crime"] <= round(before * 3)
    assert elm.watch is not None and after["watch"] == elm.watch.name


@pytest.mark.asyncio
async def test_a_case_gone_cold_calms_nothing_and_never_earns_a_watch(monkeypatch):
    cases, engine, _ = make_cases()
    cases.districts = Districts(cases.config)
    await tick(cases, engine)
    case = shared(cases)
    district = cases.districts.by_street[district_of(case.crime.place)]
    district.crime, district.fear, district.exposures = 0.6, 0.9, 0

    async def nothing(engine, now=None):
        pass

    monkeypatch.setattr(cases, "ensure", nothing)
    await tick(cases, engine, day=5, phase="afternoon")
    assert case.state == "closed" and case.crime.culprit in cases.offenders.exposed
    assert (district.crime, district.fear, district.exposures, district.watch) == (0.6, 0.9, 0, None)
    assert not [e for e in kinds(engine, "post") if "starting a watch" in e.data["text"]]
