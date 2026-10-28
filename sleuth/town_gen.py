"""Generate the village: Haiku writes the people, code wires who knows whom."""

import json
import os
import random
import re
from dataclasses import asdict

from sleuth.models import Villager
from sleuth.faith import FAITH, GORE
from sleuth.town import STREETS
from sleuth.traits import assign_traits
from sleuth.writer import Writer, extract_json

BATCH = 10
MAX_FAILED_BATCHES = 5
REQUIRED = ("name", "occupation", "personality", "grudge", "needs", "quirks")
MAX_RELATIONSHIPS = 4
REVERSE = {"parent": "child", "child": "parent"}
# Weighted draw, so friends are commoner than the rest.
KINDS = ["friend", "friend", "coworker", "neighbor", "rival"]
# How many residents must be on bad terms with someone for them to have that many people with a motive, and one
# resident in how many is.
RIVALS = 2
RIVALED_EVERY = 5
# (kind, size, tie, weight); a pair tie is the same both ways unless given as (first's, second's).
HOUSEHOLDS = (
    ("alone", 1, None, 3), ("married", 2, "spouse", 3), ("partners", 2, "partner", 2),
    ("roommates", 2, "roommate", 2), ("parent and adult child", 2, ("parent", "child"), 1),
    ("siblings", 2, "sibling", 1),
)
WARMTH = {
    "spouse": (0.7, 1.0), "partner": (0.6, 0.95), "parent": (0.5, 0.9), "child": (0.5, 0.9),
    "sibling": (0.4, 0.9), "roommate": (0.2, 0.6), "friend": (0.4, 0.8), "coworker": (0.1, 0.5),
    "neighbor": (0.0, 0.4), "rival": (-0.9, -0.4),
}

SYSTEM = "You invent residents of a small modern American town. Reply with only JSON, no prose."
PROMPT = (
    "Invent {n} distinct residents as a top-level JSON array of objects, not wrapped in "
    "another object. Each item has: name (a full name), occupation, personality (one "
    "short phrase), grudge (a string, empty for most residents), and needs: a JSON array of 3 to 5 strings, each one sentence in the resident's own voice "
    "about news they would prick up their ears at: one about their work, one about a "
    "person they love or resent, one about their standing or money, and one about an odd "
    "fascination or fear of their own (break-ins, layoffs, gossip, their health, the town "
    "changing, or anything else). Make needs particular to this person and "
    "different from the other residents', never generic topics like news or gossip. "
    "quirks: a JSON array of 1 or 2 short phrases, each a strong, harmless obsession or habit that shows whenever "
    'they talk, such as "convinced the dog-park goose is plotting something", "a would-be true-crime expert" or '
    '"blames the town council for everything". '
    "Leave faith out: nothing about anyone, their work, places, grudges or needs may touch on faith or spirituality. "
    "{temper}{taken}"
)
GOOD = (
    "good-natured, with a temperament such as warm, curious, cheerful, timid, nosy, "
    'absent-minded, or kindly, and an empty grudge ""'
)
SOUR = (
    "sour, with a grudge: one sentence about someone or something they resent. Sour residents "
    "are the town's skeptics, quick to doubt, deny, or mock what they hear, and their "
    "personality shows it"
)
MIX = f"Most residents are {GOOD}; vary their temperaments. Roughly one resident in five is {SOUR}. "
SOUR_SHARE = 0.2
# How many replies are asked for one new resident with a first name no one has.
RESIDENT_TRIES = 3


BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s*")


def _split_needs(text: str) -> list[str]:
    """Split a needs string on newlines and semicolons, else on sentence ends."""
    parts = re.split(r"[\n;]+", text)
    if len(parts) < 2:
        parts = re.split(r"(?<=[.!?])\s+", text)
    return [p for p in (BULLET.sub("", part).strip() for part in parts) if p]


def _prepare(raw):
    """Turn a needs string into a list of needs; anything else passes through."""
    if isinstance(raw, dict) and isinstance(raw.get("needs"), str):
        raw = {**raw, "needs": _split_needs(raw["needs"])}
    return raw


def _unwrap(parsed):
    """The villager list from a bare array or an object holding a single list."""
    if isinstance(parsed, dict):
        lists = [v for v in parsed.values() if isinstance(v, list)]
        return lists[0] if len(lists) == 1 else None
    return parsed if isinstance(parsed, list) else None


def _valid(raw) -> bool:
    """True for a dict with every required key, 3 or more string needs, a quirk or more, and nothing of faith or anything grisly."""
    return (
        isinstance(raw, dict)
        and all(k in raw for k in REQUIRED)
        and isinstance(raw["needs"], list)
        and len(raw["needs"]) >= 3
        and all(isinstance(n, str) for n in raw["needs"])
        and isinstance(raw["quirks"], list)
        and len(raw["quirks"]) >= 1
        and all(isinstance(q, str) and q.strip() for q in raw["quirks"])
        and not FAITH.search(json.dumps(raw))
        and not GORE.search(json.dumps(raw))
    )


