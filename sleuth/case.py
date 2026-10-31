"""Staging a crime from where the town expects its residents to be, and the evidence it leaves."""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from random import Random

from sleuth.game import PHASES
from sleuth.lineage import Ids
from sleuth.town import PLACES, STREETS, Town, at, district_of, place_name
from sleuth.traits import RANGES, SEEN_AS, describe, figure, fits

TIERS = ("petty", "serious", "major")
NEWS = "Someone {did} {victim}'s {item} {at} {when}."
TITLE = "{victim}'s {item}"


@dataclass(frozen=True)
class Kind:
    tier: str
    did: str
    doing: str  # the same deed as a gerund
    items: tuple[str, ...]
    found: str  # what the victim finds
    seen: str  # what a witness saw the figure do
    news: str = NEWS
    title: str = TITLE


CRIMES = {
    "steal": Kind("petty", "stole", "stealing", ("bike", "tote bag", "thermos"), "missing", "walked off with something"),
    "vandalize": Kind("petty", "vandalized", "vandalizing", ("car", "bike"), "damaged", "was bent over something"),
    "sabotage": Kind("petty", "sabotaged", "sabotaging", ("county-fair pumpkin", "county-fair jam", "county-fair quilt"), "spoiled",
                     "was fiddling with something"),
    "dog": Kind("petty", "let out", "letting out", ("dog",), "loose", "was opening a gate"),
    "trailer": Kind("petty", "drove off with", "driving off with", ("marching band trailer",), "missing", "was hauling something off"),
    "salt": Kind("petty", "salted", "salting", ("sugar jars",), "salted", "was fiddling with the jars"),
    "moustache": Kind("petty", "drew a moustache on", "drawing a moustache on", ("portrait",), "defaced", "was scribbling on something"),
    "goose": Kind("petty", "made off with", "making off with", ("goose",), "missing", "was carrying something that honked"),
    "gnome": Kind("petty", "pinched", "pinching", ("garden gnome",), "missing", "was carrying something small and pointy"),
    "rob": Kind("serious", "robbed", "robbing", ("till", "cash box"), "emptied", "was hurrying out with a bag",
                news="Someone robbed {victim}'s {item} {at} {when}."),
    "mug": Kind("serious", "mugged", "mugging", ("wallet", "phone"), "gone", "was grabbing at someone",
                news="Someone mugged {victim} {at} {when} and took their {item}.", title="The mugging of {victim}"),
    "car": Kind("serious", "stole", "stealing", ("car",), "gone", "was driving off in a car that wasn't theirs"),
    "death": Kind("major", "", "", ("",), "", "was leaving in a hurry",
                  news="{victim} was found dead {at}. It happened {window}. Police are treating it as suspicious.",
                  title="The death of {victim}"),
}
TEMPLATES = CRIMES
# Where each item plausibly is. Residents are on a street only at home: at night, or by day working from home.
FAIR_PLACES = (*STREETS, "town hall", "library")
TILL_PLACES = ("grocery", "hardware store", "cafe", "bar", "gym")
MUG_PLACES = (*STREETS, "dog park", "bar", "gym", "grocery")
# Items whose victim works where they are taken.
AT_WORK = ("till", "cash box")
ITEM_PLACES = {"bike": (*STREETS, "gym", "school"), "tote bag": ("cafe", "gym", "library", "grocery"),
               "thermos": ("cafe", "gym", "school", "library"), "car": (*STREETS, "grocery", "hardware store", "gym", "bar"),
               "county-fair pumpkin": FAIR_PLACES, "county-fair jam": FAIR_PLACES, "county-fair quilt": FAIR_PLACES,
               "dog": STREETS, "marching band trailer": ("school",), "sugar jars": ("cafe", "grocery"),
               "portrait": ("town hall", "library"), "goose": ("dog park", *STREETS), "garden gnome": STREETS,
               "till": TILL_PLACES, "cash box": TILL_PLACES, "wallet": MUG_PLACES, "phone": MUG_PLACES,
               "": tuple(p for p in PLACES if p != "school")}
