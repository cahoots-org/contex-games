"""How each resident looks: what a witness can see, never a name."""

import random
from collections import Counter
from itertools import product

from sleuth.models import Villager
from sleuth.town import place_name

TRAITS: dict[str, tuple[str, ...]] = {
    "gender": ("man", "woman"),
    "height": ("short", "average height", "tall"),
    "hair": ("grey-haired", "blond", "dark-haired", "red-haired", "bald"),
    "coat": ("grey hoodie", "denim jacket", "green raincoat", "black puffer", "plaid flannel"),
    "car": ("red pickup", "white sedan", "blue hatchback", "silver minivan", "bicycle"),
}
# What never changes about a resident; the coat is the day's outfit, picked from a wardrobe of WARDROBE.
FIXED = ("gender", "height", "hair", "car")
# Gender comes with the resident; the rest of the fixed traits are dealt.
GIVEN = ("gender",)
DEALT = tuple(c for c in FIXED if c not in GIVEN)
WARDROBE = 3
# What talking to someone shows of them, and what someone who knows them can put into words.
IN_PERSON = ("gender", "height", "hair", "coat")
BY_WORD = ("height", "hair", "car")
PHRASES = {"gender": "a {}", "height": "{}", "hair": "{}", "coat": "in a {}", "car": "with a {}"}
# What a witness can notice of someone: their traits, and the street they headed toward.
SEEN_AS = ("gender", "height", "hair", "coat", "car", "headed")
# What a witness can say loosely, and the trait values each phrase covers.
RANGES: dict[str, tuple[str, ...]] = {
    "not tall": ("short", "average height"),
    "not short": ("average height", "tall"),
    "darkish-haired": ("dark-haired", "red-haired"),
    "fair-haired": ("blond", "grey-haired"),
    "in a dark coat": ("black puffer", "denim jacket", "grey hoodie"),
    "in a bright coat": ("green raincoat", "plaid flannel"),
    "with a car": ("red pickup", "white sedan", "blue hatchback", "silver minivan"),
}
COLOURS = {
    "grey-haired": "#9a9a9a", "blond": "#e0c77a", "dark-haired": "#2b2118", "red-haired": "#b0482a", "bald": None,
    "grey hoodie": "#8a8d91", "denim jacket": "#3d5f8a", "green raincoat": "#4f8a3e", "black puffer": "#25272b",
    "plaid flannel": "#9a3a30",
}


def _look(v: Villager) -> tuple[str, ...]:
    return tuple(v.traits[c] for c in FIXED)


def assign_traits(villagers: list[Villager], rng: random.Random) -> None:
    """Keep each resident's gender, deal the other fixed categories evenly, swap values until every fixed look is
    unique or the swaps run out, and give each resident a wardrobe."""
    for v in villagers:
        v.traits = {c: v.traits[c] for c in GIVEN if c in v.traits}
        v.wardrobe = rng.sample(TRAITS["coat"], WARDROBE)
    for cat in FIXED:
        dealt = [v for v in villagers if cat not in v.traits]
        if not dealt:
            continue
        order = rng.sample(TRAITS[cat], len(TRAITS[cat]))
        column = [order[i % len(order)] for i in range(len(dealt))]
        rng.shuffle(column)
        for v, value in zip(dealt, column):
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
            b, cat = rng.choice(villagers), rng.choice(DEALT)
            counts.subtract((_look(a), _look(b)))
            a.traits[cat], b.traits[cat] = b.traits[cat], a.traits[cat]
            counts.update((_look(a), _look(b)))
            swaps -= 1


def fits(seen: dict[str, str], looks: dict[str, str]) -> bool:
    """Whether every sighting is exactly the look's value or a range covering it."""
    return all(value == looks.get(c) or looks.get(c) in RANGES.get(value, ()) for c, value in seen.items())


def assign_look(v: Villager, others: list[Villager], rng: random.Random, avoid: list[dict[str, str]] = ()) -> None:
    """Give one resident, keeping their gender, fixed traits no one else's fixed look has and fitting none of the
    sightings to avoid, as far as one is left, and a wardrobe."""
    taken = {tuple(o.traits.get(c) for c in FIXED) for o in others}
    sightings = [{c: s[c] for c in FIXED if c in s} for s in avoid]
    kept = {c: v.traits[c] for c in GIVEN if c in v.traits}
    looks = [dict(zip(FIXED, look)) for look in product(*(TRAITS[c] for c in FIXED))]
    looks = [look for look in looks if kept.items() <= look.items()]
    free = [look for look in looks if tuple(look.values()) not in taken]
    clear = [look for look in free if not any(s and fits(s, look) for s in sightings)]
    v.traits = rng.choice(clear or free or looks)
    v.wardrobe = rng.sample(TRAITS["coat"], WARDROBE)


def describe(traits: dict[str, str]) -> str:
    """The traits as a witness would put them, e.g. "tall, bald, in a grey hoodie, with a bicycle"."""
    said = [traits[c] if traits[c] in RANGES else PHRASES[c].format(traits[c]) for c in TRAITS if c in traits]
    if "headed" in traits:
        said.append(f"headed toward {place_name(traits['headed'])}")
    return ", ".join(said)


def figure(traits: dict[str, str]) -> str:
    """The traits around "figure", e.g. "a tall, bald figure in a grey hoodie, with a bicycle"."""
    looks = [traits[c].replace(" ", "-") for c in ("height", "hair") if c in traits]
    gear = describe({c: traits[c] for c in ("coat", "car") if c in traits})
    words = ", ".join(looks) + " figure" if looks else "figure"
    article = "an" if words[0] in "aeiou" else "a"
    return f"{article} {words} {gear}".rstrip()


def face(traits: dict[str, str]) -> dict:
    """What the page needs to draw a face that matches the traits: hair and coat colours, and height 0 to 2."""
    height = traits.get("height")
    return {"hair": COLOURS.get(traits.get("hair")), "coat": COLOURS.get(traits.get("coat")),
            "height": TRAITS["height"].index(height) if height in TRAITS["height"] else 1}
