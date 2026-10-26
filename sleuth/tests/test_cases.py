import json
from dataclasses import replace
from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth.alibi import claim
from sleuth.case import WHEN, Crime, points_at, suspects, told
from sleuth.cases import CaseFile, Cases, case_json
from sleuth.config import Config
from sleuth.feed import Feed
from sleuth.lineage import Ids, Lineage
from sleuth.players import Players
from sleuth.tests.test_case import make_routine, make_town
from sleuth.traits import assign_traits


class FakeEngine:
    def __init__(self, town):
        self.lines = []
        self.feed = Feed(Lineage(), town, out=self.lines.append)
        self.delivered = []
        self.players = Players()

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
    said = told(case.crime.text, case.crime, 2)
    assert said.endswith("last night.")
    assert event.data["case"] == {"id": case.crime.id, "text": said, "place": case.crime.place,
                                  "phase": "night", "day": 1, "state": "open", "private": False,
                                  "title": f"{town.name_of(case.crime.victim)}'s {case.crime.item}",
                                  "victim": case.crime.victim,
                                  "nearby": [v.id for v in town.villagers
                                             if v.id != case.crime.victim and v.home == case.crime.place]}
    assert case.opened == 2.75 and cases.for_player("p-1") is case
    news, listeners, _ = next(d for d in engine.delivered if cases.root_kind(d[0].id)[1] == "news")
    victim = town.get(case.crime.victim)
    assert news.speaker_name == "The neighborhood app" and news.text == said and news.verb == "posted"
    assert victim.id in listeners and {v.id for v in town.villagers if v.household == victim.household} <= set(listeners)
    assert {v.id for v in town.present(case.crime.place)} <= set(listeners)
    [post] = kinds(engine, "post")
    assert post.data == {"case_id": case.crime.id, "speaker": "The neighborhood app", "text": said,
                         "app": True}


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
    assert closed.data["case_id"] == case.crime.id
    assert f"The case went cold. It was {town_name(cases, case.crime.culprit)}." in engine.lines


def town_name(cases, vid):
    return cases.town.get(vid).name


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


def culprit_file(cases, culprit="v3", victim="v1", phase="night"):
    crime = Crime("case-1", "steal", "bike", culprit, victim, "elm street", 1, phase, 1400, "opportunity",
                  "Someone stole Dana Reyes's bike on Elm Street last night.")
    cases.files[crime.id] = CaseFile(crime, {}, "open")
    return cases.files[crime.id]


def test_case_lists_who_is_usually_at_the_scene_from_routine_alone():
    cases, _, town = make_cases()
    cases.routine = make_routine(night={"v4": "gym"})
    file = culprit_file(cases, culprit="v5")
    town.move("v5", "elm street")
    town.move("v2", "gym")
    file.whereabouts = {"v5": ["elm street"], "v3": ["gym"]}
    assert case_json(file, town, cases.routine)["nearby"] == ["v2", "v3"]
    assert case_json(file, town, None)["nearby"] == []


def test_alibi_claim_is_the_culprits_expected_place():
    cases, _, town = make_cases()
    cases.routine = make_routine(night={"v3": "gym"})
    file = culprit_file(cases)
    assert cases.alibi("v3") == f"I was at the gym {WHEN}, all night."
    assert file.alibi == ["gym"]
    assert cases.alibi("v2") is None


def test_blame_names_the_victims_rival_never_culprit_or_victim():
    cases, _, town = make_cases()
    culprit_file(cases)
    assert cases.blame("v3") == f"Hal Burke has never liked Dana. I'd ask where they were {WHEN}."


def test_blame_falls_back_to_the_culprits_coldest_tie_other_than_the_victim():
    cases, _, town = make_cases()
    culprit_file(cases, culprit="v5")
    assert cases.blame("v5") is None
    town.get("v5").warmth.update({"v7": 0.3, "v8": 0.5})
    assert cases.blame("v5") == f"Jo Tran has never liked Dana. I'd ask where they were {WHEN}."


