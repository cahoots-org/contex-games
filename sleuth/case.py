"""Staging a petty crime from where the town expects its residents to be, and the evidence it leaves."""

import re
from dataclasses import dataclass, field, replace
from random import Random

from sleuth.lineage import Ids
from sleuth.town import STREETS, Town, at, place_name
from sleuth.traits import describe, figure

TEMPLATES = {"steal": ("stole", ("bike", "tote bag", "thermos")), "vandalize": ("vandalized", ("car", "bike")),
             "sabotage": ("sabotaged", ("county-fair pumpkin", "county-fair jam", "county-fair quilt")),
             "dog": ("let out", ("dog",)), "trailer": ("drove off with", ("marching band trailer",))}
# Where each item plausibly is. Residents are on a street only at night, at home.
FAIR_PLACES = (*STREETS, "town hall", "library")
ITEM_PLACES = {"bike": (*STREETS, "gym", "school"), "tote bag": ("cafe", "gym", "library", "grocery"),
               "thermos": ("cafe", "gym", "school", "library"), "car": (*STREETS, "grocery", "hardware store", "gym", "bar"),
               "county-fair pumpkin": FAIR_PLACES, "county-fair jam": FAIR_PLACES, "county-fair quilt": FAIR_PLACES,
               "dog": STREETS, "marching band trailer": ("school",)}
FOUND = {"steal": "missing", "vandalize": "damaged", "sabotage": "spoiled", "dog": "loose", "trailer": "missing"}
# How many minutes after the crime the victim finds it.
NOTICED = (10, 45)
PHASE_MINUTES = {"morning": (420, 720), "afternoon": (720, 1020), "evening": (1020, 1320), "night": (1320, 1740)}
MOTIVE_WEIGHT = 3
# How often the culprit is someone expected at the scene anyway, when one fits.
REGULAR_CULPRIT = 1 / 3
CAMERA_PLACES = ("grocery", "bar", "town hall", "elm street")
LOG_PLACES = {"gym": "Gym check-in", "bar": "Bar tab closed", "grocery": "Grocery receipt", "library": "Library checkout"}
MAX_WITNESSES = 2
WITNESS_TRAITS = 2
CLIP_TRAITS = ("height", "coat")
WITNESS_ACTION = {"steal": "walked off with something", "vandalize": "was bent over something",
                  "sabotage": "was fiddling with something", "dog": "was opening a gate",
                  "trailer": "was hauling something off"}
WITNESS_DRIFT = 20
# What the culprit can leave behind: a trace of one trait, or a store receipt whose log names who paid.
TRACES = {"height": "A boot print {at}, left by {figure}.", "coat": "A thread {at}, snagged from {figure}.",
          "car": "Fresh tracks {at}, from a {value}."}
RECEIPT = "A grocery receipt dropped {at}, stamped {clock}."
# How many minutes before the crime a dropped receipt was stamped.
RECEIPT_BEFORE = (20, 180)
# Case text keeps the crime's time as WHEN, said relative to the day it is read.
WHEN = "{when}"
DAYS_AGO = ("two", "three", "four", "five", "six")
# A time as ago() or a resident says it.
SAID_TIME = re.compile(r"\b(?:this (?:morning|afternoon|evening)|tonight|last night|yesterday (?:morning|afternoon|evening)|"
                       r"\w+ days ago, (?:in the (?:morning|afternoon|evening)|at night))\b", re.IGNORECASE)


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
    kind: str  # "memory" | "discovery" | "clip" | "log" | "clue" | "statement"
    place: str
    clock: str
    text: str
    holder: str = ""  # vid who saw or said it ("" for place records)
    traits: dict[str, str] = field(default_factory=dict)  # what was seen
    who: str | None = None  # a log's named resident; whom a household word is about
    sound: bool = True  # traces to the truth
    utterance: str | None = None  # memory: its delivered utterance id; statement: source record id
    day: int = 0  # game day
    trail: bool = False  # a store log behind a receipt dropped at the scene


def clock_at(minute: int) -> str:
    """Minutes since midnight as a twelve-hour time, like "11:42pm"."""
    hour, mins = divmod(minute % 1440, 60)
    return f"{(hour - 1) % 12 + 1}:{mins:02d}{'am' if hour < 12 else 'pm'}"


def ago(day: int, phase: str, today: int) -> str:
    """When day's phase was, said on today: "this afternoon", "last night", "two days ago, in the evening"."""
    days = today - day
    if days <= 0:
        return "tonight" if phase == "night" else f"this {phase}"
    if days == 1:
        return "last night" if phase == "night" else f"yesterday {phase}"
    count = DAYS_AGO[days - 2] if days - 2 < len(DAYS_AGO) else str(days)
    return f"{count} days ago, " + ("at night" if phase == "night" else f"in the {phase}")


def when(crime: Crime, today: int | None = None) -> str:
    """When the crime happened, said on today, or on the crime's own day."""
    return ago(crime.day, crime.phase, crime.day if today is None else today)


