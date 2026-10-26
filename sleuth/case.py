"""Staging a petty crime from where the town expects its residents to be."""

import re
from dataclasses import dataclass
from random import Random

from sleuth.town import STREETS, Town

TEMPLATES = {"steal": ("stole", ("bike", "tote bag", "thermos")), "vandalize": ("vandalized", ("car", "bike")),
             "sabotage": ("sabotaged", ("county fair pumpkin", "prize jam", "fair quilt"))}
PHASE_MINUTES = {"morning": (420, 720), "afternoon": (720, 1020), "evening": (1020, 1320), "night": (1320, 1740)}
MOTIVE_WEIGHT = 3


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