# What a mugging's victim saw the mugger do.
VICTIM_SAW = "grabbed at me and took my {item}"
# How many residents besides the culprit a death's victim must be on cold terms with.
MOTIVES = 2
# How many minutes after the crime the victim finds it.
NOTICED = (10, 45)
PHASE_MINUTES = {"morning": (420, 720), "afternoon": (720, 1020), "evening": (1020, 1320), "night": (1320, 1740)}
MOTIVE_WEIGHT = 3
# By tier: how many residents may witness a crime, and how often its culprit is someone expected at the scene anyway,
# when one fits.
EVIDENCE = {"petty": (2, 1 / 3), "serious": (3, 0.0), "major": (2, 0.0)}
# By tier: the chance a case has no witness, so it is solved from traces and records alone; a mugging's victim still
# remembers one thing.
NO_WITNESS = {"petty": 0.3, "serious": 0.6, "major": 0.85}
CAMERA_PLACES = ("grocery", "bar", "town hall", "elm street")
LOG_PLACES = {"gym": "Gym check-in", "bar": "Bar tab closed", "grocery": "Grocery receipt", "library": "Library checkout"}
# The chance a witness describes what they saw only roughly, when a range covers it.
RANGED_CHANCE = 0.4
CLIP_TRAITS = ("height", "coat")
# How many minutes after the crime a camera nearby catches the culprit's car.
PASSING = (3, 12)
WITNESS_DRIFT = 20
# What the culprit can leave behind: a trace of one trait, or a store receipt whose log names who paid.
TRACES = {"height": "A boot print {at}, left by {figure}.", "coat": "A thread {at}, snagged from {figure}.",
          "car": "Fresh tracks {at}, from a {value}."}
RECEIPT = "A grocery receipt dropped {at}, stamped {clock}."
# How many minutes before the crime a dropped receipt was stamped, never before its part of the day.
RECEIPT_BEFORE = (10, 60)
# Case text keeps the crime's time as WHEN, said relative to the day it is read.
WHEN = "{when}"
# A death's news keeps the window it happened in as WINDOW, said the same way.
WINDOW = "{span}"
DAYS_AGO = ("two", "three", "four", "five", "six")
# A time as ago() or a resident says it, or a window between two such times.
_TIME = (r"(?:this (?:morning|afternoon|evening)|tonight|last night|the night before last|"
         r"yesterday (?:morning|afternoon|evening)|"
         r"\w+ days ago, (?:in the (?:morning|afternoon|evening)|at night))")
_OLDER_SPAN = r"sometime (?:at night|in the evening) \w+ days ago or (?:the next morning|that night)"
SAID_TIME = re.compile(rf"\b(?:{_OLDER_SPAN}|sometime between {_TIME} and {_TIME}|{_TIME})\b", re.IGNORECASE)
# How people say an evening too.
EVENING = {"last night": "yesterday evening", "tonight": "this evening"}


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
    owner: str | None = None  # the practice case's player
    tier: str = "petty"
    window: list[str] = field(default_factory=list)  # a death's public window: two phases in order, one its own


@dataclass
class Record:
    id: str
    case: str
    kind: str  # "memory" | "discovery" | "clip" | "log" | "clue" | "statement" | "photo"
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
    disproof: str | None = None  # an unsound record's: the id of a sound record that contradicts it


def clock_at(minute: int) -> str:
    """Minutes since midnight as a twelve-hour time, like "11:42pm"."""
    hour, mins = divmod(minute % 1440, 60)
    return f"{(hour - 1) % 12 + 1}:{mins:02d}{'am' if hour < 12 else 'pm'}"


def minute_of(clock: str, phase: str) -> int:
    """A twelve-hour time in phase as minutes since the phase's day began, past midnight for the small hours."""
    hour, mins = map(int, clock[:-2].split(":"))
    minute = hour % 12 * 60 + mins + (720 if clock.endswith("pm") else 0)
    return minute + 1440 if minute < PHASE_MINUTES[phase][0] else minute


