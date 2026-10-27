"""Town state: villagers, their places and whereabouts."""

import re
from dataclasses import asdict
from random import Random

from sleuth.models import Villager

PUBLIC_PLACES = ("cafe", "gym", "school", "bar", "dog park", "hardware store", "grocery", "town hall", "library")
STREETS = ("elm street", "oak street", "maple street")
PLACES = PUBLIC_PLACES + STREETS
START_PLACE = "cafe"


def place_name(place: str) -> str:
    """The place as written in a sentence: streets are proper names."""
    return place.title() if place in STREETS else place


def at(place: str) -> str:
    """Where someone is, like "at the cafe" or "on Elm Street"."""
    return f"on {place_name(place)}" if place in STREETS else f"at the {place}"


def subject(place: str) -> str:
    """The place opening a sentence, like "The cafe" or "Elm Street"."""
    return place_name(place) if place in STREETS else f"The {place}"


NEWCOMER = "newcomer"


class Town:
    def __init__(self) -> None:
        self._villagers: dict[str, Villager] = {}
        self._places: dict[str, str] = {}
        self.departed: list[Villager] = []
        self._phase_starts: dict[str, str] = {}
        self._phase_moves: dict[str, list[str]] = {}
        # Each day's outfit, by resident.
        self.worn: dict[int, dict[str, str]] = {}

    def to_state(self) -> dict:
        """Villagers, places, departed villagers, this phase's whereabouts and recent outfits as plain JSON."""
        return {"villagers": [asdict(v) for v in self._villagers.values()], "places": dict(self._places),
                "departed": [asdict(v) for v in self.departed],
                "phase_starts": dict(self._phase_starts), "phase_moves": {k: list(m) for k, m in self._phase_moves.items()},
                "worn": {str(day): dict(w) for day, w in self.worn.items()}}

    def restore(self, state: dict) -> None:
        """Replace the town with a saved state."""
        self._villagers = {v["id"]: Villager(**v) for v in state["villagers"]}
        self._places = dict(state["places"])
        self.departed = [Villager(**v) for v in state["departed"]]
        self._phase_starts = dict(state["phase_starts"])
        self._phase_moves = {k: list(m) for k, m in state["phase_moves"].items()}
        self.worn = {int(day): dict(w) for day, w in state["worn"].items()}

    def dress(self, day: int, rng: Random, avoid: dict[str, str] | None = None, keep_days: int = 5) -> None:
        """Pick the day's outfit from each wardrobe, never the one avoid gives when another fits, once a day; forget
        days older than keep_days."""
        if day in self.worn:
            return
        avoid = avoid or {}
        self.worn[day] = {v.id: rng.choice([c for c in v.wardrobe if c != avoid.get(v.id)] or v.wardrobe)
                          for v in self._villagers.values() if v.wardrobe}
        self.worn = {d: w for d, w in self.worn.items() if d >= day - keep_days}

    def outfit(self, vid: str, day: int) -> str | None:
        """What the resident wore that day, if it is recorded."""
        return self.worn.get(day, {}).get(vid)

    def looks(self, vid: str, day: int) -> dict[str, str]:
        """The resident's traits, wearing what they wore that day."""
        coat = self.outfit(vid, day)
        return {**self.get(vid).traits, **({"coat": coat} if coat else {})}

    def __contains__(self, vid: str) -> bool:
        return vid in self._villagers

    @property
    def alive_count(self) -> int:
        return len(self._villagers)

    def add(self, v: Villager, place: str = START_PLACE) -> None:
        """Add the resident at place, dressed for the latest dressed day."""
        self._villagers[v.id] = v
        if self.worn and v.wardrobe:
            self.worn[max(self.worn)][v.id] = Random().choice(v.wardrobe)
        self._places[v.id] = place
        self._phase_moves.setdefault(v.id, []).append(place)

    def remove(self, vid: str) -> Villager:
        v = self._villagers.pop(vid)
        self._places.pop(vid, None)
        self._phase_starts.pop(vid, None)
        self._phase_moves.pop(vid, None)
        self.departed.append(v)
        return v

    @property
    def villagers(self) -> list[Villager]:
        return list(self._villagers.values())

    def get(self, vid: str) -> Villager:
        return self._villagers[vid]

    def name_of(self, vid: str) -> str | None:
        """The villager's name, even after they left town."""
        v = self._villagers.get(vid) or next((d for d in self.departed if d.id == vid), None)
        return v.name if v else None

    def place_of(self, vid: str) -> str:
        return self._places[vid]

    def move(self, vid: str, place: str) -> None:
        if place not in PLACES:
            raise ValueError(f"unknown place: {place}")
        self._places[vid] = place
        self._phase_moves.setdefault(vid, []).append(place)

    def whereabouts(self, vid: str) -> list[str]:
        """Where the resident has moved to this phase, or their place at its start."""
        return list(self._phase_moves.get(vid) or [self._phase_starts[vid]])

    def new_phase(self) -> dict[str, list[str]]:
        """End the phase: return each resident's whereabouts through it, then start the next."""
        log = {vid: self.whereabouts(vid) for vid in self._villagers}
        self._phase_starts, self._phase_moves = dict(self._places), {}
        return log

    def present(self, place: str, exclude: str | None = None) -> list[Villager]:
        return [
            self._villagers[vid]
            for vid, p in self._places.items()
            if p == place and vid != exclude
        ]

    def find(self, name: str) -> list[Villager]:
        needle = name.lower()
        exact = [v for v in self._villagers.values() if v.name.lower() == needle]
        if exact:
            return exact
        return [v for v in self._villagers.values() if needle in v.name.lower()]


def neighbours(town: Town, villager: Villager, text: str) -> list[str]:
    """Who the text names among the villager's neighbours, by trade and how the villager knows them."""
    named = []
    for v, gone in [*((v, False) for v in town.villagers), *((v, True) for v in town.departed)]:
        if v.id == villager.id or not re.search(rf"\b{re.escape(v.name.split()[0])}\b", text, re.IGNORECASE):
            continue
        tie = villager.relationships.get(v.id)
        named.append(f"{v.name}, the {v.occupation}" + (f" (your {tie})" if tie else "")
                     + (", who has left town" if gone else ""))
    return named