def _villager(vid: str, raw: dict) -> Villager:
    return Villager(
        id=vid, name=raw["name"], occupation=raw["occupation"],
        personality=raw["personality"], grudge=raw["grudge"] or "",
        needs=list(raw["needs"])[:5], relationships={}, quirks=raw["quirks"][:2],
    )


# Where new villages are saved, one file per world.
WORLDS_DIR = "sleuth_worlds"


def world_path(session: str, data_dir: str = "") -> str:
    """Where a new village for this session is saved, under the data directory."""
    return os.path.join(data_dir, WORLDS_DIR, f"{session}.json")


def _first(name: str) -> str:
    return name.split()[0].lower() if name.split() else ""


def _first_names_taken(villagers: list[Villager]) -> str:
    """The prompt line that keeps every first name in the village unique."""
    names = ", ".join(sorted({v.name.split()[0] for v in villagers if v.name.split()}))
    return f"Give each resident a first name no one else in town has; these are taken: {names}."


async def generate_villagers(writer: Writer, count: int, rng: random.Random) -> list[Villager]:
    """Ask Haiku for villagers in batches of 10, with ids v001... and no relationships.

    Gives up after MAX_FAILED_BATCHES replies in a row that add no villager.
    """
    villagers: list[Villager] = []
    failed = 0
    while len(villagers) < count and failed < MAX_FAILED_BATCHES:
        failed += 1
        n = min(BATCH, count - len(villagers))
        taken = ""
        if villagers:
            jobs = ", ".join(v.occupation for v in villagers[-30:])
            taken = f"Do not reuse these occupations: {jobs}. {_first_names_taken(villagers)}"
        text = await writer.complete(SYSTEM, PROMPT.format(n=n, temper=MIX, taken=taken), max_tokens=4000)
        try:
            parsed = extract_json(text)
        except ValueError:
            continue
        items = _unwrap(parsed)
        if items is None:
            continue
        used = {_first(v.name) for v in villagers}
        for raw in [r for r in map(_prepare, items) if _valid(r)]:
            if len(villagers) >= count or _first(raw["name"]) in used:
                continue
            used.add(_first(raw["name"]))
            villagers.append(_villager(f"v{len(villagers) + 1:03d}", raw))
            failed = 0
    if len(villagers) < count:
        raise ValueError(
            f"got {len(villagers)} of {count} residents after {MAX_FAILED_BATCHES} failed batches"
        )
    return villagers


async def generate_resident(writer: Writer, taken: list[Villager], rng: random.Random) -> Villager:
    """One new resident whose first name and id no one in taken has, with no ties; ValueError when every try fails."""
    temper = f"Make this resident {SOUR if rng.random() < SOUR_SHARE else GOOD}. "
    used = {_first(v.name) for v in taken}
    for _ in range(RESIDENT_TRIES):
        text = await writer.complete(SYSTEM, PROMPT.format(n=1, temper=temper, taken=_first_names_taken(taken)),
                                     max_tokens=800)
        try:
            parsed = extract_json(text)
        except ValueError:
            continue
        raw = _prepare(parsed[0] if isinstance(parsed, list) and parsed else parsed)
        if _valid(raw) and _first(raw["name"]) not in used:
            last = max((int(v.id[1:]) for v in taken if v.id[1:].isdigit()), default=0)
            return _villager(f"v{last + 1:03d}", raw)
    raise ValueError(f"no new resident in {RESIDENT_TRIES} tries")


def settle(v: Villager, villagers: list[Villager], home: str, rng: random.Random) -> None:
    """Give the resident a household of their own on home, a neighbor there with room for one, a rival who lacks
    RIVALS people on bad terms with them while too few residents have that many, and drawn ties up to two."""
    last = max((int(o.household[1:]) for o in villagers if o.household[1:].isdigit()), default=0)
    v.household, v.home = f"h{last + 1:02d}", home
    street = [o for o in villagers if o.home == home and o.id != v.id and len(o.relationships) < MAX_RELATIONSHIPS]
    if street:
        _tie(v, rng.choice(street), "neighbor", rng)
    if _short(villagers) > 0:
        others = [o for o in villagers if o.id != v.id and o.id not in v.relationships
                  and len(o.relationships) < MAX_RELATIONSHIPS and _bad_terms(o, villagers) < RIVALS]
        if others:
            _tie(v, max(others, key=lambda o: (_bad_terms(o, villagers), rng.random())), "rival", rng)
    while len(v.relationships) < 2 and (other := _partner(v, villagers, rng)):
        _link(v, other, rng)


def _tie(a: Villager, b: Villager, kind: str, rng: random.Random) -> None:
    """Tie a to b as kind, b back to a as its reverse, with one warmth drawn for both."""
    a.relationships[b.id], b.relationships[a.id] = kind, REVERSE.get(kind, kind)
    a.warmth[b.id] = b.warmth[a.id] = rng.uniform(*WARMTH[kind])