def ago(day: int, phase: str, today: float) -> str:
    """When day's phase was, said on today (a day, plus how far into it by part, as Game.time gives): "this
    afternoon", "last night", "the night before last", "two days ago, in the evening". An evening read in the small hours was last night."""
    days = int(today) - day
    if days <= 0 and phase == "evening" and PHASES[int(today % 1 * len(PHASES))] == "night":
        return "last night"
    if days <= 0:
        return "tonight" if phase == "night" else f"this {phase}"
    if days == 1:
        return "last night" if phase == "night" else f"yesterday {phase}"
    if days == 2 and phase == "night":
        return "the night before last"
    return f"{_days(days)} days ago, " + ("at night" if phase == "night" else f"in the {phase}")


def _days(days: int) -> str:
    """Two or more days as said, like "three"."""
    return DAYS_AGO[days - 2] if days - 2 < len(DAYS_AGO) else str(days)


def when(crime: Crime, today: float | None = None) -> str:
    """When the crime happened, or the window it happened in, said on today, or on the crime's own day; a window
    two or more days old is said from its first part, like "sometime at night three days ago or the next morning"."""
    today = crime.day if today is None else today
    if not crime.window:
        return ago(crime.day, crime.phase, today)
    first, last = crime.window
    i = PHASES.index(crime.phase)
    first_day = crime.day - (PHASES.index(first) > i)
    last_day = crime.day + (PHASES.index(last) < i)
    if int(today) - last_day < 2:
        return f"sometime between {ago(first_day, first, today)} and {ago(last_day, last, today)}"
    start = "at night" if first == "night" else f"in the {first}"
    return f"sometime {start} {_days(int(today) - first_day)} days ago or " + (
        f"the next {last}" if last_day > first_day else f"that {last}")


def told(text: str, crime: Crime, today: float | None = None) -> str:
    """text with its WHEN and WINDOW said on today."""
    said = when(crime, today)
    return text.replace(WHEN, said).replace(WINDOW, said)


def retime(text: str, said: str) -> str:
    """text, said about the case on some earlier day, with each time it gives replaced by said."""
    return SAID_TIME.sub(said, text)


def misdated(line: str, allowed: str) -> bool:
    """Whether the line gives a time allowed does not; "last night" and "tonight" may say an evening."""
    allowed = allowed.lower()
    return any(t not in allowed and EVENING.get(t, t) not in allowed for t in map(str.lower, SAID_TIME.findall(line)))


def resents(a, b) -> bool:
    """Whether a's grudge names b."""
    return bool(re.search(rf"\b{re.escape(b.name.split()[0])}\b", a.grudge, re.IGNORECASE))


def motives(town: Town, victim: str) -> list[str]:
    """Residents on cold terms with the victim or holding a grudge with them, either way."""
    v = town.get(victim)
    return [o.id for o in town.villagers if o.id != victim and (
        o.warmth.get(victim, 0.0) < 0 or v.warmth.get(o.id, 0.0) < 0 or resents(o, v) or resents(v, o))]


def motive_of(culprit, victim) -> str:
    if culprit.warmth.get(victim.id, 0.0) < 0:
        return "rival"
    return "grudge" if resents(culprit, victim) else "opportunity"


