import random
from itertools import product

import pytest

from sleuth.models import Villager
from sleuth.traits import COLOURS, FIXED, RANGES, TRAITS, assign_look, assign_traits, describe, face, figure, fits


def ring(n):
    return [Villager(f"v{i:03d}", f"N{i}", "x", "y", "z", ["a", "b", "c"], {}) for i in range(1, n + 1)]


def test_describe_orders_and_phrases_traits():
    assert describe({"height": "tall", "gender": "woman", "hair": "red-haired"}) == "a woman, tall, red-haired"
    assert describe({"coat": "grey hoodie", "height": "tall"}) == "tall, in a grey hoodie"
    assert describe({"car": "red pickup", "hair": "red-haired"}) == "red-haired, with a red pickup"


def test_figure_puts_looks_before_the_noun_and_clothes_after():
    assert figure({"coat": "black puffer", "hair": "dark-haired", "height": "tall"}) == (
        "a tall, dark-haired figure in a black puffer")
    assert figure({"height": "average height", "car": "bicycle"}) == "an average-height figure with a bicycle"
    assert figure({"coat": "grey hoodie", "car": "white sedan"}) == "someone in a grey hoodie with a white sedan"
    assert figure({"gender": "woman", "height": "tall", "coat": "in a dark coat"}) == "a tall woman in a dark coat"
    assert figure({}) == "someone"


def test_every_range_covers_values_of_one_category():
    for phrase, covered in RANGES.items():
        assert any(set(covered) <= set(values) for values in TRAITS.values()), phrase


def test_assign_traits_gives_fixed_looks_and_a_wardrobe_of_three():
    vs = ring(50)
    assign_traits(vs, random.Random(3))
    assert all(set(v.traits) == set(FIXED) for v in vs)
    assert len({tuple(sorted(v.traits.items())) for v in vs}) == 50
    assert all(len(set(v.wardrobe)) == 3 and set(v.wardrobe) <= set(TRAITS["coat"]) for v in vs)
    for cat in FIXED:
        assert all(sum(v.traits[cat] == x for v in vs) >= 2 for x in TRAITS[cat])


def test_assign_traits_keeps_each_category_balanced():
    vs = ring(50)
    assign_traits(vs, random.Random(4))
    for cat in FIXED:
        counts = [sum(v.traits[cat] == x for v in vs) for x in TRAITS[cat]]
        assert max(counts) - min(counts) <= 1


def test_assign_traits_tolerates_more_residents_than_combinations():
    vs = ring(400)
    assign_traits(vs, random.Random(1))
    assert all(set(v.traits) == set(FIXED) for v in vs)


def test_face_draws_hair_and_coat_from_the_traits():
    assert all(COLOURS[x] for x in TRAITS["coat"] + TRAITS["hair"] if x != "bald")
    bald = face({"height": "short", "hair": "bald", "coat": "grey hoodie", "car": "bicycle"})
    assert bald == {"hair": None, "coat": COLOURS["grey hoodie"], "height": 0}
    assert face({"height": "tall", "hair": "red-haired", "coat": "black puffer"})["hair"] == COLOURS["red-haired"]


def test_a_ranged_sighting_fits_every_value_it_covers():
    assert fits({"height": "not tall"}, {"height": "short", "hair": "bald"})
    assert fits({"height": "not tall"}, {"height": "average height"})
    assert not fits({"height": "not tall"}, {"height": "tall"})
    assert fits({"hair": "bald"}, {"hair": "bald"}) and not fits({"hair": "bald"}, {"hair": "blond"})


def test_a_ranged_sighting_is_described_as_said():
    assert describe({"height": "not tall", "coat": "in a dark coat"}) == "not tall, in a dark coat"


def test_generated_residents_keep_their_gender():
    vs = [Villager(f"v{i}", f"N{i}", "x", "y", "", [], {}, {"gender": ("man", "woman")[i % 2]}) for i in range(20)]
    assign_traits(vs, random.Random(2))
    assert [v.traits["gender"] for v in vs] == [("man", "woman")[i % 2] for i in range(20)]
    assert len({tuple(v.traits[c] for c in FIXED) for v in vs}) == 20


@pytest.mark.parametrize("gender", ["man", "woman"])
@pytest.mark.parametrize("seed", range(5))
def test_someone_moving_in_is_given_a_look_of_their_own_gender(gender, seed):
    others = [Villager(f"v{i}", f"N{i}", "x", "y", "", [], {}, dict(zip(FIXED, look)))
              for i, look in enumerate(product(*(TRAITS[c] for c in FIXED))) if look[0] != gender]
    v = Villager("v0", "Wren Abara", "x", "y", "", [], {}, {"gender": gender})
    assign_look(v, others, random.Random(seed))
    assert v.traits["gender"] == gender
    full = [Villager(f"w{i}", f"M{i}", "x", "y", "", [], {}, dict(zip(FIXED, look)))
            for i, look in enumerate(product(*(TRAITS[c] for c in FIXED)))]
    assign_look(v, full, random.Random(seed))
    assert v.traits["gender"] == gender
