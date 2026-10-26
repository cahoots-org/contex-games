import json
from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth.cases import Cases
from sleuth.config import Config
from sleuth.feed import Feed
from sleuth.lineage import Ids, Lineage
from sleuth.tests.test_case import make_routine, make_town
from sleuth.traits import assign_traits


class FakeEngine:
    def __init__(self, town):
        self.lines = []
        self.feed = Feed(Lineage(), town, out=self.lines.append)
        self.delivered = []

    async def deliver(self, utterance, listener_ids, addressed=False):
        self.delivered.append((utterance, listener_ids, addressed))


def make_cases(**config):
    town = make_town()
    assign_traits(town.villagers, Random(0))
    cases = Cases(Config(**config), town, make_routine(), Random(1), Ids())
    return cases, FakeEngine(town), town


async def tick(cases, engine, day=1, phase="night", playing=True):
    await cases.on_tick(engine, day, phase, {}, playing)


def kinds(engine, kind):
    return [e for e in engine.feed.recent if e.kind == kind]


@pytest.mark.asyncio
async def test_tick_stages_a_crime_only_when_none_is_open():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    assert case.state == "setup" and cases.shared() is case
    await tick(cases, engine, day=2)
    assert list(cases.files.values()) == [case] and case.state == "open"


@pytest.mark.asyncio
async def test_culprit_is_moved_to_the_crime_place():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    assert town.place_of(case.crime.culprit) == case.crime.place
    assert cases.busy() == {case.crime.culprit} and cases.culprit_case(case.crime.culprit) is case


@pytest.mark.asyncio
async def test_witness_memory_is_delivered_to_the_witness_alone_and_rooted():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    assert not engine.delivered
    await tick(cases, engine, day=2)
    [case] = cases.files.values()
    memory = next(r for r in case.records.values() if r.kind == "memory")
    witness = memory.holder
    u, ids, addressed = engine.delivered[0]
    assert ids == [witness] and addressed and cases.root_kind(u.id)[1] == "memory"
    assert u.id == memory.utterance and u.text == memory.text and u.verb == "saw" and u.place == case.crime.place


@pytest.mark.asyncio
async def test_news_breaks_on_the_next_tick_after_the_solvability_check():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    assert not kinds(engine, "case")
    await tick(cases, engine, day=2)
    [event] = kinds(engine, "case")
    [case] = cases.files.values()
    assert event.data["case"] == {"id": case.crime.id, "text": case.crime.text, "place": case.crime.place,
                                  "phase": "night", "day": 1, "state": "open", "private": False}
    assert case.opened == 2.75 and cases.for_player("p-1") is case
    news, listeners, _ = next(d for d in engine.delivered if cases.root_kind(d[0].id)[1] == "news")
    victim = town.get(case.crime.victim)
    assert news.speaker_name == "The neighborhood app" and news.text == case.crime.text and news.verb == "posted"
    assert victim.id in listeners and {v.id for v in town.villagers if v.household == victim.household} <= set(listeners)
    assert {v.id for v in town.present(case.crime.place)} <= set(listeners)
    [post] = kinds(engine, "post")
    assert post.data == {"case_id": case.crime.id, "speaker": "The neighborhood app", "text": case.crime.text}


@pytest.mark.asyncio
async def test_unsolvable_case_is_dropped_without_news(monkeypatch):
    monkeypatch.setattr(cases_mod, "make_solvable", lambda *a: None)
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [first] = cases.files
    await tick(cases, engine, day=2)
    assert not cases.files and not kinds(engine, "case") and not engine.delivered
    assert cases.last_closed == 2.75
    await tick(cases, engine, day=3)
    assert first not in cases.files and len(cases.files) == 1


@pytest.mark.asyncio
async def test_a_case_that_fails_to_finish_is_dropped_and_crimes_go_on(monkeypatch, caplog):
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [first] = cases.files

    def broken(*a):
        raise KeyError("v1")

    monkeypatch.setattr(cases_mod, "make_solvable", broken)
    await tick(cases, engine, day=2)
    assert not cases.files and not cases.busy() and "case-1" in caplog.text
    monkeypatch.undo()
    await tick(cases, engine, day=3)
    [second] = cases.files
    assert second != first


@pytest.mark.asyncio
async def test_case_goes_cold_after_case_days():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    await tick(cases, engine, day=2)
    [case] = cases.files.values()
    await tick(cases, engine, day=5, phase="afternoon", playing=False)
    assert case.state == "open"
    await tick(cases, engine, day=5, playing=False)
    assert case.state == "closed" and cases.last_closed == 5.75 and cases.for_player("p-1") is None
    [closed] = kinds(engine, "case_closed")
    assert closed.data["case_id"] == case.crime.id and "The case went cold." in engine.lines


@pytest.mark.asyncio
async def test_no_crime_is_staged_while_nobody_plays():
    cases, engine, _ = make_cases()
    await tick(cases, engine, playing=False)
    assert not cases.files
    await tick(cases, engine, day=2)
    await tick(cases, engine, day=3, playing=False)
    assert [c.state for c in cases.files.values()] == ["open"]


@pytest.mark.asyncio
async def test_next_crime_waits_crime_every_days_after_a_close():
    cases, engine, _ = make_cases(case_days=0.25)
    await tick(cases, engine)
    await tick(cases, engine, day=2)
    await tick(cases, engine, day=3, phase="morning")
    assert cases.last_closed == 3.0
    await tick(cases, engine, day=3)
    assert len(cases.files) == 1
    await tick(cases, engine, day=4)
    assert len(cases.files) == 2


@pytest.mark.asyncio
async def test_cases_round_trip_through_state():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    await tick(cases, engine, day=2)
    await tick(cases, engine, day=3)
    fresh = Cases(Config(), town, make_routine(), Random(1), Ids())
    fresh.restore(json.loads(json.dumps(cases.to_state())))
    assert fresh.files == cases.files and fresh.last_closed == cases.last_closed
    assert fresh.to_state() == cases.to_state()