def stage_crime(town: Town, routine, rng: Random, day: int, phase: str, case_id: str, *,
                exclude=frozenset(), culprits: set[str] | None = None, tier: str = "petty",
                weight: Callable[[str], float] | None = None) -> Crime | None:
    """Draw a crime of tier, then a culprit (one of culprits, when given) and a victim from different households, the
    victim where the item plausibly is, at work for a till, each place weighted by weight when given. With the tier's EVIDENCE chance, when one fits, the culprit is expected at the
    scene too, otherwise elsewhere; with none, never there. A death's victim is on cold terms with at least MOTIVES
    others besides the culprit, and its window spans the part of the day before or after, either equally likely.
    None if no crime fits."""
    residents = [v for v in town.villagers if v.id not in exclude and routine.place(v.id, phase) is not None]
    disliked = {v.id: set(motives(town, v.id)) for v in residents} if tier == "major" else {}
    crimes = [(t, item) for t, kind in CRIMES.items() if kind.tier == tier for item in kind.items]
    chance = EVIDENCE[tier][1]
    fits = {}
    for template, item in crimes:
        pairs = [(c, w, motive_of(c, w)) for w in residents for c in residents
                 if c.household != w.household and (culprits is None or c.id in culprits)
                 and routine.place(w.id, phase) in ITEM_PLACES[item]
                 and (item not in AT_WORK or routine.place(w.id, phase) == routine.place(w.id, "morning"))
                 and (chance or routine.place(c.id, phase) != routine.place(w.id, phase))
                 and (not disliked or len(disliked[w.id] - {c.id}) >= MOTIVES)]
        if pairs:
            fits[template, item] = pairs
    if not fits:
        return None
    # A kind of crime is drawn as often as its victims' places allow, so a watch steers the kind as well as the place.
    shares = [sum(weight(routine.place(w.id, phase)) for _, w, _ in pairs) / len(pairs) if weight else 1
              for pairs in fits.values()]
    template, item = rng.choices(list(fits), shares)[0]
    pairs = fits[template, item]
    regular = [p for p in pairs if routine.place(p[0].id, phase) == routine.place(p[1].id, phase)]
    away = [p for p in pairs if p not in regular]
    pairs = regular if regular and (not away or rng.random() < chance) else away
    weights = [(1 if m == "opportunity" else MOTIVE_WEIGHT) * (weight(routine.place(w.id, phase)) if weight else 1)
               for _, w, m in pairs]
    culprit, victim, motive = rng.choices(pairs, weights)[0]
    minute = rng.randrange(*PHASE_MINUTES[phase])
    place = routine.place(victim.id, phase)
    kind = CRIMES[template]
    text = kind.news.format(did=kind.did, victim=victim.name, item=item, at=at(place), when=WHEN, window=WINDOW)
    i = PHASES.index(phase)
    window = []
    if kind.tier == "major":
        window = [PHASES[i - 1], phase] if rng.random() < 0.5 else [phase, PHASES[(i + 1) % len(PHASES)]]
    return Crime(case_id, template, item, culprit.id, victim.id, place, day, phase, minute, motive, text,
                 tier=kind.tier, window=window)


def crime_title(crime: Crime, town: Town) -> str:
    """The case's title, like "Ada Reyes's bike"."""
    return CRIMES[crime.template].title.format(victim=town.name_of(crime.victim), item=crime.item)


def catalog_tiers() -> tuple[str, ...]:
    """The tiers the catalog has a crime for, lowest first."""
    return tuple(t for t in TIERS if any(k.tier == t for k in CRIMES.values()))


def record_json(r: Record, town: Town, crime: Crime | None = None, today: float | None = None) -> dict:
    """What the player sees of a record, its case's time said on today."""
    text = told(r.text, crime, today) if crime else r.text
    return {"id": r.id, "kind": r.kind, "place": r.place, "day": r.day, "clock": r.clock, "text": text,
            "from": town.name_of(r.holder) or "" if r.holder else "", "holder": r.holder}


def _sighted(seen: dict[str, str]) -> str:
    """Who was seen, gender as the noun: "a tall woman in a grey hoodie", "a bald figure", or just "someone"."""
    looks = ", ".join(seen[c].replace(" ", "-") for c in ("height", "hair") if c in seen)
    noun = seen.get("gender") or ("figure" if looks else "")
    gear = " ".join(describe({c: seen[c]}) for c in ("coat", "car") if c in seen)
    words = f"{looks} {noun}".strip()
    if words:
        words = f"{'an' if words[0] in 'aeiou' else 'a'} {words}"
    return f"{words or 'someone'} {gear}".rstrip()


def _memory_text(crime: Crime, clock: str, seen: dict[str, str], holder: str) -> str:
    """What the holder saw, a mugging's victim in their own words."""
    where = f"Around {clock}, {at(crime.place)}"
    if list(seen) == ["car"] and holder != crime.victim:
        car = "a car" if seen["car"] in RANGES else f"a {seen['car']}"
        return f"{where}, someone {'rode off on' if seen['car'] == 'bicycle' else 'drove off in'} {car}."
    did = VICTIM_SAW.format(item=crime.item) if holder == crime.victim else CRIMES[crime.template].seen
    headed = f", headed toward {place_name(seen['headed'])}" if "headed" in seen else ""
    return f"{where}, {_sighted(seen)} {did}{headed}."


