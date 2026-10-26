"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import Crime, Record

MAX_CITED = 5


def points_at(crime: Crime, culprit: str, traits: dict[str, str], r: Record) -> bool:
    """Whether a record singles out the culprit: a sighting that fits them or a log at the scene. A housemate's "I was
    asleep" says the same of everyone, so it points at no one."""
    if r.kind in ("memory", "clip"):
        return bool(r.traits) and r.traits.items() <= traits.items()
    return r.kind == "log" and r.who == culprit and r.place == crime.place


def holds(crime: Crime, culprit: str, traits: dict[str, str], cited: list[Record]) -> bool:
    """Right when it names the culprit, cites only sound evidence from this case, and some of it points at them."""
    return (culprit == crime.culprit and all(r.case == crime.id and r.sound for r in cited)
            and any(points_at(crime, culprit, traits, r) for r in cited))