def told(text: str, crime: Crime, today: int | None = None) -> str:
    """text with its WHEN said on today."""
    return text.replace(WHEN, when(crime, today))


def retime(text: str, said: str) -> str:
    """text, said about the case on some earlier day, with each time it gives replaced by said."""
    return SAID_TIME.sub(said, text)


def misdated(line: str, allowed: str) -> bool:
    """Whether the line gives a time allowed does not."""
    return any(t.lower() not in allowed.lower() for t in SAID_TIME.findall(line))


def motive_of(culprit, victim) -> str:
    if culprit.warmth.get(victim.id, 0.0) < 0:
        return "rival"
    first = re.escape(victim.name.split()[0])
    return "grudge" if re.search(rf"\b{first}\b", culprit.grudge, re.IGNORECASE) else "opportunity"


def stage_crime(town: Town, routine, rng: Random, day: int, phase: str, case_id: str, *,
                places=None, exclude=frozenset()) -> Crime | None:
    """Draw a crime, then a culprit and a victim from different households, the victim where the item plausibly is.
    About REGULAR_CULPRIT of the time, when one fits, the culprit is expected at the scene too, otherwise elsewhere;
    None if no crime fits."""
    residents = [v for v in town.villagers if v.id not in exclude and routine.place(v.id, phase) is not None]
    crimes = [(t, item) for t, (_, items) in TEMPLATES.items() for item in items]
    for template, item in rng.sample(crimes, len(crimes)):
        pairs = [(c, w, motive_of(c, w)) for w in residents for c in residents
                 if c.household != w.household
                 and routine.place(w.id, phase) in ITEM_PLACES[item]
                 and (places is None or routine.place(w.id, phase) in places)]
        if pairs:
            break
    else:
        return None
    regular = [p for p in pairs if routine.place(p[0].id, phase) == routine.place(p[1].id, phase)]
    away = [p for p in pairs if p not in regular]
    pairs = regular if regular and (not away or rng.random() < REGULAR_CULPRIT) else away
    culprit, victim, motive = rng.choices(pairs, [1 if m == "opportunity" else MOTIVE_WEIGHT for *_, m in pairs])[0]
    minute = rng.randrange(*PHASE_MINUTES[phase])
    place = routine.place(victim.id, phase)
    return Crime(case_id, template, item, culprit.id, victim.id, place, day, phase, minute, motive,
                 f"Someone {TEMPLATES[template][0]} {victim.name}'s {item} {at(place)} {WHEN}.")


def record_json(r: Record, town: Town, crime: Crime | None = None, today: int | None = None) -> dict:
    """What the player sees of a record, its case's time said on today."""
    text = told(r.text, crime, today) if crime else r.text
    return {"id": r.id, "kind": r.kind, "place": r.place, "day": r.day, "clock": r.clock, "text": text,
            "from": town.get(r.holder).name if r.holder else "", "holder": r.holder}


def _memory_text(crime: Crime, clock: str, seen: dict[str, str]) -> str:
    return f"Around {clock}, {at(crime.place)}, someone {describe(seen)} {WITNESS_ACTION[crime.template]}."


def _memory(crime: Crime, witness: str, seen: dict[str, str], rng: Random, ids: Ids) -> Record:
    lo, hi = PHASE_MINUTES[crime.phase]
    clock = clock_at(min(max(crime.minute + rng.randint(-WITNESS_DRIFT, WITNESS_DRIFT), lo), hi - 1))
    return Record(ids.next("r"), crime.id, "memory", crime.place, clock, _memory_text(crime, clock, seen), witness, seen,
                  day=crime.day)


def recall_more(crime: Crime, memory: Record, culprit: dict[str, str]) -> Record:
    """The memory with one more of the culprit's traits, unnumbered, or as it was when it already has them all."""
    extra = next((c for c in culprit if c not in memory.traits), None)
    if extra is None:
        return replace(memory)
    seen = {**memory.traits, extra: culprit[extra]}
    return replace(memory, id="", traits=seen, text=_memory_text(crime, memory.clock, seen))


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


def discovery(crime: Crime, town: Town, rng: Random, ids: Ids) -> Record:
    """The victim finding the crime a little after it, which says nothing of who did it."""
    clock = clock_at(min(crime.minute + rng.randint(*NOTICED), PHASE_MINUTES[crime.phase][1] - 1))
    text = f"Around {clock}, {town.get(crime.victim).name} found the {crime.item} {FOUND[crime.template]} {at(crime.place)}."
    return Record(ids.next("r"), crime.id, "discovery", crime.place, clock, text, crime.victim, day=crime.day)


def found_it(crime: Crime, clock: str) -> str:
    """The discovery in the victim's own words."""
    return f"Around {clock}, I found my {crime.item} {FOUND[crime.template]} {at(crime.place)}."