def test_mark_cover_roots_the_line_in_the_culprits_case():
    cases, _, _ = make_cases()
    file = culprit_file(cases)
    cases.mark_cover("v3", "u-9")
    assert cases.root_kind("u-9") == (file, "cover")


def test_alibi_on_a_street_is_being_at_home():
    cases, _, _ = make_cases()
    culprit_file(cases)
    assert cases.alibi("v3") == f"I was at home on Elm Street {WHEN}, all night."


@pytest.mark.asyncio
async def test_the_crime_phase_log_is_kept_as_whereabouts_when_the_news_breaks():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    log = {"v2": ["elm street", "bar"]}
    await cases.on_tick(engine, 2, "night", log, True)
    [case] = cases.files.values()
    assert case.state == "open" and case.whereabouts == log


@pytest.mark.asyncio
async def test_a_player_off_the_practice_case_is_told_the_town_s_open_case():
    cases, engine, _ = make_cases()
    shared = culprit_file(cases)
    shared.crime.text = "Someone stole Dana Reyes's bike on Elm Street {when}."
    engine.feed.recent.clear()
    cases.brief(engine.feed, "p-1", 2)
    case, post = engine.feed.recent
    assert (case.kind, case.player, case.data["case"]["id"]) == ("case", "p-1", shared.crime.id)
    assert (post.kind, post.player, post.data["app"]) == ("post", "p-1", True)
    assert post.data["text"] == "Someone stole Dana Reyes's bike on Elm Street last night."
    shared.state = "closed"
    cases.brief(engine.feed, "p-1", 2)
    assert len(engine.feed.recent) == 2


def test_for_player_prefers_the_private_case():
    cases, _, _ = make_cases()
    shared = culprit_file(cases)
    private = CaseFile(replace(shared.crime, id="case-2", owner="p-1"), {}, "open")
    cases.files[private.crime.id] = private
    assert cases.for_player("p-1") is private and cases.for_player("p-2") is shared
    assert cases.private("p-1") is private and cases.private("p-2") is None
    assert cases.shared() is shared


@pytest.mark.asyncio
async def test_the_victim_is_told_what_they_found_when_the_case_opens():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    await tick(cases, engine, day=2)
    [case] = cases.files.values()
    [found] = [r for r in case.records.values() if r.kind == "discovery"]
    assert found.holder == case.crime.victim
    u, ids, addressed = next(d for d in engine.delivered if d[0].id == found.utterance)
    assert ids == [case.crime.victim] and addressed and cases.root_kind(u.id)[1] == "memory"
    assert u.text.startswith(f"Around {found.clock}, I found my {case.crime.item} ")
    assert town.name_of(case.crime.victim) not in u.text


@pytest.mark.asyncio
async def test_staged_cases_hold_clues_at_the_crime_place():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    case = cases.shared()
    clues = [r for r in case.records.values() if r.kind == "clue"]
    assert 1 <= len(clues) <= 2 and {r.place for r in clues} == {case.crime.place}


@pytest.mark.asyncio
async def test_cases_with_a_regular_culprit_still_open_solvable():
    regulars = 0
    for seed in range(40):
        cases, engine, town = make_cases()
        cases.rng = Random(seed)
        await tick(cases, engine)
        await tick(cases, engine, day=2)
        case = cases.shared()
        if case is None or cases.routine.place(case.crime.culprit, case.crime.phase) != case.crime.place:
            continue
        crime = case.crime
        regulars += 1
        records = list(case.records.values())
        traits = town.get(crime.culprit).traits
        assert case.state == "open" and suspects(crime, records, town) == {crime.culprit}
        assert any(r.sound and points_at(crime, crime.culprit, traits, r) for r in records)
        assert claim(case, crime.culprit, cases.routine) == ([crime.place], True)
    assert regulars
