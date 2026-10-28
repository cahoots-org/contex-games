"""The town's three districts, one per street: how much crime each has seen and how afraid its residents are."""

from dataclasses import asdict, dataclass, field
from random import Random

from sleuth.case import Crime
from sleuth.config import Config
from sleuth.town import STREETS, Town

PLACE_DISTRICT = {"cafe": "elm street", "bar": "elm street", "dog park": "elm street",
                  "gym": "oak street", "school": "oak street", "library": "oak street",
                  "hardware store": "maple street", "grocery": "maple street", "town hall": "maple street",
                  **{s: s for s in STREETS}}
# How far a crime of each tier raises its district's crime and fear.
HIT = {"petty": 0.25, "serious": 0.45, "major": 0.7}
# How far an exposure lowers its district's crime, and fear.
RELIEF = (0.15, 0.1)
# How far a value must move since the last morning to show a trend.
TREND_DEAD_ZONE = 0.05
WATCH_NAMES = ("{street} Neighborhood Watch", "{street} Porch-Light Pact", "{street} Group Chat")
WATCH_SIZE = 6
FORMED = "{street} residents are starting a watch. {first}'s making flyers."
TOLD = "We're starting the {name}. Keep an eye out on {street}."
WOUND_DOWN = "The {name} has wound down. {street} feels safe again."


def district_of(place: str) -> str:
    return PLACE_DISTRICT[place]


def level(x: float) -> int:
    """A crime or fear value as the browser sees it, 0 to 3."""
    return round(x * 3)


def _trend(now: float, was: float) -> int:
    """Whether a value rose (1), fell (-1) or held (0) since the last morning, ignoring changes up to TREND_DEAD_ZONE."""
    return 0 if abs(now - was) <= TREND_DEAD_ZONE else 1 if now > was else -1


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class Watch:
    name: str
    founder: str
    members: list[str]  # the founder first
    since: float


@dataclass
class District:
    crime: float = 0.0
    fear: float = 0.0
    exposures: int = 0  # exposures since it last organized
    was: list[float] = field(default_factory=lambda: [0.0, 0.0])  # crime, fear at the last morning
    watch: Watch | None = None


class Districts:
    def __init__(self, config: Config):
        self.config = config
        self.by_street = {s: District() for s in STREETS}

    def to_state(self) -> dict:
        return {street: asdict(d) for street, d in self.by_street.items()}

    def restore(self, state: dict) -> None:
        self.by_street = {street: District(**{**d, "watch": d["watch"] and Watch(**d["watch"])})
                          for street, d in state.items()}

    def organized(self, place: str) -> bool:
        return self.by_street[district_of(place)].watch is not None

    def on_crime(self, crime: Crime) -> None:
        d = self.by_street[district_of(crime.place)]
        d.crime, d.fear = _clamp(d.crime + HIT[crime.tier]), _clamp(d.fear + HIT[crime.tier])

    def on_exposed(self, crime: Crime) -> None:
        """Ease the district of a crime a podcaster solved, counting toward a watch."""
        d = self.by_street[district_of(crime.place)]
        d.crime, d.fear = _clamp(d.crime - RELIEF[0]), _clamp(d.fear - RELIEF[1])
        d.exposures += 1

    def tick(self, morning: bool) -> None:
        """Let crime and fear fade for a part of the day; of a morning, remember them for the day's trends."""
        for d in self.by_street.values():
            d.crime = _clamp(d.crime - self.config.district_crime_decay)
            d.fear = _clamp(d.fear - self.config.district_fear_decay)
            if morning:
                d.was = [d.crime, d.fear]

    def organize(self, street: str, town: Town, rng: Random, now: float, victim: str | None = None) -> Watch | None:
        """Form a watch when fear >= organize_fear, exposures >= 1 and none stands; resets exposures. Its founder is
        the victim when they live on the street, else a random resident, joined by the residents they're warmest to."""
        d = self.by_street[street]
        residents = [v.id for v in town.villagers if v.home == street]
        if d.watch or d.fear < self.config.organize_fear or d.exposures < 1 or not residents:
            return None
        founder = victim if victim in residents else rng.choice(residents)
        warmth = town.get(founder).warmth
        others = sorted((vid for vid in residents if vid != founder), key=lambda vid: -warmth.get(vid, 0.0))
        name = rng.choice(WATCH_NAMES).format(street=street.title())
        d.watch, d.exposures = Watch(name, founder, [founder, *others[:WATCH_SIZE - 1]], now), 0
        return d.watch

    def wind_down(self) -> list[str]:
        """End the watch of every street whose crime and fear have both faded below disband_below; returns them."""
        ended = [s for s, d in self.by_street.items()
                 if d.watch and max(d.crime, d.fear) < self.config.disband_below]
        for s in ended:
            self.by_street[s].watch = None
        return ended

    def neglected(self) -> list[str]:
        """Streets with no watch whose crime and fear are both at least neglect_at."""
        at_ = self.config.neglect_at
        return [s for s, d in self.by_street.items() if not d.watch and min(d.crime, d.fear) >= at_]

    def mood(self, street: str) -> str | None:
        """How the street feels, like "on edge, but the Elm Street Group Chat is on it", or None when calm."""
        d = self.by_street[street]
        mood = "rattled" if d.fear >= 0.6 else "on edge" if d.fear >= 0.3 else None
        return f"{mood}, but the {d.watch.name} is on it" if mood and d.watch else mood

    def levels(self, town: Town) -> list[dict]:
        """What the browser sees of each district: levels, trends since the last morning, and any watch and founder."""
        return [{"street": s, "name": s.title(), "crime": level(d.crime), "fear": level(d.fear),
                 "crime_trend": _trend(d.crime, d.was[0]), "fear_trend": _trend(d.fear, d.was[1]),
                 "watch": d.watch.name if d.watch else None,
                 "founder": town.name_of(d.watch.founder) if d.watch else None}
                for s, d in self.by_street.items()]