def camera_clip(crime: Crime, town: Town, ids: Ids, traits: tuple[str, ...] = CLIP_TRAITS) -> Record | None:
    """The scene's camera footage at the crime minute, if the place has a camera."""
    if crime.place not in CAMERA_PLACES:
        return None
    culprit = town.get(crime.culprit).traits
    seen = {c: culprit[c] for c in traits}
    clock = clock_at(crime.minute)
    text = f"{clock}, {place_name(crime.place)} camera: {figure(seen)} {WITNESS_ACTION[crime.template]}."
    return Record(ids.next("r"), crime.id, "clip", crime.place, clock, text, traits=seen, day=crime.day)


def scene_clues(crime: Crime, town: Town, routine, rng: Random, ids: Ids) -> list[Record]:
    """One or two things left at the scene: a trace of one of the culprit's traits, or a receipt dropped by the
    culprit or someone expected there. A receipt names no one; the grocery's log for its time, returned with it,
    names who paid."""
    culprit = town.get(crime.culprit).traits
    clues: list[Record] = []
    for kind in rng.sample([*TRACES, "receipt"], rng.randint(1, 2)):
        if kind == "receipt":
            who = rng.choice([crime.culprit, *_bystanders(crime, town, routine)])
            clock = clock_at(crime.minute - rng.randint(*RECEIPT_BEFORE))
            text = RECEIPT.format(at=at(crime.place), clock=clock)
            clues.append(Record(ids.next("r"), crime.id, "clue", crime.place, clock, text, day=crime.day))
            paid = f"{LOG_PLACES['grocery']}: {town.get(who).name}, {clock}"
            clues.append(Record(ids.next("r"), crime.id, "log", "grocery", clock, paid, who=who, trail=True,
                                day=crime.day))
        else:
            seen = {kind: culprit[kind]}
            text = TRACES[kind].format(at=at(crime.place), figure=figure(seen), value=seen[kind])
            clues.append(Record(ids.next("r"), crime.id, "clue", crime.place, "", text, traits=seen, day=crime.day))
    return clues


def logs(crime: Crime, phase_log: dict[str, list[str]], town: Town, rng: Random, ids: Ids) -> list[Record]:
    """A check-in, tab or receipt for every resident who passed through a logging place this phase."""
    records = []
    for vid, places in phase_log.items():
        for place in dict.fromkeys(places):
            if place in LOG_PLACES:
                clock = clock_at(rng.randrange(*PHASE_MINUTES[crime.phase]))
                text = f"{LOG_PLACES[place]}: {town.get(vid).name}, {clock}"
                records.append(Record(ids.next("r"), crime.id, "log", place, clock, text, who=vid,
                                      day=crime.day))
    return records


def points_at(crime: Crime, culprit: str, traits: dict[str, str], r: Record) -> bool:
    """Whether a record singles out the culprit: a sighting or trace that fits them, or a log that puts them at the
    scene or behind a receipt left there. A housemate's "I was asleep" says the same of everyone, so it points at no one."""
    if r.kind in ("memory", "clip", "clue") and r.traits:
        return r.traits.items() <= traits.items()
    return r.kind == "log" and r.who == culprit and (r.place == crime.place or r.trail)


def suspects(crime: Crime, records: list[Record], town: Town) -> set[str]:
    """Residents who match every sighting and trace and are not logged only elsewhere."""
    sightings = [r.traits for r in records if r.kind in ("memory", "clip", "clue")]
    logged = [r for r in records if r.kind == "log" and not r.trail]
    at_scene = {r.who for r in logged if r.place == crime.place}
    alibied = {r.who for r in logged if r.place != crime.place} - at_scene
    return {v.id for v in town.villagers if v.id != crime.victim and v.id not in alibied
            and all(seen.items() <= v.traits.items() for seen in sightings)}


def make_solvable(crime: Crime, records: list[Record], town: Town, routine, rng: Random, ids: Ids) -> list[Record] | None:
    """The extra memory that narrows the case to the culprit and points at them: [] if none is needed, None if none
    can."""
    left = suspects(crime, records, town)
    if crime.culprit not in left:
        return None
    culprit = town.get(crime.culprit).traits
    seen: dict[str, str] = {}
    pointing = any(r.sound and points_at(crime, crime.culprit, culprit, r) for r in records)
    while len(left) > 1 or not (seen or pointing):
        unseen = [c for c in culprit if c not in seen]
        if not unseen:
            return None
        best = max(unseen, key=lambda c: sum(town.get(s).traits.get(c) != culprit[c] for s in left))
        narrowed = {s for s in left if town.get(s).traits.get(best) == culprit[best]}
        if narrowed == left and len(left) > 1:
            return None
        seen[best], left = culprit[best], narrowed
    if not seen:
        return []
    seen_by = {r.holder for r in records if r.kind == "memory"}
    others = [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim)]
    witness = next((w for w in _bystanders(crime, town, routine) + others if w not in seen_by), None)
    return None if witness is None else [_memory(crime, witness, seen, rng, ids)]
