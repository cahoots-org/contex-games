"""How each resident regards each podcaster, in [-1, 1]."""

from collections.abc import Iterable

from sleuth.config import Config


class Reputation:
    def __init__(self, config: Config):
        self.config = config
        self._by_player: dict[str, dict[str, float]] = {}

    def get(self, vid: str, player: str) -> float:
        return self._by_player.get(player, {}).get(vid, 0.0)

    def nudge(self, vid: str, player: str, delta: float) -> None:
        """Move the resident's regard for the player by delta, clamped to [-1, 1]."""
        self._by_player.setdefault(player, {})[vid] = max(-1.0, min(1.0, self.get(vid, player) + delta))

    def nudge_all(self, player: str, delta: float, vids: Iterable[str]) -> None:
        for vid in vids:
            self.nudge(vid, player, delta)

    def mean(self, player: str, vids: Iterable[str]) -> float:
        values = [self.get(vid, player) for vid in vids]
        return sum(values) / len(values) if values else 0.0

    def decay(self) -> None:
        """Move every regard reputation_decay toward 0."""
        step = self.config.reputation_decay
        for values in self._by_player.values():
            for vid, v in values.items():
                values[vid] = max(0.0, v - step) if v > 0 else min(0.0, v + step)

    def to_state(self) -> dict:
        return {player: dict(values) for player, values in self._by_player.items()}

    def restore(self, state: dict) -> None:
        self._by_player = {player: dict(values) for player, values in state.items()}
