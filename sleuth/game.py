"""The village clock."""

import time

# The parts of a game day, in order; the clock moves through them evenly.
PHASES = ("morning", "afternoon", "evening", "night")


class Game:
    def __init__(self, day_seconds: float = 120.0):
        self.day_seconds = day_seconds
        self.day, self.phase = 1, PHASES[0]
        self.phase_started = time.time()

    def to_state(self) -> dict:
        """The day, phase, and how far through the phase it is (0 to 1)."""
        part = self.day_seconds / len(PHASES)
        return {"day": self.day, "phase": self.phase,
                "elapsed": min(1.0, (time.time() - self.phase_started) / part)}

    def restore(self, state: dict) -> None:
        """Replace the clock with a saved state; the phase resumes where it left off."""
        self.day, self.phase = state["day"], state["phase"]
        self.phase_started = time.time() - state["elapsed"] * self.day_seconds / len(PHASES)

    def now(self) -> str:
        """The day and its part, like "day 4, morning"."""
        return f"day {self.day}, {self.phase}"

    def time(self) -> float:
        """The day and how far into it by part, like 4.5 on day 4's evening."""
        return self.day + PHASES.index(self.phase) / len(PHASES)

    def tick(self) -> None:
        """Move the village clock on to the next part of the day."""
        at = PHASES.index(self.phase) + 1
        self.day += at // len(PHASES)
        self.phase = PHASES[at % len(PHASES)]
        self.phase_started = time.time()

    def clock(self) -> dict:
        """The day, its part, how far through the day it is (0 to 1), and how long a day lasts in seconds."""
        part = self.day_seconds / len(PHASES)
        into = min(1.0, (time.time() - self.phase_started) / part)
        return {"day": self.day, "phase": self.phase, "fraction": (PHASES.index(self.phase) + into) / len(PHASES),
                "day_seconds": self.day_seconds}
