"""The judge: whether a podcaster's episode holds up."""

from sleuth.case import LOG_NOUNS, TRACES, Crime, Record, points_at
from sleuth.town import Town, at, place_name
from sleuth.traits import RANGES, figure

MAX_CITED = 5
# The records that show how the figure looked; a description says how some resident looks.
SIGHTINGS = {"memory", "clip", "clue"}


def covers(value: str) -> set[str]:
    """The exact values a trait value stands for."""
    return set(RANGES.get(value, (value,)))


def contradicts(a: Record, b: Record) -> bool:
    """Whether one disproves the other, or they are sightings giving a trait no single look could fit both of."""
    shared = a.traits.keys() & b.traits.keys() if {a.kind, b.kind} <= SIGHTINGS else set()
    return (a.disproof == b.id or b.disproof == a.id
            or any(not covers(a.traits[c]) & covers(b.traits[c]) for c in shared))


def holds(crime: Crime, culprit: str, traits: dict[str, str], cited: list[Record]) -> bool:
    """Right when it names the culprit, cites evidence from this case, some sound piece points at them, and at most
    one cited piece is unsound, clashing with nothing else cited."""
    stray = [r for r in cited if not r.sound]
    clash = len(stray) == 1 and any(contradicts(stray[0], r) for r in cited if r is not stray[0])
    return (culprit == crime.culprit and all(r.case == crime.id for r in cited) and len(stray) <= 1 and not clash
            and any(r.sound and points_at(crime, culprit, traits, r) for r in cited))


# What a record that disproves a false piece is called to a podcaster who never found it.
SOURCES = {"clip": "a camera", "log": "a log", "memory": "a witness", "clue": "a trace"}
# The nouns that open a trace's text, e.g. "A boot print", and the receipt.
TRACE_NOUNS = [t.split(" {")[0] for t in TRACES.values()] + ["A grocery receipt"]
# What a camera or trace shows of one trait, after "shows".
SHOWS = {"gender": "a {}", "height": "someone {}", "hair": "someone {}", "coat": "a {}", "car": "a {}"}


def label(r: Record, town: Town) -> str:
    """A record as a podcaster would point at it, its holder by first name."""
    first = (town.name_of(r.holder) or "someone").split()[0]
    if r.kind == "memory":
        headed = f" headed toward {place_name(r.traits['headed'])}" if "headed" in r.traits else ""
        return f"{first}'s sighting of {figure(r.traits)}{headed}"
    if r.kind == "clue":
        noun = next((n for n in TRACE_NOUNS if r.text.startswith(n)), "A trace")
        return f"the {noun.removeprefix('A grocery ').removeprefix('A ').lower()} {at(r.place)}"
    if r.kind == "clip":
        return f"the {place_name(r.place)} camera"
    if r.kind == "log":
        return f"the {r.place}'s {LOG_NOUNS[r.place]}"
    return f"{first}'s word"


def disproof_label(fake: Record, proof: Record, town: Town) -> str:
    """The record that disproves a false piece and what it shows: a camera or trace the look, a log who it puts there
    or that it leaves out the one the piece is about."""
    said = label(proof, town)
    shown = next((c for c in fake.traits if c in proof.traits), None)
    if proof.kind in ("clip", "clue") and shown:
        return f"{said} shows {SHOWS[shown].format(proof.traits[shown])}"
    about = fake.who or fake.holder
    if proof.kind == "log" and about and proof.who != about:
        return f"{said} don't have {town.name_of(about)}"
    if proof.kind == "log":
        return f"{said} put {town.name_of(proof.who)} there at {proof.clock}"
    return said


def why_wrong(named: str, cited: list[Record], notebook: dict[str, Record], town: Town,
              records: dict[str, Record]) -> str:
    """One sentence on why an episode failed, never saying whether the one named did it: the first false piece cited
    and what disproves it, else that the evidence doesn't point at them. The notebook holds the podcaster's records and
    records all the case's, which tell the source of a disproof they never found."""
    fake = next((r for r in cited if not r.sound), None)
    if fake is None:
        return f"Your evidence doesn't point at {town.name_of(named)}."
    piece = label(fake, town)
    piece = piece[0].upper() + piece[1:]
    if fake.disproof is None:
        return f"{piece}: it doesn't hold up."
    if fake.disproof in notebook:
        return f"{piece}: {disproof_label(fake, notebook[fake.disproof], town)}."
    source = SOURCES.get(records[fake.disproof].kind if fake.disproof in records else "", "an account")
    return f"{piece}: {source} says otherwise."