def witness_memory(crime: Crime, witness: str, seen: dict[str, str], rng: Random, ids: Ids) -> Record:
    """What the witness saw at the scene, clocked a little either side of the crime within its part of the day."""
    lo, hi = PHASE_MINUTES[crime.phase]
    clock = clock_at(min(max(crime.minute + rng.randint(-WITNESS_DRIFT, WITNESS_DRIFT), lo), hi - 1))
    return Record(ids.next("r"), crime.id, "memory", crime.place, clock, _memory_text(crime, clock, seen, witness),
                  witness, seen, day=crime.day)


def evident(crime: Crime, town: Town) -> dict[str, str]:
    """What evidence can show of the culprit: their sighting that day, less their own car when they drove off in the
    victim's."""
    seen = town.sighting(crime.culprit, crime.day)
    return {c: v for c, v in seen.items() if not (crime.template == "car" and c == "car")}


def witness_sees(culprit: dict[str, str], rng: Random) -> dict[str, str]:
    """One thing a witness noticed of the culprit, sometimes only roughly."""
    category = rng.choice([c for c in SEEN_AS if c in culprit])
    value = culprit[category]
    loosely = [phrase for phrase, covered in RANGES.items() if value in covered]
    if loosely and rng.random() < RANGED_CHANCE:
        value = rng.choice(loosely)
    return {category: value}


def recall_more(crime: Crime, memory: Record, culprit: dict[str, str]) -> Record:
    """The memory with a rough sighting sharpened or one more trait, unnumbered, or as it was when it has them all or
    is mistaken."""
    if not memory.sound:
        return replace(memory)
    seen = dict(memory.traits)
    rough = next((c for c in seen if seen[c] != culprit[c]), None)
    extra = rough or next((c for c in SEEN_AS if c in culprit and c not in seen), None)
    if extra is None:
        return replace(memory)
    seen[extra] = culprit[extra]
    return replace(memory, id="", traits=seen, text=_memory_text(crime, memory.clock, seen, memory.holder))


def bystanders(crime: Crime, town: Town, routine, away=frozenset()) -> list[str]:
    """Residents expected at the scene in the crime's part of the day, besides its culprit, its victim and anyone away."""
    return [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim, *away)
            and routine.place(v.id, crime.phase) == crime.place]


def witness_memories(crime: Crime, town: Town, routine, rng: Random, ids: Ids, away=frozenset()) -> list[Record]:
    """Up to the tier's EVIDENCE count of residents expected at the scene and not away, each recalling one thing about
    the culprit."""
    nearby = bystanders(crime, town, routine, away)
    culprit = evident(crime, town)
    memories = []
    for w in rng.sample(nearby, min(EVIDENCE[crime.tier][0], len(nearby))):
        memories.append(witness_memory(crime, w, witness_sees(culprit, rng), rng, ids))
    return memories


def victim_memory(crime: Crime, town: Town, rng: Random, ids: Ids) -> Record:
    """What a mugging's victim saw of the mugger: one of their traits."""
    culprit = evident(crime, town)
    trait = rng.choice([c for c in SEEN_AS if c in culprit])
    return witness_memory(crime, crime.victim, {trait: culprit[trait]}, rng, ids)


def discovery(crime: Crime, town: Town, rng: Random, ids: Ids, finder: str | None = None) -> Record:
    """The victim finding the crime a little after it, or the finder finding the victim of a death, which says nothing
    of who did it."""
    clock = clock_at(min(crime.minute + rng.randint(*NOTICED), PHASE_MINUTES[crime.phase][1] - 1))
    if finder:
        text = f"Around {clock}, {town.get(finder).name} found {town.get(crime.victim).name} {at(crime.place)}."
    else:
        text = f"Around {clock}, {town.get(crime.victim).name} found the {crime.item} {CRIMES[crime.template].found} {at(crime.place)}."
    return Record(ids.next("r"), crime.id, "discovery", crime.place, clock, text, finder or crime.victim, day=crime.day)


