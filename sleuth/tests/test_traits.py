import random

from sleuth.models import Villager
from sleuth.traits import COLOURS, FIXED, TRAITS, assign_traits, describe, face, figure


def ring(n):
    return [Villager(f"v{i:03d}", f"N{i}", "x", "y", "z", ["a", "b", "c"], {}) for i in range(1, n + 1)]


def test_describe_orders_and_phrases_traits():
    assert describe({"coat": "grey hoodie", "height": "tall"}) == "tall, in a grey hoodie"
    assert describe({"car": "red pickup", "hair": "red-haired"}) == "red-haired, with a red pickup"


def test_figure_puts_looks_before_the_noun_and_clothes_after():
    assert figure({"coat": "black puffer", "hair": "dark-haired", "height": "tall"}) == (
        "a tall, dark-haired figure in a black puffer")
    assert figure({"height": "average height", "car": "bicycle"}) == "an average-height figure with a bicycle"
    assert figure({"coat": "grey hoodie", "car": "white sedan"}) == "a figure in a grey hoodie, with a white sedan"


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
