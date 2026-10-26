"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import Crime, Record

MAX_CITED = 5


def holds(crime: Crime, culprit: str, cited: list[Record]) -> bool:
    """Right when it names the culprit and cites only sound evidence from this case."""
    return culprit == crime.culprit and bool(cited) and all(r.case == crime.id and r.sound for r in cited)
