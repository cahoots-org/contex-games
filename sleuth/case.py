"""Staging a petty crime from where the town expects its residents to be, and the evidence it leaves."""

import re
from dataclasses import dataclass, field
from random import Random

from sleuth.lineage import Ids
from sleuth.town import STREETS, Town
from sleuth.traits import describe

TEMPLATES = {"steal": ("stole", ("bike", "tote bag", "thermos")), "vandalize": ("vandalized", ("car", "bike")),
             "sabotage": ("sabotaged", ("county fair pumpkin", "prize jam", "fair quilt"))}
PHASE_MINUTES = {"morning": (420, 720), "afternoon": (720, 1020), "evening": (1020, 1320), "night": (1320, 1740)}
MOTIVE_WEIGHT = 3
CAMERA_PLACES = ("grocery", "bar", "town hall", "elm street")
LOG_PLACES = {"gym": "Gym check-in", "bar": "Bar tab closed", "grocery": "Grocery receipt", "library": "Library checkout"}
MAX_WITNESSES = 2
WITNESS_TRAITS = 2
CLIP_TRAITS = ("height", "coat")
WITNESS_ACTION = {"steal": "walked off with something", "vandalize": "was bent over something",
                  "sabotage": "was fiddling with something"}
WITNESS_DRIFT = 20


@dataclass
class Crime:
    id: str
    template: str
    item: str
    culprit: str
    victim: str
    place: str
    day: int
    phase: str
    minute: int
    motive: str  # "rival" | "grudge" | "opportunity"
    text: str  # public news line
    owner: str | None = None  # a private guided case's player


@dataclass
class Record:
    id: str
    case: str
    kind: str  # "memory" | "clip" | "log" | "statement"
    place: str
    clock: str
    text: str
    holder: str = ""  # vid who saw or said it ("" for place records)
    traits: dict[str, str] = field(default_factory=dict)  # what was seen
    who: str | None = None  # a log's named resident
    sound: bool = True  # traces to the truth
    utterance: str | None = None  # memory: its delivered utterance id; statement: source record id


def clock_at(minute: int) -> str:
    """Minutes since midnight as a twelve-hour time, like "11:42pm"."""
    hour, mins = divmod(minute % 1440, 60)
    return f"{(hour - 1) % 12 + 1}:{mins:02d}{'am' if hour < 12 else 'pm'}"


def when(phase: str) -> str:
    return "last night" if phase == "night" else f"this {phase}"


def at(place: str) -> str:
    return f"on {place}" if place in STREETS else f"at the {place}"


def _motive(culprit, victim) -> str:
    if culprit.warmth.get(victim.id, 0.0) < 0:
        return "rival"
    first = re.escape(victim.name.split()[0])
    return "grudge" if re.search(rf"\b{first}\b", culprit.grudge, re.IGNORECASE) else "opportunity"


def stage_crime(town: Town, routine, rng: Random, day: int, phase: str, case_id: str, *,
                places=None, exclude=frozenset()) -> Crime | None:
    """Draw a culprit and a victim from different households, the culprit expected elsewhere; None if none fit."""
    residents = [v for v in town.villagers if v.id not in exclude and routine.place(v.id, phase) is not None]
    pairs = [(c, w, _motive(c, w)) for w in residents for c in residents
             if c.household != w.household
             and (places is None or routine.place(w.id, phase) in places)
             and routine.place(c.id, phase) != routine.place(w.id, phase)]
    if not pairs:
        return None
    culprit, victim, motive = rng.choices(pairs, [1 if m == "opportunity" else MOTIVE_WEIGHT for *_, m in pairs])[0]
    template = rng.choice(list(TEMPLATES))
    verb, items = TEMPLATES[template]
    item = rng.choice(items)
    minute = rng.randrange(*PHASE_MINUTES[phase])
    place = routine.place(victim.id, phase)
    return Crime(case_id, template, item, culprit.id, victim.id, place, day, phase, minute, motive,
                 f"Someone {verb} {victim.name}'s {item} {at(place)} {when(phase)}.")


def record_json(r: Record, town: Town) -> dict:
    """What the player sees of a record."""
    return {"id": r.id, "kind": r.kind, "place": r.place, "clock": r.clock, "text": r.text,
            "from": town.get(r.holder).name if r.holder else ""}


