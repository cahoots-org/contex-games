"""Evidence that is wrong, each piece contradicted by something true on file."""

from dataclasses import replace
from random import Random

from sleuth.case import (
    PHASE_MINUTES, TRACES, Crime, Record, bystanders, evident, minute_of, motives, trace, witness_memory,
)
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.town import Town
from sleuth.traits import TRAITS

# By tier: how many false pieces a case has, inclusive; a petty case has one with PETTY_FALSE_CHANCE, else none.
FALSE_COUNT = {"petty": (0, 1), "serious": (1, 2), "major": (2, 3)}
PETTY_FALSE_CHANCE = 0.2
# The chance a false piece fits someone innocent, one with a motive when one fits, rather than no one in particular.
AIMED_CHANCE = 0.5
# How many minutes before the crime a decoy's log at the scene must be for their trace there to be left earlier.
LEFT_BEFORE = 30


def false_count(tier: str, rng: Random) -> int:
    """How many false pieces a case of tier has."""
    if tier == "petty":
        return int(rng.random() < PETTY_FALSE_CHANCE)
    return rng.randint(*FALSE_COUNT[tier])


def stage_false(crime: Crime, records: list[Record], town: Town, routine, rng: Random, ids: Ids, away: set[str],
                count: int) -> list[Record]:
    """Up to count false pieces, each unsound with the id of the sound record that contradicts it as its disproof: a
    bystander's mistaken memory of one thing the scene's camera or a trace there shows rightly, only in a case a
    bystander truly witnessed, or a trace of a decoy whose own log puts them at the scene well before the crime. As
    many as can be disproved, so possibly none."""
    culprit = evident(crime, town)
    suspected = set(motives(town, crime.victim)) - {crime.culprit}
    sound = [r for r in records if r.sound]
    nearby = bystanders(crime, town, routine, away)
    witnessed = any(r.kind == "memory" and r.holder in nearby for r in sound)
    seen_by = {r.holder for r in records}
    witnesses = [w for w in nearby if w not in seen_by] if witnessed else []
    shown = [r for r in sound if r.kind in ("clip", "clue") and r.place == crime.place and r.traits]
    earlier = [r for r in sound if r.kind == "log" and not r.trail and r.place == crime.place
               and r.who not in (crime.culprit, crime.victim)
               and minute_of(r.clock, crime.phase) <= crime.minute - LEFT_BEFORE]
    fakes = []
    for _ in range(count):
        leftovers = [(log, c) for log in earlier for c in _left(crime, town, culprit, log.who)]
        kinds = [k for k, can in (("mistake", witnesses and shown), ("leftover", leftovers)) if can]
        if not kinds:
            break
        if rng.choice(kinds) == "mistake":
            disproof = rng.choice(shown)
            category = rng.choice(list(disproof.traits))
            value = _wrong(crime, town, category, disproof.traits[category], suspected, rng)
            witness = witnesses.pop(rng.randrange(len(witnesses)))
            fake = witness_memory(crime, witness, {category: value}, rng, ids)
        else:
            aimed = [p for p in leftovers if p[0].who in suspected]
            disproof, category = rng.choice(aimed if aimed and rng.random() < AIMED_CHANCE else leftovers)
            earlier.remove(disproof)
            fake = trace(crime, category, town.sighting(disproof.who, crime.day)[category], ids)
        fakes.append(replace(fake, sound=False, disproof=disproof.id))
    return fakes


def _left(crime: Crime, town: Town, culprit: dict[str, str], decoy: str) -> list[str]:
    """What the decoy could have left at the scene that the culprit couldn't: a trace of a look they don't share."""
    looks = town.sighting(decoy, crime.day)
    return [c for c in TRACES if c in looks and looks[c] != culprit.get(c) and not (crime.template == "car" and c == "car")]


def _wrong(crime: Crime, town: Town, category: str, right: str, suspected: set[str], rng: Random) -> str:
    """A value of category other than right: with AIMED_CHANCE an innocent's, one with a motive when one fits, else
    any."""
    decoys = [v.id for v in town.villagers if v.id not in (crime.culprit, crime.victim)
              and town.sighting(v.id, crime.day).get(category) not in (None, right)]
    if decoys and rng.random() < AIMED_CHANCE:
        decoy = rng.choice([d for d in decoys if d in suspected] or decoys)
        return town.sighting(decoy, crime.day)[category]
    return rng.choice([v for v in TRAITS[category] if v != right])


def cover_place(whereabouts: dict[str, list[str]], accomplice: Villager) -> str:
    """Where the accomplice says the culprit was with them: the first place they were during the crime, else home."""
    return (whereabouts.get(accomplice.id) or [accomplice.home])[0]


def cover_disproof(crime: Crime, records, place: str) -> str | None:
    """The id of a sound log, not one behind a receipt, at place in the crime's part of the day that leaves the
    culprit out, which disproves a word that they were there."""
    lo, hi = PHASE_MINUTES[crime.phase]
    return next((r.id for r in records if r.sound and r.kind == "log" and not r.trail and r.place == place
                 and r.who != crime.culprit and r.day == crime.day and lo <= minute_of(r.clock, crime.phase) < hi),
                None)
