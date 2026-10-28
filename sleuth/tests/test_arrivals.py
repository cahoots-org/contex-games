import asyncio
import json
from itertools import product
from random import Random

import pytest

from sleuth.arrivals import move_in, moved_in
from sleuth.case import Record, suspects
from sleuth.cases import BREATHES, RESOLVED
from sleuth.config import Config
from sleuth.districts import Districts
from sleuth.game import Game
from sleuth.models import Villager
from sleuth.photos import Album
from sleuth.players import Players
from sleuth.reputation import Reputation
from sleuth.routine import Routine
from sleuth.tests.helpers import StubBaselines, StubJev
from sleuth.tests.test_cases import culprit_file, make_cases, tiered
from sleuth.town_gen import settle
from sleuth.traits import FIXED, TRAITS, assign_look

RESIDENT = {"name": "Wren Abara", "occupation": "locksmith", "personality": "dry and patient", "grudge": "",
            "needs": ["a lock I can't pick", "my sister's new job", "rent going up"], "quirks": ["collects old keys"]}


class CountingWriter:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def complete(self, system, user, max_tokens=400):
        self.calls += 1
        await asyncio.sleep(0)
        return self.reply.pop(0) if isinstance(self.reply, list) else self.reply


class Arriving:
    """What moving in uses of the engine, with counting Haiku and Jev stand-ins."""

    def __init__(self, cases, town, feed, places, population=50):
        self.config = Config(population=population, newcomer_offender_chance=0.0)
        self.town, self.cases, self.feed = town, cases, feed
        self.writer = CountingWriter(json.dumps([RESIDENT]))
        self.jev = StubJev({"work": "library", "leisure": "bar"})
        self.routine = Routine(self.jev, places, self.config)
        self.baselines = StubBaselines(0.5)
        self.game = Game()
        self.album = Album()
        self.players = Players()
        self.reputation = Reputation(Config())
        self.added = []

    async def deliver(self, utterance, listener_ids, addressed=False):
        pass

    async def add_villager(self, v, place):
        self.added.append((v.id, place))
        self.town.add(v, place)

    async def remove_villager(self, vid):
        self.town.remove(vid)


def arriving(tmp_path, population=50):
    cases, fake, town = make_cases()
    return Arriving(cases, town, fake.feed, str(tmp_path / "places.json"), population), town


@pytest.mark.asyncio
async def test_someone_moves_in_on_the_arrested_resident_s_street(tmp_path):
    engine, town = arriving(tmp_path)
    v = await (await engine.cases.arrest(engine, "v5"))
    assert "v5" not in town and v is not None and v.id == "v009" and v.name == "Wren Abara" and v in town.villagers
    assert v.home == "oak street" and v.household not in {o.household for o in town.villagers if o is not v}
    assert len(v.relationships) == 2 and "neighbor" in v.relationships.values()
    neighbour = next(o for o, kind in v.relationships.items() if kind == "neighbor")
    assert town.get(neighbour).home == "oak street" and town.get(neighbour).relationships[v.id] == "neighbor"
    assert engine.added == [("v009", "hardware store")] and engine.routine.place("v009", "night") == "oak street"
    arrested, moved = [e for e in engine.feed.recent if e.kind == "post"]
    assert arrested.data["text"] == "Hal Burke was arrested and has left town."
    assert moved.data["text"] == "Wren Abara moved in on Oak Street. Locksmith." and moved.data["app"]


@pytest.mark.asyncio
async def test_moving_in_costs_one_haiku_and_one_jev_call(tmp_path):
    engine, _ = arriving(tmp_path)
    assert await move_in(engine, "elm street")
    assert engine.writer.calls == 1 and engine.jev.calls == 1


@pytest.mark.asyncio
async def test_moving_in_never_grows_the_town_past_population(tmp_path):
    engine, town = arriving(tmp_path, population=8)
    assert await move_in(engine, "elm street") is None
    assert town.alive_count == 8 and engine.writer.calls == 0 and engine.jev.calls == 0


@pytest.mark.asyncio
async def test_a_failed_move_in_is_logged_and_adds_no_one(tmp_path, caplog):
    engine, town = arriving(tmp_path)
    engine.writer.reply = "not json"
    assert await move_in(engine, "elm street") is None
    assert town.alive_count == 8 and "moving in" in caplog.text


@pytest.mark.asyncio
async def test_someone_who_moved_in_may_be_an_offender_while_there_is_room(tmp_path):
    engine, _ = arriving(tmp_path)
    engine.config = Config(newcomer_offender_chance=1.0, max_offenders=1)
    v = await move_in(engine, "elm street")
    assert v.id in engine.cases.offenders.active
    engine.writer.reply = json.dumps([{**RESIDENT, "name": "Oona Pike"}])
    assert (await move_in(engine, "elm street")).id not in engine.cases.offenders.active