def found_it(crime: Crime, clock: str, victim: str = "") -> str:
    """The discovery in its finder's own words; victim names a death's victim."""
    if victim:
        return f"Around {clock}, I found {victim} {at(crime.place)}."
    return f"Around {clock}, I found my {crime.item} {CRIMES[crime.template].found} {at(crime.place)}."


def camera_clip(crime: Crime, town: Town, ids: Ids) -> Record | None:
    """The scene's camera footage at the crime minute, if the place has a camera."""
    if crime.place not in CAMERA_PLACES:
        return None
    culprit = town.looks(crime.culprit, crime.day)
    seen = {c: culprit[c] for c in CLIP_TRAITS}
    clock = clock_at(crime.minute)
    text = f"{clock}, {place_name(crime.place)} camera: {figure(seen)} {CRIMES[crime.template].seen}."
    return Record(ids.next("r"), crime.id, "clip", crime.place, clock, text, traits=seen, day=crime.day)


def passing_clip(crime: Crime, town: Town, ids: Ids, rng: Random) -> Record | None:
    """Another camera in the scene's district catching the culprit's own car heading away a few minutes after, if they
    drove it and the district has one."""
    car = evident(crime, town).get("car")
    cameras = [p for p in CAMERA_PLACES if p != crime.place and district_of(p) == district_of(crime.place)]
    if car in (None, "bicycle") or not cameras:
        return None
    camera = rng.choice(cameras)
    clock = clock_at(crime.minute + rng.randint(*PASSING))
    scene = place_name(crime.place) if crime.place in STREETS else f"the {crime.place}"
    text = f"{clock}, {place_name(camera)} camera: a {car} heading away from {scene}."
    return Record(ids.next("r"), crime.id, "clip", camera, clock, text, traits={"car": car}, day=crime.day)


def scene_clues(crime: Crime, town: Town, routine, rng: Random, ids: Ids, away=frozenset()) -> list[Record]:
    """One or two things left at the scene: a trace of one of the culprit's traits, or a receipt dropped by the
    culprit or someone expected there and not away. A receipt names no one; the grocery's log for its time, returned
    with it, names who paid."""
    culprit = evident(crime, town)
    clues: list[Record] = []
    for kind in rng.sample([*(k for k in TRACES if k in culprit), "receipt"], rng.randint(1, 2)):
        if kind == "receipt":
            who = rng.choice([crime.culprit, *bystanders(crime, town, routine, away)])
            clues += _receipt(crime, who, town, rng, ids)
        else:
            clues.append(trace(crime, kind, culprit[kind], ids))
    return clues


def trace(crime: Crime, kind: str, value: str, ids: Ids) -> Record:
    """A trace at the scene of one trait value."""
    seen = {kind: value}
    text = TRACES[kind].format(at=at(crime.place), figure=figure(seen), value=value)
    return Record(ids.next("r"), crime.id, "clue", crime.place, "", text, traits=seen, day=crime.day)


def _receipt(crime: Crime, who: str, town: Town, rng: Random, ids: Ids) -> list[Record]:
    """A receipt dropped at the scene, and the grocery's log naming who paid."""
    clock = clock_at(max(crime.minute - rng.randint(*RECEIPT_BEFORE), PHASE_MINUTES[crime.phase][0]))
    text = RECEIPT.format(at=at(crime.place), clock=clock)
    paid = f"{LOG_PLACES['grocery']}: {town.get(who).name}, {clock}"
    return [Record(ids.next("r"), crime.id, "clue", crime.place, clock, text, day=crime.day),
            Record(ids.next("r"), crime.id, "log", "grocery", clock, paid, who=who, trail=True, day=crime.day)]


def logs(crime: Crime, phase_log: dict[str, list[str]], town: Town, rng: Random, ids: Ids) -> list[Record]:
    """A check-in, tab or receipt for every resident who passed through a logging place this phase, a death's victim
    only before it."""
    records = []
    start, end = PHASE_MINUTES[crime.phase]
    for vid, places in phase_log.items():
        last = crime.minute if crime.template == "death" and vid == crime.victim else end
        for place in dict.fromkeys(places):
            if place in LOG_PLACES and start < last:
                clock = clock_at(rng.randrange(start, last))
                text = f"{LOG_PLACES[place]}: {town.get(vid).name}, {clock}"
                records.append(Record(ids.next("r"), crime.id, "log", place, clock, text, who=vid,
                                      day=crime.day))
    return records


