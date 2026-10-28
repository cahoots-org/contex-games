import json
from dataclasses import asdict, replace
from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth.alibi import claim
from sleuth.case import CLIP_TRAITS, WHEN, Crime, Record, points_at, suspects, told
from sleuth.cases import CaseFile, Cases, case_json
from sleuth.config import Config
from sleuth.feed import Feed
from sleuth.game import PHASES
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance
from sleuth.offenders import Offender
from sleuth.photos import Album, Photo
from sleuth.players import Players
from sleuth.reputation import Reputation
from sleuth.tests.helpers import StubRoutine
from sleuth.tests.test_case import RESIDENTS, make_routine, make_town
from sleuth.traits import assign_traits


class FakeEngine:
    def __init__(self, town):
        self.town = town
        self.config = Config(population=0)
        self.reputation = Reputation(Config())
        self.lines = []
        self.feed = Feed(Lineage(), town, out=self.lines.append)
        self.delivered = []
        self.players = Players()
        self.album = Album()

    async def deliver(self, utterance, listener_ids, addressed=False):
        self.delivered.append((utterance, listener_ids, addressed))

    async def remove_villager(self, vid):
        self.town.remove(vid)


def make_cases(**config):
    town = make_town()
    assign_traits(town.villagers, Random(0))
    town.dress(1, Random(0))
    cases = Cases(Config(**config), town, make_routine(), Random(1), Ids())
    return cases, FakeEngine(town), town


async def tick(cases, engine, day=2, phase="morning", finished=None):
    await cases.on_tick(engine, day, phase, finished or {})


def kinds(engine, kind):
    return [e for e in engine.feed.recent if e.kind == kind]


@pytest.mark.asyncio
async def test_a_tick_with_no_shared_case_opens_one_at_once():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    assert case.state == "open" and cases.shared() is case and case.opened == 2.0
    assert kinds(engine, "case") and kinds(engine, "post")
    await tick(cases, engine, day=3)
    assert list(cases.files.values()) == [case]


@pytest.mark.asyncio
@pytest.mark.parametrize("now, part, said", [(2.0, (1, "night"), "last night"),
                                             (2.25, (2, "morning"), "this morning"),
                                             (2.5, (2, "afternoon"), "this afternoon")])
async def test_the_crime_is_set_in_the_part_of_the_day_just_finished(now, part, said):
    cases, engine, _ = make_cases()
    cases.routine = StubRoutine({vid: {p: street for p in PHASES} for vid, _, _, street in RESIDENTS})
    await cases.ensure(engine, now)
    case = cases.shared()
    assert (case.crime.day, case.crime.phase) == part and case.opened == now
    [post] = kinds(engine, "post")
    assert post.data["text"].endswith(f"{said}.")


@pytest.mark.asyncio
async def test_no_one_in_a_photo_of_the_crime_s_part_of_the_day_is_its_culprit_victim_or_witness():
    pictured = {"v1", "v3", "v5", "v7"}
    seen = set()
    for seed in range(30):
        cases, engine, _ = make_cases()
        cases.rng = Random(seed)
        cases.routine = StubRoutine({vid: {p: street for p in PHASES} for vid, _, _, street in RESIDENTS})
        engine.album.photos += [Photo("r-90", "gym", 2, "morning", {vid: {} for vid in pictured}, "", "v1"),
                                Photo("r-91", "gym", 2, "afternoon", {"v2": {}, "v4": {}}, "", "v2")]
        await cases.ensure(engine, 2.25)
        case = cases.shared()
        if case is None:
            continue
        witnesses = {r.holder for r in case.records.values() if r.kind == "memory"}
        assert not {case.crime.culprit, case.crime.victim} & pictured and not witnesses & pictured
        seen |= {case.crime.culprit, case.crime.victim}
    assert {"v2", "v4"} <= seen


@pytest.mark.asyncio
async def test_witness_memory_is_delivered_to_the_witness_alone_and_rooted():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    memory = next(r for r in case.records.values() if r.kind == "memory")
    witness = memory.holder
    u, ids, addressed = engine.delivered[0]
    assert ids == [witness] and addressed and cases.root_kind(u.id)[1] == "memory"
    assert u.id == memory.utterance and u.text == memory.text and u.verb == "saw" and u.place == case.crime.place


@pytest.mark.asyncio
async def test_the_news_breaks_as_the_case_opens():
    cases, engine, town = make_cases()
    await tick(cases, engine)
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
    assert cases.for_player("p-1") is case
    news, listeners, _ = next(d for d in engine.delivered if cases.root_kind(d[0].id)[1] == "news")
    victim = town.get(case.crime.victim)
    assert news.speaker_name == "The neighborhood app" and news.text == said and news.verb == "posted"
    assert victim.id in listeners and {v.id for v in town.villagers if v.household == victim.household} <= set(listeners)
    assert {v.id for v in town.present(case.crime.place)} <= set(listeners)
    [post] = kinds(engine, "post")
    assert post.data == {"case_id": case.crime.id, "speaker": "The neighborhood app", "text": said,
                         "app": True}


