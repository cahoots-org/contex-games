import json
import os
import random
from collections import defaultdict
from dataclasses import asdict

import pytest

from sleuth.models import Villager
from sleuth.town import STREETS
from sleuth.tests.test_copy import WORDS
from sleuth.town_gen import (
    HOUSEHOLDS, MAX_FAILED_BATCHES, SeedMismatch, form_households, generate_villagers,
    load_or_generate, settle, wire_relationships, world_path,
)

HOUSEHOLD_TIES = {"spouse", "partner", "roommate", "parent", "child", "sibling"}


def entry(i):
    return {
        "name": f"Name{i}", "occupation": "baker", "personality": "gruff",
        "grudge": "old feud",
        "needs": ["my oven keeps failing", "my daughter wants to leave", "flour prices"],
        "quirks": ["blames the town council for everything"],
    }


class StubWriter:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    async def complete(self, system, user, max_tokens=400):
        self.calls += 1
        return self.text


class FreshBatches:
    """A writer whose every reply is a fenced batch of n villagers with names not used before."""

    def __init__(self, n):
        self.n = n
        self.calls = 0

    async def complete(self, system, user, max_tokens=400):
        self.calls += 1
        start = (self.calls - 1) * self.n
        return "```json\n" + json.dumps([entry(i) for i in range(start, start + self.n)]) + "\n```"


def fenced(n):
    return "Here you go:\n```json\n" + json.dumps([entry(i) for i in range(n)]) + "\n```"


def ring(n):
    return [Villager(f"v{i:03d}", f"N{i}", "x", "y", "z", ["a", "b", "c"], {}) for i in range(1, n + 1)]


@pytest.mark.asyncio
async def test_generate_villagers_parses_fenced_json_and_assigns_ids():
    writer = FreshBatches(10)

    villagers = await generate_villagers(writer, 12, random.Random(1))

    assert [v.id for v in villagers] == [f"v{i:03d}" for i in range(1, 13)]
    assert writer.calls == 2
    assert all(v.relationships == {} for v in villagers)


@pytest.mark.asyncio
async def test_generate_villagers_makes_more_batches_than_the_failure_cap():
    writer = FreshBatches(10)

    villagers = await generate_villagers(writer, 100, random.Random(1))

    assert len(villagers) == 100
    assert writer.calls == 10


@pytest.mark.asyncio
async def test_generation_names_the_taken_first_names_and_skips_a_repeat():
    prompts = []
    batches = [
        [{**entry(i), "name": f"Ada Name{i}"} if i == 0 else entry(i) for i in range(3)],
        [{**entry(9), "name": "Ada Other"}, entry(3)],
    ]

    class RecordingWriter:
        async def complete(self, system, user, max_tokens=400):
            prompts.append(user)
            return json.dumps(batches[len(prompts) - 1])

    villagers = await generate_villagers(RecordingWriter(), 4, random.Random(1))

    assert [v.name for v in villagers] == ["Ada Name0", "Name1", "Name2", "Name3"]
    assert "these are taken: Ada, Name1, Name2" in prompts[1]


@pytest.mark.asyncio
async def test_every_villager_has_three_to_five_needs():
    villagers = await generate_villagers(StubWriter(fenced(5)), 5, random.Random(1))

    assert all(3 <= len(v.needs) <= 5 for v in villagers)


def test_wire_relationships_bounds_and_reciprocity():
    villagers = ring(30)
    wire_relationships(villagers, random.Random(7))
    by_id = {v.id: v for v in villagers}
    reverse = {"friend": "friend", "coworker": "coworker", "neighbor": "neighbor", "rival": "rival"}

    for v in villagers:
        assert 2 <= len(v.relationships) <= 4
        for other, kind in v.relationships.items():
            assert by_id[other].relationships[v.id] == reverse[kind]


@pytest.mark.asyncio
async def test_load_or_generate_reuses_seed_file(tmp_path):
    path = tmp_path / "seed.json"
    writer = StubWriter(fenced(10))

    first = await load_or_generate(str(path), writer, 10, random.Random(1))
    calls = writer.calls
    second = await load_or_generate(str(path), writer, 10, random.Random(2))

    assert writer.calls == calls
    assert second == first
    assert all(v.relationships for v in second)