def _memory(crime: Crime, witness: str, seen: dict[str, str], rng: Random, ids: Ids) -> Record:
    lo, hi = PHASE_MINUTES[crime.phase]
    clock = clock_at(min(max(crime.minute + rng.randint(-WITNESS_DRIFT, WITNESS_DRIFT), lo), hi - 1))
    text = f"Around {clock}, {at(crime.place)}, someone {describe(seen)} {WITNESS_ACTION[crime.template]}."
    return Record(ids.next("r"), crime.id, "memory", crime.place, clock, text, witness, seen)


def _bystanders(crime: Crime, town: Town, routine) -> list[str]:
    return [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim)
            and routine.place(v.id, crime.phase) == crime.place]


def witness_memories(crime: Crime, town: Town, routine, rng: Random, ids: Ids) -> list[Record]:
    """Up to MAX_WITNESSES residents expected at the scene, each recalling two of the culprit's traits."""
    bystanders = _bystanders(crime, town, routine)
    culprit = town.get(crime.culprit).traits
    memories = []
    for w in rng.sample(bystanders, min(MAX_WITNESSES, len(bystanders))):
        seen = {c: culprit[c] for c in rng.sample(list(culprit), WITNESS_TRAITS)}
        memories.append(_memory(crime, w, seen, rng, ids))
    return memories


def camera_clip(crime: Crime, town: Town, ids: Ids, traits: tuple[str, ...] = CLIP_TRAITS) -> Record | None:
    """The scene's camera footage at the crime minute, if the place has a camera."""
    if crime.place not in CAMERA_PLACES:
        return None
    culprit = town.get(crime.culprit).traits
    seen = {c: culprit[c] for c in traits}
    clock = clock_at(crime.minute)
    text = f"{clock}, {crime.place} camera: a figure {describe(seen)} {WITNESS_ACTION[crime.template]}."
    return Record(ids.next("r"), crime.id, "clip", crime.place, clock, text, traits=seen)


def logs(crime: Crime, phase_log: dict[str, list[str]], town: Town, rng: Random, ids: Ids) -> list[Record]:
    """A check-in, tab or receipt for every resident who passed through a logging place this phase."""
    records = []
    for vid, places in phase_log.items():
        for place in dict.fromkeys(places):
            if place in LOG_PLACES:
                clock = clock_at(rng.randrange(*PHASE_MINUTES[crime.phase]))
                text = f"{LOG_PLACES[place]}: {town.get(vid).name}, {clock}"
                records.append(Record(ids.next("r"), crime.id, "log", place, clock, text, who=vid))
    return records


def suspects(crime: Crime, records: list[Record], town: Town) -> set[str]:
    """Residents who match every sighting and are not logged only elsewhere."""
    sightings = [r.traits for r in records if r.kind in ("memory", "clip")]
    logged = [r for r in records if r.kind == "log"]
    at_scene = {r.who for r in logged if r.place == crime.place}
    alibied = {r.who for r in logged if r.place != crime.place} - at_scene
    return {v.id for v in town.villagers if v.id != crime.victim and v.id not in alibied
            and all(seen.items() <= v.traits.items() for seen in sightings)}


def make_solvable(crime: Crime, records: list[Record], town: Town, routine, rng: Random, ids: Ids) -> list[Record] | None:
    """The extra memory that narrows the case to the culprit: [] if none is needed, None if none can."""
    left = suspects(crime, records, town)
    if left == {crime.culprit}:
        return []
    if crime.culprit not in left:
        return None
    culprit = town.get(crime.culprit).traits
    seen: dict[str, str] = {}
    while len(left) > 1:
        unseen = [c for c in culprit if c not in seen]
        if not unseen:
            return None
        best = max(unseen, key=lambda c: sum(town.get(s).traits.get(c) != culprit[c] for s in left))
        narrowed = {s for s in left if town.get(s).traits.get(best) == culprit[best]}
        if narrowed == left:
            return None
        seen[best], left = culprit[best], narrowed
    seen_by = {r.holder for r in records if r.kind == "memory"}
    others = [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim)]
    witness = next((w for w in _bystanders(crime, town, routine) + others if w not in seen_by), None)
    return None if witness is None else [_memory(crime, witness, seen, rng, ids)]
