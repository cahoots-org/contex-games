"""The few residents who commit the town's crimes, hidden from everyone, and who the town knows did what."""

from dataclasses import asdict, dataclass
from random import Random

from sleuth.case import TIERS, catalog_tiers
from sleuth.config import Config
from sleuth.town import Town


@dataclass
class Offender:
    tier: str = "petty"
    escaped: int = 0
    quiet_until: int = 0  # game day before which they commit nothing


class Offenders:
    def __init__(self, config: Config):
        self.config = config
        # Hidden: who offends, at what tier.
        self.active: dict[str, Offender] = {}
        # Public: what the town knows each exposed resident did, like "stole Ada Reyes's bike".
        self.exposed: dict[str, str] = {}

    def to_state(self) -> dict:
        return {"active": {vid: asdict(o) for vid, o in self.active.items()}, "exposed": dict(self.exposed)}

    def restore(self, state: dict) -> None:
        self.active = {vid: Offender(**o) for vid, o in state["active"].items()}
        self.exposed = dict(state["exposed"])

    def top_up(self, town: Town, rng: Random, candidates: list[str] | None = None) -> list[str]:
        """Fill active up to config.offenders from candidates (default: every resident) not active and never exposed;
        returns who joined."""
        pool = [vid for vid in (candidates if candidates is not None else [v.id for v in town.villagers])
                if vid not in self.active and vid not in self.exposed]
        joined = rng.sample(pool, max(0, min(self.config.offenders - len(self.active), len(pool))))
        self.active.update({vid: Offender() for vid in joined})
        return joined

    def turn(self, street_residents: list[str], rng: Random) -> str | None:
        """Make one resident not active and never exposed a petty offender, unless active is at max_offenders."""
        pool = [vid for vid in street_residents if vid not in self.active and vid not in self.exposed]
        if len(self.active) >= self.config.max_offenders or not pool:
            return None
        vid = rng.choice(pool)
        self.active[vid] = Offender()
        return vid

    def ready(self, day: int, tier: str) -> set[str]:
        """Active offenders at tier whose quiet_until <= day."""
        return {vid for vid, o in self.active.items() if o.tier == tier and o.quiet_until <= day}

    def _held_by(self, tier: str) -> int:
        return sum(o.tier == tier for o in self.active.values())

    def escaped_with(self, vid: str) -> None:
        """Count a case gone cold; at config.escalate_after move up one tier within catalog_tiers(), reset escaped,
        unless they are the last offender of their tier."""
        if (o := self.active.get(vid)) is None:
            return
        o.escaped += 1
        tiers = catalog_tiers()
        if o.escaped >= self.config.escalate_after and o.tier in tiers[:-1] and self._held_by(o.tier) > 1:
            o.tier, o.escaped = tiers[tiers.index(o.tier) + 1], 0

    def promote(self, tier: str, exclude=frozenset(), day: int | None = None) -> str | None:
        """Move the offender one tier below, not in exclude nor lying low on day, with the most escapes up to tier,
        unless the tier below would be left with none."""
        if tier == TIERS[0]:
            return None
        below = TIERS[TIERS.index(tier) - 1]
        if self._held_by(below) < 2:
            return None
        vid = max((vid for vid, o in self.active.items() if o.tier == below and vid not in exclude
                   and (day is None or o.quiet_until <= day)),
                  key=lambda v: self.active[v].escaped, default=None)
        if vid is not None:
            self.active[vid].tier, self.active[vid].escaped = tier, 0
        return vid

    def new_day(self, day: int, rng: Random) -> list[str]:
        """Each exposed offender done lying low reforms, and stops offending, with reform_chance; returns who did."""
        reformed = [vid for vid, o in self.active.items()
                    if vid in self.exposed and o.quiet_until <= day and rng.random() < self.config.reform_chance]
        for vid in reformed:
            self.drop(vid)
        return reformed

    def drop(self, vid: str) -> None:
        self.active.pop(vid, None)