@pytest.mark.asyncio
async def test_seed_of_another_size_is_rejected(tmp_path):
    path = tmp_path / "seed.json"
    await load_or_generate(str(path), StubWriter(fenced(10)), 10, random.Random(1))

    with pytest.raises(SeedMismatch, match=f"{path} has 10 residents but population is 20; "
                       "delete it or set SLEUTH_POPULATION=10"):
        await load_or_generate(str(path), StubWriter(fenced(10)), 20, random.Random(1))


class SequenceWriter:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, system, user, max_tokens=400):
        self.calls += 1
        return self.texts[min(self.calls, len(self.texts)) - 1]


@pytest.mark.asyncio
async def test_generate_villagers_gives_up_after_max_attempts():
    writer = SequenceWriter("[]")

    with pytest.raises(ValueError, match="0 of 5"):
        await generate_villagers(writer, 5, random.Random(1))

    assert writer.calls == MAX_FAILED_BATCHES


@pytest.mark.asyncio
async def test_generate_villagers_retries_invalid_replies():
    few_needs = json.dumps([{**entry(0), "needs": ["only", "two"]}])
    writer = SequenceWriter(json.dumps(entry(0)), few_needs, fenced(3))

    villagers = await generate_villagers(writer, 3, random.Random(1))

    assert len(villagers) == 3
    assert writer.calls == 3


@pytest.mark.asyncio
async def test_wrapper_object_reply_yields_villagers():
    writer = StubWriter(json.dumps({"villagers": [entry(i) for i in range(3)]}))

    villagers = await generate_villagers(writer, 3, random.Random(1))

    assert [v.name for v in villagers] == ["Name0", "Name1", "Name2"]


@pytest.mark.asyncio
async def test_needs_string_is_split_into_needs():
    multi = "- my oven keeps failing\n- my daughter wants to leave\n2. flour prices"
    sentences = "My oven fails. My daughter wants to leave! Flour is dear."
    reply = json.dumps([{**entry(0), "needs": multi}, {**entry(1), "needs": sentences}])

    villagers = await generate_villagers(StubWriter(reply), 2, random.Random(1))

    assert villagers[0].needs == ["my oven keeps failing", "my daughter wants to leave", "flour prices"]
    assert villagers[1].needs == ["My oven fails.", "My daughter wants to leave!", "Flour is dear."]


@pytest.mark.asyncio
async def test_one_sentence_needs_string_is_rejected():
    writer = StubWriter(json.dumps([{**entry(0), "needs": "Just one worry."}]))

    with pytest.raises(ValueError, match="0 of 1"):
        await generate_villagers(writer, 1, random.Random(1))

    assert writer.calls == MAX_FAILED_BATCHES


@pytest.mark.asyncio
async def test_an_empty_or_null_grudge_is_a_valid_villager():
    writer = StubWriter(json.dumps([{**entry(0), "grudge": ""}, {**entry(1), "grudge": None}]))

    villagers = await generate_villagers(writer, 2, random.Random(1))

    assert [v.grudge for v in villagers] == ["", ""]


@pytest.mark.asyncio
async def test_generation_asks_for_mostly_kindly_villagers_and_a_few_sour_ones():
    prompts = []

    class RecordingWriter:
        async def complete(self, system, user, max_tokens=400):
            prompts.append(user)
            return json.dumps([entry(i) for i in range(10)])

    await generate_villagers(RecordingWriter(), 10, random.Random(1))

    assert "Most residents are good-natured" in prompts[0]
    assert "one resident in five is sour" in prompts[0]
    assert 'empty grudge ""' in prompts[0]


