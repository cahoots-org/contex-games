"""Player identity and the players of one world."""

import secrets
import time
from collections.abc import Callable, Iterator

from sleuth.player import Player
from sleuth.usage import Usage

def new_player_id() -> str:
    return "p-" + secrets.token_hex(8)


def new_owner_id() -> str:
    return "o-" + secrets.token_hex(8)


class Players:
    """The players in one world, by id."""

    def __init__(self, usage: Usage | None = None) -> None:
        self.usage = usage
        self._by_id: dict[str, Player] = {}
        self._latest: dict[str, Player] = {}

    def to_state(self) -> dict:
        """Every run as plain JSON."""
        return {"runs": [p.to_state() for p in self._by_id.values()]}

    def restore(self, state: dict, make: Callable[[str, str], Player]) -> None:
        """Replace the runs with a saved state; make(id, owner) builds a wired run."""
        self._by_id, self._latest = {}, {}
        for run in state["runs"]:
            player = make(run["id"], run["owner"])
            player.restore(run)
            self.add(player)

    def add(self, player: Player) -> None:
        self._by_id[player.id] = player
        self._latest[player.owner] = player

    def get(self, player_id: str) -> Player | None:
        return self._by_id.get(player_id)

    def live(self, owner: str) -> Player | None:
        """The owner's current run."""
        return self._latest.get(owner)

    def __iter__(self) -> Iterator[Player]:
        return iter(self._by_id.values())

    def any_playing(self) -> bool:
        """Whether some player is active and the village is not resting for the day."""
        if self.resting():
            return False
        return any(p.active() for p in self._by_id.values())

    def resting(self) -> bool:
        """Whether the village is resting for the day."""
        return self.usage is not None and self.usage.resting()

    def at(self, place: str) -> list[Player]:
        """The active players at place."""
        return [p for p in self._by_id.values() if p.place == place and p.active()]

    def prune(self) -> list[Player]:
        """Drop and return the runs that never played: those older than idle_after_seconds, and the oldest past the
        newest run's max_idle_runs."""
        now = time.time()
        idle = sorted((p for p in self._by_id.values() if not p.ever_active()), key=lambda p: p.created_at)
        excess = len(idle) - idle[-1].config.max_idle_runs if idle else 0
        stale = [p for i, p in enumerate(idle) if i < excess or now - p.created_at >= p.config.idle_after_seconds]
        for p in stale:
            del self._by_id[p.id]
            if self._latest.get(p.owner) is p:
                del self._latest[p.owner]
        return stale
