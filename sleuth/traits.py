"""The fixed look of each resident: what a witness can see, never a name."""

import random
from collections import Counter

from sleuth.models import Villager

TRAITS: dict[str, tuple[str, ...]] = {
    "height": ("short", "average height", "tall"),
    "hair": ("grey-haired", "blond", "dark-haired", "red-haired", "bald"),
    "coat": ("grey hoodie", "denim jacket", "green raincoat", "black puffer", "plaid flannel"),
    "car": ("red pickup", "white sedan", "blue hatchback", "silver minivan", "bicycle"),
}
PHRASES = {"height": "{}", "hair": "{}", "coat": "in a {}", "car": "with a {}"}
COLOURS = {
    "grey-haired": "#9a9a9a", "blond": "#e0c77a", "dark-haired": "#2b2118", "red-haired": "#b0482a", "bald": None,
    "grey hoodie": "#8a8d91", "denim jacket": "#3d5f8a", "green raincoat": "#4f8a3e", "black puffer": "#25272b",
    "plaid flannel": "#9a3a30",
}


def _look(v: Villager) -> tuple[str, ...]:
    return tuple(v.traits[c] for c in TRAITS)


def assign_traits(villagers: list[Villager], rng: random.Random) -> None:
    """Deal each category evenly, then swap values until every look is unique or the swaps run out."""
    for v in villagers:
        v.traits = {}
    for cat, values in TRAITS.items():
        order = rng.sample(values, len(values))
        column = [order[i % len(order)] for i in range(len(villagers))]
        rng.shuffle(column)
        for v, value in zip(villagers, column):
            v.traits[cat] = value
    counts = Counter(map(_look, villagers))
    swaps = len(villagers) * 20
    while swaps > 0:
        clashing = [v for v in villagers if counts[_look(v)] > 1]
        if not clashing:
            return
        for a in clashing[:swaps]:
            if counts[_look(a)] < 2:
                continue
            b, cat = rng.choice(villagers), rng.choice(list(TRAITS))
            counts.subtract((_look(a), _look(b)))
            a.traits[cat], b.traits[cat] = b.traits[cat], a.traits[cat]
            counts.update((_look(a), _look(b)))
            swaps -= 1


def describe(traits: dict[str, str]) -> str:
    """The traits as a witness would put them, e.g. "tall, bald, in a grey hoodie, with a bicycle"."""
    return ", ".join(PHRASES[c].format(traits[c]) for c in TRAITS if c in traits)


def face(traits: dict[str, str]) -> dict:
    """What the page needs to draw a face that matches the traits: hair and coat colours, and height 0 to 2."""
    height = traits.get("height")
    return {"hair": COLOURS.get(traits.get("hair")), "coat": COLOURS.get(traits.get("coat")),
            "height": TRAITS["height"].index(height) if height in TRAITS["height"] else 1}
