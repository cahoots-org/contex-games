"""Town state: villagers, their places and whereabouts."""

import re
from dataclasses import asdict

from sleuth.models import Villager

PUBLIC_PLACES = ("cafe", "gym", "school", "bar", "dog park", "hardware store", "grocery", "town hall", "library")
STREETS = ("elm street", "oak street", "maple street")
PLACES = PUBLIC_PLACES + STREETS
START_PLACE = "cafe"
NEWCOMER = "newcomer"


class Town:
    def __init__(self) -> None:
        self._villagers: dict[str, Villager] = {}
        self._places: dict[str, str] = {}
        self.departed: list[Villager] = []
        self._phase_starts: dict[str, str] = {}
        self._phase_moves: dict[str, list[str]] = {}

    def to_state(self) -> dict:
        """Villagers, places, departed villagers and this phase's whereabouts as plain JSON."""
        return {"villagers": [asdict(v) for v in self._villagers.values()], "places": dict(self._places),
                "departed": [asdict(v) for v in self.departed],
                "phase_starts": dict(self._phase_starts), "phase_moves": {k: list(m) for k, m in self._phase_moves.items()}}

    def restore(self, state: dict) -> None:
        """Replace the town with a saved state."""
        self._villagers = {v["id"]: Villager(**v) for v in state["villagers"]}
        self._places = dict(state["places"])
        self.departed = [Villager(**v) for v in state["departed"]]
        self._phase_starts = dict(state["phase_starts"])
        self._phase_moves = {k: list(m) for k, m in state["phase_moves"].items()}

    def __contains__(self, vid: str) -> bool:
        return vid in self._villagers

    @property
    def alive_count(self) -> int:
        return len(self._villagers)

    def add(self, v: Villager, place: str = START_PLACE) -> None:
        self._villagers[v.id] = v
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
