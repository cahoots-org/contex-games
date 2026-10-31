"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import Crime, Record, points_at
from sleuth.traits import RANGES

MAX_CITED = 5


def covers(value: str) -> set[str]:
    """The exact values a trait value stands for."""
    return set(RANGES.get(value, (value,)))


def contradicts(a: Record, b: Record) -> bool:
    """Whether one disproves the other, or they give a trait no single look could fit both of."""
    return (a.disproof == b.id or b.disproof == a.id
            or any(not covers(a.traits[c]) & covers(b.traits[c]) for c in a.traits.keys() & b.traits.keys()))


def holds(crime: Crime, culprit: str, traits: dict[str, str], cited: list[Record]) -> bool:
    """Right when it names the culprit, cites evidence from this case, some sound piece points at them, and at most
    one cited piece is unsound, clashing with nothing else cited."""
    stray = [r for r in cited if not r.sound]
    clash = any(contradicts(stray[0], r) for r in cited if r is not stray[0]) if stray else False
    return (culprit == crime.culprit and all(r.case == crime.id for r in cited) and len(stray) <= 1 and not clash
            and any(r.sound and points_at(crime, culprit, traits, r) for r in cited))
