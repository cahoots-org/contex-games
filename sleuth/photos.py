"""Photos on the neighborhood app: a few residents at a public place in some part of a day, in what they wore."""

from dataclasses import asdict, dataclass
from random import Random

from sleuth.lineage import Ids
from sleuth.town import PUBLIC_PLACES, Town, at
from sleuth.traits import IN_PERSON, describe, face

PHOTO_PHASES = ("morning", "afternoon", "evening")
# How many residents a photo shows, at least and at most.
PEOPLE = (2, 3)
KEPT = 60


@dataclass
class Photo:
    id: str
    place: str
    day: int
    phase: str
    people: dict[str, dict[str, str]]  # vid → how they looked in person that day
    caption: str


def photo_json(photo: Photo, town: Town) -> dict:
    """What the page shows of a photo: its caption and each resident in it with their looks and face."""
    people = [{"id": vid, "name": town.name_of(vid), "looks": describe(looks), "face": face(looks)}
              for vid, looks in photo.people.items()]
    return {"id": photo.id, "place": photo.place, "day": photo.day, "phase": photo.phase, "caption": photo.caption,
            "people": people}


class Album:
    """The photos posted to the app, newest last."""

    def __init__(self, rng: Random | None = None):
        self.rng = rng or Random()
        self.photos: list[Photo] = []

    def to_state(self) -> dict:
        return {"photos": [asdict(p) for p in self.photos]}

    def restore(self, state: dict) -> None:
        self.photos = [Photo(**p) for p in state["photos"]]

    def get(self, photo_id: str) -> Photo | None:
        return next((p for p in self.photos if p.id == photo_id), None)

    def take(self, town: Town, day: int, phase: str, whereabouts: dict[str, list[str]], ids: Ids,
             exclude: set[str] = frozenset()) -> Photo | None:
        """A photo of 2 or 3 residents logged together at a public place that part of the day, none of exclude; None
        at night or when no place had 2."""
        if phase not in PHOTO_PHASES:
            return None
        crowds: dict[str, list[str]] = {}
        for vid, places in whereabouts.items():
            if vid in town and vid not in exclude:
                for place in dict.fromkeys(places):
                    if place in PUBLIC_PLACES:
                        crowds.setdefault(place, []).append(vid)
        places = sorted(p for p, vids in crowds.items() if len(vids) >= PEOPLE[0])
        if not places:
            return None
        place = self.rng.choice(places)
        vids = self.rng.sample(crowds[place], min(self.rng.randint(*PEOPLE), len(crowds[place])))
        people = {vid: {c: v for c, v in town.looks(vid, day).items() if c in IN_PERSON} for vid in vids}
        named = [town.get(vid).name + (f" in a {looks['coat']}" if "coat" in looks else "")
                 for vid, looks in people.items()]
        photo = Photo(ids.next("r"), place, day, phase, people, f"{phase.capitalize()} {at(place)}: {', '.join(named)}.")
        self.photos.append(photo)
        del self.photos[:-KEPT]
        return photo