def test_a_resident_who_moved_in_has_unique_looks_and_three_outfits():
    looks = list(product(*(TRAITS[c] for c in FIXED)))
    others = [Villager(f"v{i}", f"N{i}", "x", "y", "", [], {}, dict(zip(FIXED, look))) for i, look in enumerate(looks[1:])]
    v = Villager("v0", "Wren Abara", "x", "y", "", [], {})
    assign_look(v, others, Random(0))
    assert tuple(v.traits[c] for c in FIXED) == looks[0]
    assert len(set(v.wardrobe)) == 3 and set(v.wardrobe) <= set(TRAITS["coat"])


@pytest.mark.asyncio
async def test_someone_who_moved_in_never_fits_an_open_case(tmp_path):
    for seed in range(20):
        engine, town = arriving(tmp_path)
        engine.cases.rng = Random(seed)
        file = culprit_file(engine.cases)
        hair = town.get("v3").traits["hair"]
        file.records["r-1"] = Record("r-1", file.crime.id, "clue", "elm street", "", "", traits={"hair": hair})
        before = suspects(file.crime, list(file.records.values()), town)
        v = await move_in(engine, "oak street")
        assert v.traits["hair"] != hair and suspects(file.crime, list(file.records.values()), town) == before


@pytest.mark.asyncio
async def test_a_failed_move_in_leaves_no_ties_and_no_offender(tmp_path):
    engine, town = arriving(tmp_path)
    engine.config = Config(newcomer_offender_chance=1.0)

    async def fails(v, place):
        raise RuntimeError("no mind")

    engine.add_villager = fails
    assert await move_in(engine, "oak street") is None
    assert not any("v009" in v.relationships or "v009" in v.warmth for v in town.villagers)
    assert "v009" not in engine.cases.offenders.active


def test_someone_settling_on_an_empty_street_still_gets_two_ties():
    villagers = [Villager(f"v{i}", f"N{i}", "x", "y", "", [], {}, home="elm street", household=f"h{i:02d}")
                 for i in range(1, 5)]
    v = Villager("v9", "Wren Abara", "x", "y", "", [], {})
    settle(v, villagers, "oak street", Random(0))
    assert (v.home, v.household) == ("oak street", "h05") and len(v.relationships) == 2


@pytest.mark.asyncio
async def test_a_home_left_empty_is_moved_into_on_a_later_tick(tmp_path):
    engine, town = arriving(tmp_path)
    engine.writer.reply = "not json"
    assert await (await engine.cases.arrest(engine, "v5")) is None
    assert engine.cases.vacant == ["oak street"]
    engine.writer.reply = json.dumps([RESIDENT])
    await engine.cases.on_tick(engine, 2, "morning", {})
    await asyncio.gather(*engine.cases._moving)
    assert engine.cases.vacant == [] and town.get("v009").home == "oak street"


@pytest.mark.asyncio
async def test_two_moving_in_at_once_get_their_own_ids_and_names(tmp_path):
    engine, town = arriving(tmp_path)
    engine.writer.reply = [json.dumps([RESIDENT]), json.dumps([{**RESIDENT, "name": "Oona Pike"}])]
    tasks = [await engine.cases.arrest(engine, vid) for vid in ("v5", "v6")]
    first, second = await asyncio.gather(*tasks)
    assert (first.id, first.name, second.id, second.name) == ("v009", "Wren Abara", "v010", "Oona Pike")


@pytest.mark.asyncio
async def test_a_held_major_episode_arrests_the_culprit_and_someone_moves_in(tmp_path):
    engine, town = arriving(tmp_path)
    file = tiered(engine.cases, "major", "v5", "v1")
    await engine.cases.on_held(engine, file, "p-1")
    await asyncio.gather(*engine.cases._moving)
    assert file.state == "closed" and "v5" not in town and "v5" not in engine.cases.offenders.exposed
    posts = [e.data["text"] for e in engine.feed.recent if e.kind == "post"]
    assert "Hal Burke was arrested and has left town." in posts
    assert "Wren Abara moved in on Oak Street. Locksmith." in posts


def test_the_moved_in_post_reads_well_whatever_the_job_is_called():
    assert moved_in("Mavis Oakhurst", "Night-shift pharmacy technician", "Oak Street") == \
        "Mavis Oakhurst moved in on Oak Street. Night-shift pharmacy technician."
    assert moved_in("Ada Reyes", "owner of the Pet Parlor", "Elm Street") == \
        "Ada Reyes moved in on Elm Street. Owner of the Pet Parlor."


@pytest.mark.asyncio
async def test_a_solved_death_gets_a_sober_line_not_relief(tmp_path):
    engine, town = arriving(tmp_path)
    engine.cases.districts = Districts(engine.cases.config)
    file = tiered(engine.cases, "major", "v5", "v1")
    await engine.cases.on_held(engine, file, "p-1")
    await asyncio.gather(*engine.cases._moving)
    posts = [e.data["text"] for e in engine.feed.recent if e.kind == "post"]
    assert any(p.endswith(RESOLVED.split("}", 1)[1]) for p in posts)
    assert not any(BREATHES.split("}", 1)[1].split("{")[0] in p for p in posts)
