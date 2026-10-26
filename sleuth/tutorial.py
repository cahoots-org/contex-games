"""The practice town where a new podcaster's first case happens, apart from the real town."""

from random import Random

from sleuth.case import WHEN, Crime, Record
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.game import Game
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.reputation import Reputation
from sleuth.routine import Routine
from sleuth.town import Town

# A day so long that the practice clock never moves on from early afternoon.
FROZEN_DAY_SECONDS = 10**9
NOW = {"day": 1, "phase": "afternoon", "elapsed": 0.3}
# id: name, occupation, personality, grudge, household, street, height, hair, coat, car, work place, evening place
RESIDENTS = {
    "t1": ("Ruth Okafor", "librarian", "precise and warm", "Cal Hughes sneers at her overdue notices", "h1",
           "elm street", "short", "dark-haired", "denim jacket", "blue hatchback", "library", "cafe"),
    "t2": ("Dev Okafor", "hardware clerk", "easygoing and chatty", "none", "h1",
           "elm street", "average height", "bald", "grey hoodie", "silver minivan", "hardware store", "bar"),
    "t3": ("Tess Moreno", "retired teacher", "observant and fussy", "none", "h2",
           "oak street", "short", "grey-haired", "plaid flannel", "bicycle", "library", "dog park"),
    "t4": ("Gus Moreno", "barista", "loud and generous", "none", "h2",
           "oak street", "tall", "red-haired", "black puffer", "white sedan", "cafe", "gym"),
    "t5": ("Cal Hughes", "grocery stocker", "sullen and proud", "Ruth Okafor fined him and posted about it", "h3",
           "maple street", "tall", "red-haired", "green raincoat", "red pickup", "grocery", "bar"),
    "t6": ("Ivy Hughes", "teacher", "cheerful and busy", "none", "h3",
           "maple street", "average height", "blond", "green raincoat", "bicycle", "school", "gym"),
}
# Both ways: a's tie to b, b's back to a, and the warmth they share.
TIES = (("t1", "t2", "spouse", "spouse", 0.8), ("t3", "t4", "spouse", "spouse", 0.7),
        ("t5", "t6", "sibling", "sibling", 0.6), ("t1", "t5", "rival", "rival", -0.6),
        ("t1", "t3", "friend", "friend", 0.5), ("t2", "t4", "friend", "friend", 0.4),
        ("t4", "t5", "coworker", "coworker", 0.2))
# Tess saw a tall, red-haired figure (Gus or Cal); the thread is from a green raincoat (Cal or Ivy): only Cal is both.
CRIME = ("steal", "tote bag", "t5", "t1", "library", 1, "morning", 590, "rival",
         f"Someone stole Ruth Okafor's tote bag at the library {WHEN}.")
RECORDS = (
    ("memory", "library", "9:45am", "Around 9:45am, at the library, someone tall, red-haired walked off with something.",
     "t3", {"height": "tall", "hair": "red-haired"}, None),
    ("discovery", "library", "10:05am", "Around 10:05am, Ruth Okafor found the tote bag missing at the library.",
     "t1", {}, None),
    ("clue", "library", "", "A thread at the library, snagged from a figure in a green raincoat.",
     "", {"coat": "green raincoat"}, None),
    ("log", "library", "9:20am", "Library checkout: Tess Moreno, 9:20am", "", {}, "t3"),
)


def residents() -> list[Villager]:
    """The practice town's residents, new each time."""
    town = {}
    for vid, (name, job, personality, grudge, household, street, *looks, work, leisure) in RESIDENTS.items():
        town[vid] = Villager(vid, name, job, personality, grudge, [], {}, dict(zip(("height", "hair", "coat", "car"), looks)),
                             street, household)
    for a, b, kind, back, warmth in TIES:
        town[a].relationships[b], town[b].relationships[a] = kind, back
        town[a].warmth[b] = town[b].warmth[a] = warmth
    return list(town.values())


class Practice:
    """What a Player uses of the engine, in the practice town: its own frozen clock, case, routine and regard, and
    the real Jev. Nobody hears, talks or warns anyone there."""

    def __init__(self, engine, ids: Ids, config: Config, player_id: str, saved: dict | None = None):
        self.config, self.jev, self.players = config, engine.jev, engine.players
        self.town = Town()
        self.routine = Routine(None, "", config)
        for v in residents():
            *_, work, leisure = RESIDENTS[v.id]
            self.routine.entries[v.id] = {"name": v.name, "home": v.home, "work": work, "leisure": leisure}
            self.town.add(v, work)
        self.game = Game(FROZEN_DAY_SECONDS)
        self.game.restore(NOW)
        self.reputation = Reputation(config)
        self.cases = Cases(config, self.town, self.routine, Random(), ids)
        if saved is None:
            self._open(player_id, ids)
        else:
            self.cases.restore(saved)

    def _open(self, player_id: str, ids: Ids) -> None:
        crime = Crime(ids.next("case"), *CRIME, owner=player_id)
        records = [Record(ids.next("r"), crime.id, kind, place, clock, text, holder, traits, who, day=crime.day)
                   for kind, place, clock, text, holder, traits, who in RECORDS]
        whereabouts = {v.id: [self.routine.place(v.id, crime.phase)] for v in self.town.villagers}
        whereabouts[crime.culprit] = [crime.place]
        self.cases.files[crime.id] = CaseFile(crime, {r.id: r for r in records}, "open", opened=crime.day,
                                              whereabouts=whereabouts)

    async def press(self, file: CaseFile, player_id: str) -> None:
        """The practice culprit never hears that anyone is asking."""

    async def recall_heard(self, vid: str, text: str) -> list:
        """No one in the practice town has heard anything."""
        return []