def _link(a: Villager, b: Villager, rng: random.Random) -> None:
    """Add a drawn reciprocal tie; neighbors on different streets are friends instead."""
    kind = rng.choice(KINDS)
    if kind == "neighbor" and a.home != b.home:
        kind = "friend"
    _tie(a, b, kind, rng)


def form_households(villagers: list[Villager], rng: random.Random) -> None:
    """Group residents into households of one or two, ids h01..., dealt round robin onto STREETS."""
    left = rng.sample(villagers, len(villagers))
    weights = [h[3] for h in HOUSEHOLDS]
    n = 0
    while left:
        _, size, tie, _ = rng.choices(HOUSEHOLDS, weights=weights)[0]
        members = [left.pop() for _ in range(min(size, len(left)))]
        n += 1
        for v in members:
            v.household, v.home = f"h{n:02d}", STREETS[(n - 1) % len(STREETS)]
        if len(members) == 2:
            _tie(*members, tie[0] if isinstance(tie, tuple) else tie, rng)


def _partner(v: Villager, villagers: list[Villager], rng: random.Random) -> Villager | None:
    """A random not-yet-related villager with room, preferring the least connected."""
    open_ = [
        o for o in villagers
        if o.id != v.id and o.id not in v.relationships
        and len(o.relationships) < MAX_RELATIONSHIPS
    ]
    if not open_:
        return None
    fewest = min(len(o.relationships) for o in open_)
    return rng.choice([o for o in open_ if len(o.relationships) == fewest])


def wire_relationships(villagers: list[Villager], rng: random.Random) -> None:
    """Give each villager 2-4 reciprocal relationships, and stir up rivalries.

    Fewer than 2 only when impossible: fewer than 3 villagers, or every other
    villager is already at the cap of 4 or related to them.
    """
    while True:
        lonely = [v for v in villagers if len(v.relationships) < 2]
        stuck = True
        for v in sorted(lonely, key=lambda v: len(v.relationships)):
            other = _partner(v, villagers, rng)
            if other and len(v.relationships) < 2:
                _link(v, other, rng)
                stuck = False
        if stuck:
            break
    for v in rng.sample(villagers, len(villagers)):
        other = _partner(v, villagers, rng)
        if len(v.relationships) < 3 and other and rng.random() < 0.5:
            _link(v, other, rng)
    stir_rivalries(villagers, rng)


def _bad_terms(v: Villager, villagers: list[Villager]) -> int:
    """How many of villagers v is on cold terms with."""
    ids = {o.id for o in villagers}
    return sum(w < 0 for o, w in v.warmth.items() if o in ids)


def _short(villagers: list[Villager]) -> int:
    """How many more residents should be on bad terms with RIVALS people."""
    return len(villagers) // RIVALED_EVERY - sum(_bad_terms(v, villagers) >= RIVALS for v in villagers)


def stir_rivalries(villagers: list[Villager], rng: random.Random) -> None:
    """Give one resident in RIVALED_EVERY RIVALS people on bad terms with them, the most feuding first: their friends,
    coworkers and neighbors turn rival, else a new rival is drawn."""
    by_id = {v.id: v for v in villagers}
    for v in sorted(villagers, key=lambda v: (-_bad_terms(v, villagers), rng.random())):
        if _short(villagers) <= 0:
            return
        while _bad_terms(v, villagers) < RIVALS:
            warm = [o for o, kind in v.relationships.items()
                    if kind in ("friend", "coworker", "neighbor") and v.warmth[o] >= 0 and o in by_id]
            room = len(v.relationships) < MAX_RELATIONSHIPS
            other = by_id[rng.choice(warm)] if warm else _partner(v, villagers, rng) if room else None
            if other is None:
                break
            _tie(v, other, "rival", rng)


class SeedMismatch(ValueError):
    """The seed file is not a village this game can use: another size, or one from before Sleuth or outfits."""


async def load_or_generate(
    path: str, writer: Writer, count: int, rng: random.Random,
) -> list[Villager]:
    """Load the seed file if present, else generate, settle, wire, and write it."""
    try:
        with open(path) as f:
            villagers = [Villager(**raw) for raw in json.load(f)]
    except FileNotFoundError:
        pass
    else:
        if any(not v.traits for v in villagers):
            raise SeedMismatch(f"{path} is a town from before Sleuth's; delete it")
        if any(not v.wardrobe for v in villagers):
            raise SeedMismatch(f"{path} is a town from before outfits; delete it")
        if len(villagers) != count:
            raise SeedMismatch(
                f"{path} has {len(villagers)} residents but population is {count}; "
                f"delete it or set SLEUTH_POPULATION={len(villagers)}"
            )
        return villagers
    villagers = await generate_villagers(writer, count, rng)
    form_households(villagers, rng)
    assign_traits(villagers, rng)
    wire_relationships(villagers, rng)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump([asdict(v) for v in villagers], f, indent=2)
    return villagers