@pytest.mark.asyncio
async def test_unsolvable_draws_are_retried_at_once(monkeypatch):
    real, calls = cases_mod.make_solvable, []

    def twice_none(*a, **k):
        calls.append(a[0].id)
        return None if len(calls) <= 2 else real(*a, **k)

    monkeypatch.setattr(cases_mod, "make_solvable", twice_none)
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    assert len(calls) == 3 and case.crime.id == calls[-1] and case.state == "open"
    assert len(kinds(engine, "case")) == 1


@pytest.mark.asyncio
async def test_no_case_opens_when_every_draw_is_unsolvable_and_the_next_tick_tries_again(monkeypatch):
    calls = []
    monkeypatch.setattr(cases_mod, "make_solvable", lambda *a, **k: calls.append(1))
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    assert len(calls) == cases_mod.DRAWS and not cases.files and not kinds(engine, "case") and not engine.delivered
    monkeypatch.undo()
    await tick(cases, engine, day=3)
    assert cases.shared().state == "open"


@pytest.mark.asyncio
async def test_a_draw_that_fails_is_dropped_and_the_next_opens(monkeypatch, caplog):
    real = cases_mod.make_solvable
    calls = []

    def broken_once(*a, **k):
        calls.append(a[0].id)
        if len(calls) == 1:
            raise KeyError("v1")
        return real(*a, **k)

    monkeypatch.setattr(cases_mod, "make_solvable", broken_once)
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    assert calls[0] in caplog.text and case.crime.id == calls[1] and case.state == "open"


@pytest.mark.asyncio
async def test_a_case_gone_cold_is_followed_by_the_next_in_the_same_tick():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    [case] = cases.files.values()
    await tick(cases, engine, day=4, phase="night")
    assert case.state == "open"
    await tick(cases, engine, day=5)
    assert case.state == "closed"
    [closed] = kinds(engine, "case_closed")
    assert closed.data["case_id"] == case.crime.id
    assert f"The case went cold. It was {town_name(cases, case.crime.culprit)}." in engine.lines
    following = cases.shared()
    assert following.state == "open" and following is not case and following.opened == 5.0


def town_name(cases, vid):
    return cases.town.get(vid).name


@pytest.mark.asyncio
async def test_cases_round_trip_through_state():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    await tick(cases, engine, day=5)
    fresh = Cases(Config(), town, make_routine(), Random(1), Ids())
    fresh.restore(json.loads(json.dumps(cases.to_state())))
    assert fresh.files == cases.files and fresh.to_state() == cases.to_state()


@pytest.mark.asyncio
async def test_a_restore_with_no_open_case_opens_one():
    cases, engine, town = make_cases()
    culprit_file(cases).state = "closed"
    stale = CaseFile(replace(cases.files["case-1"].crime, id="case-2"), {}, "setup")
    state = {**json.loads(json.dumps(cases.to_state())), "last_closed": 1.0}
    state["files"].append(json.loads(json.dumps(asdict(stale))))
    fresh = Cases(Config(), town, make_routine(), Random(1), Ids())
    fresh.restore(state)
    assert list(fresh.files) == ["case-1"] and fresh.shared() is None
    await fresh.ensure(engine, 3.0)
    assert fresh.shared().state == "open"


