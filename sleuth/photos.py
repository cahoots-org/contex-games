"""Photos on the neighborhood app: a resident posts a few residents, themself among them, at a public place in some part
of a day, in what they wore."""

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
    poster: str  # vid of who posted it, one of the people in it


def posted(photo: Photo, town: Town) -> str:
    """The post as one line, like "Bev Kowalczyk posted: Evening at the bar with …!"."""
    return f"{town.name_of(photo.poster)} posted: {photo.caption}"


def photo_json(photo: Photo, town: Town) -> dict:
    """What the page shows of a photo: who posted it, its caption, and each resident in it with their looks and face."""
    people = [{"id": vid, "name": town.name_of(vid), "looks": describe(looks), "face": face(looks)}
              for vid, looks in photo.people.items()]
    return {"id": photo.id, "poster": town.name_of(photo.poster), "caption": photo.caption, "people": people}


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
        """A photo of 2 or 3 residents logged together at a public place that part of the day, none of exclude, posted
        by one of them; None at night or when no place had 2."""
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
        poster = self.rng.choice(vids)
        named = [town.get(vid).name + (f" in a {looks['coat']}" if "coat" in looks else "")
                 for vid, looks in people.items() if vid != poster]
        photo = Photo(ids.next("r"), place, day, phase, people,
                      f"{phase.capitalize()} {at(place)} with {' and '.join(named)}!", poster)
        self.photos.append(photo)
        del self.photos[:-KEPT]
        return photo
