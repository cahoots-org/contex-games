"""The town's three districts, one per street: how much crime each has seen and how afraid its residents are."""

from dataclasses import asdict, dataclass, field

from sleuth.case import Crime
from sleuth.config import Config
from sleuth.town import STREETS

PLACE_DISTRICT = {"cafe": "elm street", "bar": "elm street", "dog park": "elm street",
                  "gym": "oak street", "school": "oak street", "library": "oak street",
                  "hardware store": "maple street", "grocery": "maple street", "town hall": "maple street",
                  **{s: s for s in STREETS}}
# How far a crime of each tier raises its district's crime and fear.
HIT = {"petty": 0.25, "serious": 0.45, "major": 0.7}
# How far an exposure lowers its district's crime, and fear.
RELIEF = (0.15, 0.1)


def district_of(place: str) -> str:
    return PLACE_DISTRICT[place]


def _clamp(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass
class District:
    crime: float = 0.0
    fear: float = 0.0
    exposures: int = 0  # exposures since it last organized
    was: list[float] = field(default_factory=lambda: [0.0, 0.0])  # crime, fear at the last morning


class Districts:
    def __init__(self, config: Config):
        self.config = config
        self.by_street = {s: District() for s in STREETS}

    def to_state(self) -> dict:
        return {street: asdict(d) for street, d in self.by_street.items()}

    def restore(self, state: dict) -> None:
        self.by_street = {street: District(**d) for street, d in state.items()}

    def on_crime(self, crime: Crime) -> None:
        d = self.by_street[district_of(crime.place)]
        d.crime, d.fear = _clamp(d.crime + HIT[crime.tier]), _clamp(d.fear + HIT[crime.tier])

    def on_exposed(self, crime: Crime) -> None:
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