def points_at(crime: Crime, culprit: str, traits: dict[str, str], r: Record) -> bool:
    """Whether a record singles out the culprit: a sighting or trace that fits them, or a log that puts them at the
    scene or behind a receipt left there. A housemate's "I was asleep" says the same of everyone, so it points at no one."""
    if r.kind in ("memory", "clip", "clue") and r.traits:
        return fits(r.traits, traits)
    return r.kind == "log" and r.who == culprit and (r.place == crime.place or r.trail)


def suspects(crime: Crime, records: list[Record], town: Town) -> set[str]:
    """Residents who match every sound sighting and trace and are not soundly logged only elsewhere."""
    sightings = [r.traits for r in records if r.sound and r.kind in ("memory", "clip", "clue")]
    logged = [r for r in records if r.sound and r.kind == "log" and not r.trail]
    at_scene = {r.who for r in logged if r.place == crime.place}
    alibied = {r.who for r in logged if r.place != crime.place} - at_scene
    return {v.id for v in town.villagers if v.id != crime.victim and v.id not in alibied
            and all(fits(seen, town.sighting(v.id, crime.day)) for seen in sightings)}


def make_solvable(crime: Crime, records: list[Record], town: Town, routine, rng: Random, ids: Ids,
                  away=frozenset(), allow_witness: bool = True) -> list[Record] | None:
    """The evidence that narrows the sound records to the culprit and points at them, tried in order: scene traces of
    what no record shows yet, a passing camera, the culprit's receipt and its log, each kept only if it narrows, or
    points at the culprit once only they are left; then, when allow_witness, one witness per trait still needed, from
    someone not away. [] if none is needed, None if it can't be done."""
    records = [r for r in records if r.sound]
    left = suspects(crime, records, town)
    if crime.culprit not in left:
        return None
    culprit = evident(crime, town)
    added: list[Record] = []
    pointing = any(points_at(crime, crime.culprit, culprit, r) for r in records)
    for lead in _leads(crime, records, town, rng, ids):
        if len(left) == 1 and pointing:
            break
        narrowed = suspects(crime, records + added + lead, town)
        points = any(points_at(crime, crime.culprit, culprit, r) for r in lead)
        if narrowed < left or (len(left) == 1 and points and not pointing):
            added, left, pointing = added + lead, narrowed, pointing or points
    if len(left) == 1 and pointing:
        return added
    if not allow_witness:
        return None
    seen: set[str] = set()
    seen_by = {r.holder for r in records if r.kind == "memory"}
    others = [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim, *away)]
    witnesses = [w for w in dict.fromkeys(bystanders(crime, town, routine, away) + others) if w not in seen_by]
    while len(left) > 1 or not pointing:
        unseen = [c for c in culprit if c not in seen]
        if not unseen or not witnesses:
            return None
        best = max(unseen, key=lambda c: sum(town.sighting(s, crime.day).get(c) != culprit[c] for s in left))
        narrowed = {s for s in left if town.sighting(s, crime.day).get(best) == culprit[best]}
        if narrowed == left and len(left) > 1:
            return None
        added.append(witness_memory(crime, witnesses.pop(0), {best: culprit[best]}, rng, ids))
        seen.add(best)
        left, pointing = narrowed, True
    return added


def _leads(crime: Crime, records: list[Record], town: Town, rng: Random, ids: Ids) -> Iterator[list[Record]]:
    """The evidence make_solvable tries before a witness, each piece made only when it is tried."""
    looks = evident(crime, town)
    seen = {c for r in records if r.kind in ("memory", "clip", "clue") for c in r.traits}
    kinds = [k for k in TRACES if k in looks and k not in seen]
    for kind in rng.sample(kinds, len(kinds)):
        yield [trace(crime, kind, looks[kind], ids)]
    if clip := passing_clip(crime, town, ids, rng):
        yield [clip]
    yield _receipt(crime, crime.culprit, town, rng, ids)
