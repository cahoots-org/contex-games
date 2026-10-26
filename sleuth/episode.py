"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import Crime, Record, points_at

MAX_CITED = 5


def holds(crime: Crime, culprit: str, traits: dict[str, str], cited: list[Record]) -> bool:
    """Right when it names the culprit, cites only sound evidence from this case, and some of it points at them."""
    return (culprit == crime.culprit and all(r.case == crime.id and r.sound for r in cited)
            and any(points_at(crime, culprit, traits, r) for r in cited))