def culprit_file(cases, culprit="v3", victim="v1", phase="night"):
    crime = Crime(cases.ids.next("case"), "steal", "bike", culprit, victim, "elm street", 1, phase, 1400, "opportunity",
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
async def test_the_crime_phase_log_is_kept_as_whereabouts_with_the_culprit_at_the_scene():
    cases, engine, _ = make_cases()
    log = {"v2": ["elm street", "bar"], "v4": ["gym"]}
    await tick(cases, engine, finished=log)
    [case] = cases.files.values()
    crime = case.crime
    assert case.whereabouts == {**log, crime.culprit: [crime.place]}


@pytest.mark.asyncio
async def test_without_a_finished_log_the_routine_gives_the_whereabouts():
    cases, engine, _ = make_cases()
    await cases.ensure(engine, 2.0)
    crime = cases.shared().crime
    assert cases.shared().whereabouts == {**{vid: [street] for vid, _, _, street in RESIDENTS},
                                          crime.culprit: [crime.place]}


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


@pytest.mark.asyncio
async def test_the_brief_leaves_out_news_the_feed_still_replays():
    cases, engine, _ = make_cases()
    shared = culprit_file(cases)
    engine.feed.on_post(Utterance("u-9", "app", "The neighborhood app", "elm street", "news", None), shared.crime.id)
    cases.brief(engine.feed, "p-1", 2)
    assert [e.kind for e in engine.feed.recent] == ["post", "case"]


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
        case = cases.shared()
        if case is None or cases.routine.place(case.crime.culprit, case.crime.phase) != case.crime.place:
            continue
        crime = case.crime
        regulars += 1
        records = list(case.records.values())
        traits = town.looks(crime.culprit, crime.day)
        assert case.state == "open" and suspects(crime, records, town) == {crime.culprit}
        assert any(r.sound and points_at(crime, crime.culprit, traits, r) for r in records)
        assert claim(case, crime.culprit, cases.routine) == ([crime.place], True)
    assert regulars


def test_cases_dress_today_with_the_culprits_caution():
    cases, _, town = make_cases(case_days=20)
    for v in town.villagers:
        v.wardrobe = ["green raincoat", "plaid flannel", "grey hoodie"]
    file = culprit_file(cases)
    town.worn = {1: {"v3": "green raincoat"}}
    assert cases.cautious(2) == {"v3": "green raincoat"} and cases.cautious(1) == {}
    for day in range(2, 21):
        cases.dress(day)
        assert town.outfit("v3", day) != "green raincoat"
    cases.close(file, None)
    assert cases.cautious(21) == {}


@pytest.mark.asyncio
async def test_only_offenders_commit_crimes():
    opened = 0
    for seed in range(40):
        cases, engine, _ = make_cases(offenders=3)
        cases.rng = Random(seed)
        await tick(cases, engine)
        if case := cases.shared():
            opened += 1
            assert case.crime.culprit in cases.offenders.active and len(cases.offenders.active) == 3
    assert opened > 30


@pytest.mark.asyncio
async def test_no_case_opens_while_every_offender_is_quiet():
    cases, engine, _ = make_cases()
    cases.offenders.top_up(cases.town, cases.rng)
    for o in cases.offenders.active.values():
        o.quiet_until = 9
    await tick(cases, engine)
    assert not cases.files


def test_solvability_still_narrows_among_everyone_not_just_offenders():
    cases, _, town = make_cases()
    file = culprit_file(cases)
    cases.offenders.active = {"v3": Offender()}
    looks = town.looks("v3", 1)
    twin = next(v for v in town.villagers if v.id not in ("v1", "v3"))
    twin.traits = dict(town.get("v3").traits)
    town.worn[1][twin.id] = looks["coat"]
    clip = Record("r-1", file.crime.id, "clip", "elm street", "11:20pm", "", traits={c: looks[c] for c in CLIP_TRAITS})
    assert {"v3", twin.id} <= suspects(file.crime, [clip], town)


@pytest.mark.asyncio
async def test_a_case_gone_cold_counts_as_an_escape():
    cases, engine, _ = make_cases()
    await tick(cases, engine)
    culprit = cases.shared().crime.culprit
    await tick(cases, engine, day=5)
    assert cases.offenders.active[culprit].escaped == 1


@pytest.mark.asyncio
async def test_offenders_round_trip_with_the_cases():
    cases, engine, town = make_cases()
    await tick(cases, engine)
    vid = next(iter(cases.offenders.active))
    cases.offenders.active[vid] = Offender("serious", 1, 4)
    cases.offenders.exposed["v8"] = "stole Dana Reyes's bike"
    fresh = Cases(Config(), town, make_routine(), Random(1), Ids())
    fresh.restore(json.loads(json.dumps(cases.to_state())))
    assert fresh.offenders.active == cases.offenders.active and fresh.offenders.exposed == cases.offenders.exposed


@pytest.mark.asyncio
async def test_an_exposed_offender_may_reform_only_on_a_morning():
    cases, engine, _ = make_cases(reform_chance=1.0)
    cases.offenders.active["v3"] = Offender()
    cases.offenders.exposed["v3"] = "stole Dana Reyes's bike"
    await tick(cases, engine, phase="afternoon")
    assert "v3" in cases.offenders.active
    await tick(cases, engine, day=3)
    assert "v3" not in cases.offenders.active


@pytest.mark.asyncio
async def test_a_held_serious_episode_arrests_the_culprit_who_leaves_town():
    cases, engine, town = make_cases()
    file = culprit_file(cases)
    file.crime.tier = "serious"
    cases.offenders.active["v3"] = Offender("serious")
    await cases.on_held(engine, file, "p-1")
    assert "v3" not in town and "v3" in {v.id for v in town.departed} and "v3" not in cases.offenders.active
    assert "v3" not in cases.offenders.exposed
    assert any(e.kind == "post" and e.data["text"] == "Fay Okafor was arrested and has left town." for e in engine.feed.recent)


@pytest.mark.asyncio
async def test_no_open_case_s_witness_is_another_open_case_s_culprit():
    for seed in range(30):
        cases, engine, town = make_cases(offenders=8)
        cases.rng = Random(seed)
        cases.routine = StubRoutine({vid: {"night": "elm street"} for vid, *_ in RESIDENTS})
        other = culprit_file(cases, culprit="v7", victim="v2")
        other.crime.owner = "p-1"
        await tick(cases, engine)
        case = cases.shared()
        if case is None:
            continue
        holders = {r.holder for r in case.records.values() if r.kind == "memory"}
        dropped = {r.who for r in case.records.values() if r.trail}
        assert "v7" not in holders | dropped