@pytest.mark.asyncio
async def test_a_new_world_is_saved_in_a_folder_of_its_own(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = world_path("abc123")
    await load_or_generate(path, FreshBatches(10), 10, random.Random(1))
    assert (tmp_path / "sleuth_worlds" / "abc123.json").exists()


def test_world_path_sits_under_the_data_dir(tmp_path):
    assert world_path("abc", str(tmp_path)) == str(tmp_path / "sleuth_worlds" / "abc.json")
    assert world_path("abc") == os.path.join("sleuth_worlds", "abc.json")


@pytest.mark.asyncio
async def test_a_fixed_session_reuses_its_saved_village(tmp_path):
    path = world_path("fixed", str(tmp_path))
    first = await load_or_generate(path, FreshBatches(10), 10, random.Random(1))
    again = await load_or_generate(path, FreshBatches(0), 10, random.Random(2))
    assert [v.id for v in again] == [v.id for v in first]


def households(vs):
    by = defaultdict(list)
    for v in vs:
        by[v.household].append(v)
    return by


def test_form_households_puts_everyone_in_one_household_on_a_street():
    vs = ring(50)
    form_households(vs, random.Random(2))
    assert all(v.household and v.home in STREETS for v in vs)
    by = households(vs)
    assert all(len({v.home for v in h}) == 1 and len(h) <= 2 for h in by.values())
    pair = next(h for h in by.values() if len(h) == 2)
    assert pair[0].relationships[pair[1].id] in HOUSEHOLD_TIES
    assert pair[0].warmth[pair[1].id] == pair[1].warmth[pair[0].id] > 0


def test_form_households_keeps_streets_balanced_and_numbers_households():
    vs = ring(50)
    form_households(vs, random.Random(2))
    ids = sorted(households(vs))
    assert ids == [f"h{i:02d}" for i in range(1, len(ids) + 1)]
    per_street = [sum(1 for h in ids if households(vs)[h][0].home == s) for s in STREETS]
    assert max(per_street) - min(per_street) <= 1


def test_parent_and_child_ties_point_both_ways():
    kinds = {k for k, *_ in HOUSEHOLDS}
    assert "parent and adult child" in kinds
    seen = set()
    for seed in range(20):
        vs = ring(50)
        form_households(vs, random.Random(seed))
        for v in vs:
            for other, kind in v.relationships.items():
                back = next(o for o in vs if o.id == other).relationships[v.id]
                assert back == {"parent": "child", "child": "parent"}.get(kind, kind)
                seen.add(kind)
    assert {"parent", "child"} <= seen


def test_rival_ties_are_cold_and_household_ties_warm():
    vs = ring(50)
    rng = random.Random(5)
    form_households(vs, rng)
    wire_relationships(vs, rng)
    by_id = {v.id: v for v in vs}
    kinds = [(v, o, k) for v in vs for o, k in v.relationships.items()]
    assert any(k == "rival" for _, _, k in kinds)
    for v, o, kind in kinds:
        assert -1 <= v.warmth[o] <= 1 and v.warmth[o] == by_id[o].warmth[v.id]
        if kind == "rival":
            assert v.warmth[o] < 0
        if kind in HOUSEHOLD_TIES:
            assert v.warmth[o] >= 0.2
        if kind == "neighbor":
            assert v.home == by_id[o].home
        assert len(v.relationships) <= 4


def bad_terms(v, villagers):
    """How many residents v is on cold terms with."""
    ids = {o.id for o in villagers}
    return sum(w < 0 for o, w in v.warmth.items() if o in ids)


def test_several_residents_have_two_people_on_bad_terms_with_them():
    for seed in range(20):
        vs = ring(24)
        rng = random.Random(seed)
        form_households(vs, rng)
        wire_relationships(vs, rng)
        assert sum(bad_terms(v, vs) >= 2 for v in vs) >= 4
        assert all(2 <= len(v.relationships) <= 4 for v in vs)


def test_someone_moving_in_is_a_rival_while_too_few_have_two_on_bad_terms():
    vs = ring(10)
    rng = random.Random(3)
    form_households(vs, rng)
    v = Villager("v099", "Wren Abara", "x", "y", "", [], {})
    settle(v, vs, "oak street", rng)
    assert bad_terms(v, vs) >= 1


@pytest.mark.asyncio
async def test_village_generation_is_deterministic_after_the_model(tmp_path):
    a = await load_or_generate(str(tmp_path / "a.json"), FreshBatches(10), 20, random.Random(9))
    b = await load_or_generate(str(tmp_path / "b.json"), FreshBatches(10), 20, random.Random(9))
    assert a == b
    assert all(v.traits and v.household and v.home for v in a)


@pytest.mark.asyncio
async def test_load_or_generate_rejects_a_village_without_traits(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps([asdict(Villager("v001", "Ada", "miller", "calm", "", ["a", "b", "c"], {}, traits={}))]))
    with pytest.raises(SeedMismatch, match="before Sleuth"):
        await load_or_generate(str(path), FreshBatches(1), 1, random.Random(1))


@pytest.mark.asyncio
async def test_load_or_generate_rejects_a_village_without_wardrobes(tmp_path):
    path = tmp_path / "old.json"
    traits = {"height": "tall", "hair": "bald", "car": "bicycle"}
    path.write_text(json.dumps([asdict(Villager("v001", "Ada", "miller", "calm", "", ["a", "b", "c"], {}, traits=traits))]))
    with pytest.raises(SeedMismatch, match="before outfits"):
        await load_or_generate(str(path), FreshBatches(1), 1, random.Random(1))


@pytest.mark.asyncio
async def test_generation_asks_for_a_modern_town():
    prompts = []

    class RecordingWriter:
        async def complete(self, system, user, max_tokens=400):
            prompts.append((system, user))
            return json.dumps([entry(i) for i in range(10)])

    await generate_villagers(RecordingWriter(), 10, random.Random(1))
    system, user = prompts[0]
    assert "small modern American town" in system
    assert "break-ins, layoffs, gossip" in user
    assert not WORDS.search(user) and "mayor" not in user


@pytest.mark.asyncio
async def test_generation_says_no_religion_and_regenerates_religious_residents():
    prompts = []

    class Pious:
        async def complete(self, system, user, max_tokens=400):
            prompts.append(user)
            batch = [entry(i + 10 * len(prompts)) for i in range(2)]
            if len(prompts) == 1:
                batch[0]["occupation"] = "groundskeeper behind the Methodist parsonage"
                batch[1]["needs"][0] = "the church bake sale"
            return json.dumps(batch)

    villagers = await generate_villagers(Pious(), 2, random.Random(1))
    assert len(villagers) == 2 and len(prompts) == 2
    assert not [v for v in villagers if WORDS.search(json.dumps(asdict(v)))]
    assert "faith or spirituality" in prompts[0]


@pytest.mark.asyncio
async def test_generated_residents_carry_one_or_two_quirks():
    batch = [entry(i) for i in range(10)]
    batch[3]["quirks"] = ["counts the ducks", "hates leaf blowers", "collects spoons"]
    villagers = await generate_villagers(StubWriter(json.dumps(batch)), 10, random.Random(1))
    assert all(1 <= len(v.quirks) <= 2 for v in villagers)
    assert villagers[3].quirks == ["counts the ducks", "hates leaf blowers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("quirks", [None, [], [""]])
async def test_a_reply_without_quirks_is_rejected(quirks):
    batch = [entry(0), entry(1)]
    if quirks is None:
        del batch[0]["quirks"]
    else:
        batch[0]["quirks"] = quirks
    villagers = await generate_villagers(StubWriter(json.dumps(batch)), 1, random.Random(1))
    assert [v.name for v in villagers] == ["Name1"]


@pytest.mark.asyncio
async def test_a_quirk_of_faith_is_rejected():
    batch = [entry(0), entry(1)]
    batch[0]["quirks"] = ["sings in the church choir"]
    villagers = await generate_villagers(StubWriter(json.dumps(batch)), 1, random.Random(1))
    assert [v.name for v in villagers] == ["Name1"]


@pytest.mark.asyncio
async def test_an_old_seed_without_quirks_still_loads(tmp_path):
    path = tmp_path / "old.json"
    old = asdict(Villager("v001", "Ada", "miller", "calm", "", ["a", "b", "c"], {},
                          traits={"height": "tall"}, wardrobe=["a red scarf"]))
    del old["quirks"]
    path.write_text(json.dumps([old]))
    villagers = await load_or_generate(str(path), FreshBatches(1), 1, random.Random(1))
    assert [v.quirks for v in villagers] == [[]]
