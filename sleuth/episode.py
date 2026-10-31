"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import LOG_NOUNS, TRACES, Crime, Record, points_at
from sleuth.town import Town, at
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


# What a record that disproves a false piece is called to a podcaster who never found it.
SOURCES = {"clip": "camera", "log": "log", "memory": "witness", "clue": "trace"}
# The nouns that open a trace's text, e.g. "A boot print", and the receipt.
TRACE_NOUNS = [t.split(" {")[0] for t in TRACES.values()] + ["A grocery receipt"]


def label(r: Record, crime: Crime, town: Town) -> str:
    """A record as a podcaster would point at it, never naming the culprit."""
    first = "someone" if r.holder == crime.culprit else (town.name_of(r.holder) or "someone").split()[0]
    if r.kind == "memory":
        return f"{first}'s {next(iter(r.traits.values()), 'account')}"
    if r.kind == "clue":
        noun = next((n for n in TRACE_NOUNS if r.text.startswith(n)), "A trace")
        return f"the {noun.removeprefix('A grocery ').removeprefix('A ').lower()} {at(r.place)}"
    if r.kind == "clip":
        return f"the {r.place} camera"
    if r.kind == "log":
        return f"the {r.place}'s {LOG_NOUNS[r.place]}"
    return f"{first}'s word"


def disproof_label(fake: Record, proof: Record, crime: Crime, town: Town) -> str:
    """The record that disproves a false piece; a camera is named with the look it shows."""
    shown = next((proof.traits[c] for c in fake.traits if c in proof.traits), None)
    if proof.kind == "clip" and shown:
        return f"{label(proof, crime, town)} shows a {shown}"
    return label(proof, crime, town)


def why_wrong(crime: Crime, named: str, cited: list[Record], notebook: dict[str, Record], town: Town,
              records: dict[str, Record]) -> str:
    """One sentence on why an episode failed, never naming the culprit or saying whether the one named is: the first
    false piece cited and what disproves it, else that the evidence doesn't point at them. The notebook holds the
    podcaster's records and records all the case's, which tell the source of a disproof they never found."""
    fake = next((r for r in cited if not r.sound), None)
    if fake is not None:
        if fake.disproof is None:
            return f"{label(fake, crime, town)}: someone's account says otherwise."
        if fake.disproof in notebook:
            return f"{label(fake, crime, town)}: {disproof_label(fake, notebook[fake.disproof], crime, town)}."
        source = SOURCES.get(records[fake.disproof].kind if fake.disproof in records else "", "account")
        return f"{label(fake, crime, town)}: a {source} says otherwise."
    return f"Your evidence doesn't point at {town.name_of(named)}."
