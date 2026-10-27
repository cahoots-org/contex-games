"""The town's cases as they happen: staged, checked for solvability, opened in the neighborhood app, gone cold."""

import logging
import math
from dataclasses import asdict, dataclass, field
from random import Random

from sleuth.case import (
    WHEN, Crime, Record, camera_clip, discovery, found_it, logs, make_solvable, scene_clues, stage_crime, told,
    witness_memories,
)
from sleuth.config import Config
from sleuth.game import PHASES
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.town import STREETS, Town, at

log = logging.getLogger(__name__)

APP = "The neighborhood app"
COLD = "The case went cold. It was {name}."


@dataclass
class CaseFile:
    crime: Crime
    records: dict[str, Record]
    state: str  # "setup" | "open" | "closed"
    opened: float = 0.0  # game time (day + phase index / 4) the news broke
    roots: dict[str, str] = field(default_factory=dict)  # utterance id → "news" | "memory" | "cover" | "episode"
    alibi: list[str] | None = None
    whereabouts: dict[str, list[str]] = field(default_factory=dict)  # the crime phase's log
    published: list[str] = field(default_factory=list)
    solved_by: str | None = None
    pressed: str = ""  # "day:phase" last pressed
    pressed_by: str = ""  # the podcaster who last asked around
    warned: str = ""  # "day:phase" the culprit last warned someone
    words: dict[str, list] = field(default_factory=dict)  # "speaker:about" → [household word, sound]


def case_json(case: CaseFile, town: Town, routine, today: float | None = None) -> dict:
    """What a player sees of a case on today, titled like "Ada Reyes's bike", with who besides the victim is usually
    at the scene in its part of the day: a lead from routine alone, never from where anyone actually was."""
    c = case.crime
    nearby = [v.id for v in town.villagers
              if v.id != c.victim and routine is not None and routine.place(v.id, c.phase) == c.place]
    return {"id": c.id, "text": told(c.text, c, today), "place": c.place, "phase": c.phase, "day": c.day, "state": case.state,
            "private": c.owner is not None, "title": f"{town.name_of(c.victim)}'s {c.item}", "victim": c.victim,
            "nearby": nearby}


class Cases:
    def __init__(self, config: Config, town: Town, routine, rng: Random, ids: Ids):
        self.config = config
        self.town = town
        self.routine = routine
        self.rng = rng
        self.ids = ids
        self.files: dict[str, CaseFile] = {}
        self.last_closed = -math.inf
        # Game time (day + phase index / 4) of the last tick.
        self.now = 0.0

    def to_state(self) -> dict:
        """Every case file and when the last shared case closed, as plain JSON."""
        return {"files": [asdict(f) for f in self.files.values()], "last_closed": self.last_closed}

    def restore(self, state: dict) -> None:
        """Replace the case files with a saved state."""
        self.files = {}
        for f in state["files"]:
            records = {k: Record(**r) for k, r in f["records"].items()}
            self.files[f["crime"]["id"]] = CaseFile(**{**f, "crime": Crime(**f["crime"]), "records": records})
        self.last_closed = state["last_closed"]

    def shared(self) -> CaseFile | None:
        return next((f for f in self.files.values() if f.state != "closed" and f.crime.owner is None), None)

    def private(self, player_id: str) -> CaseFile | None:
        """The player's private open case."""
        return next((f for f in self.files.values() if f.state == "open" and f.crime.owner == player_id), None)

    def for_player(self, player_id: str) -> CaseFile | None:
        """The player's private open case, otherwise the shared open case."""
        return self.private(player_id) or next(
            (f for f in self.files.values() if f.state == "open" and f.crime.owner is None), None)

    def busy(self) -> set[str]:
        """Culprits of cases still being set up, who stay at the crime place."""
        return {f.crime.culprit for f in self.files.values() if f.state == "setup"}

    def culprit_case(self, vid: str) -> CaseFile | None:
        return next((f for f in self.files.values() if f.state != "closed" and f.crime.culprit == vid), None)

    def alibi(self, vid: str) -> str | None:
        """The culprit's claim to have been where the routine expects them during the crime, its time as WHEN."""
        case = self.culprit_case(vid)
        if case is None:
            return None
        phase = case.crime.phase
        place = self.routine.place(vid, phase)
        case.alibi = [place]
        where = f"at home {at(place)}" if place in STREETS else at(place)
        return f"I was {where} {WHEN}, all {phase}."

    def blame(self, vid: str) -> str | None:
        """The culprit's hint at someone who dislikes the victim, else at the culprit's own coldest tie, its time as
        WHEN."""
        case = self.culprit_case(vid)
        if case is None:
            return None
        crime = case.crime
        victim = self.town.get(crime.victim)
        rivals = [(v.warmth[victim.id], v.id) for v in self.town.villagers
                  if v.id not in (crime.culprit, victim.id) and v.warmth.get(victim.id, 0.0) < 0]
        ties = [(w, t) for t, w in self.town.get(vid).warmth.items() if t not in (victim.id, vid) and t in self.town]
        pick = min(rivals or ties, default=None)
        if pick is None:
            return None
        name = self.town.get(pick[1]).name
        return f"{name} has never liked {victim.name.split()[0]}. I'd ask where they were {WHEN}."

    def close(self, file: CaseFile, solved_by: str | None) -> None:
        """Close a case, solved or not; the next crime waits crime_every_days from now."""
        file.state, file.solved_by = "closed", solved_by
        self.last_closed = self.now

    def brief(self, feed, player_id: str, today: float | None) -> None:
        """Tell a player just off the practice case the town's open case and, unless the feed still replays it, its
        news."""
        case = self.shared()
        if case is None or case.state != "open":
            return
        crime = case.crime
        feed.on_case(case_json(case, self.town, self.routine, today), player=player_id)
        if any(e.kind == "post" and e.data["app"] and e.data["case_id"] == crime.id for e in feed.recent):
            return
        news = Utterance("", "app", APP, crime.place, told(crime.text, crime, today), None, "posted")
        feed.on_post(news, crime.id, player=player_id)

    def mark_cover(self, vid: str, uid: str) -> None:
        if case := self.culprit_case(vid):
            case.roots[uid] = "cover"

    def root_kind(self, uid: str) -> tuple[CaseFile, str] | None:
        """The case a lineage root belongs to, and what kind of root it is."""
        return next(((f, f.roots[uid]) for f in self.files.values() if uid in f.roots), None)

    def cautious(self, day: int) -> dict[str, str]:
        """What each culprit of a case not closed wore at their crime before day, which they won't wear again."""
        worn = {f.crime.culprit: self.town.outfit(f.crime.culprit, f.crime.day) for f in self.files.values()
                if f.state != "closed" and f.crime.day < day}
        return {vid: coat for vid, coat in worn.items() if coat}

    def dress(self, day: int) -> None:
        """Dress the town for day, culprits avoiding their crime's outfit."""
        self.town.dress(day, self.rng, self.cautious(day), math.ceil(self.config.case_days) + 2)

    async def on_tick(self, engine, day: int, phase: str, finished: dict[str, list[str]], playing: bool) -> None:
        """Dress the town, finish setup cases, let old ones go cold, and stage a crime when it is time."""
        self.dress(day)
        now = self.now = day + PHASES.index(phase) / len(PHASES)
        for case in [f for f in self.files.values() if f.state == "setup"]:
            try:
                await self._finish(engine, case, finished, now)
            except Exception:
                log.exception("finishing %s failed", case.crime.id)
                self._drop(case, now)
        for case in [f for f in self.files.values() if f.state == "open"]:
            if now - case.opened >= self.config.case_days:
                self.close(case, None)
                cold = COLD.format(name=self.town.name_of(case.crime.culprit))
                engine.feed.on_case_closed(case.crime.id, cold)
        if playing and self.shared() is None and now - self.last_closed >= self.config.crime_every_days:
            self._stage(day, phase)

    def _involved(self) -> set[str]:
        """The culprits and victims of every case not yet closed."""
        return {vid for f in self.files.values() if f.state != "closed" for vid in (f.crime.culprit, f.crime.victim)}

    async def _finish(self, engine, case: CaseFile, finished: dict[str, list[str]], now: float) -> None:
        """Add the phase's logs, then open the case and tell its witnesses and victim what they saw and found if it is
        solvable, and drop it if not."""
        crime = case.crime
        case.whereabouts = dict(finished)
        for r in logs(crime, finished, self.town, self.rng, self.ids):
            case.records[r.id] = r
        added = make_solvable(crime, list(case.records.values()), self.town, self.routine, self.rng, self.ids)
        if added is None:
            self._drop(case, now)
            return
        for m in [*added, discovery(crime, self.town, self.rng, self.ids)]:
            case.records[m.id] = m
        for m in case.records.values():
            if m.kind in ("memory", "discovery"):
                await self._remember(engine, case, m)
        case.state, case.opened = "open", now
        news = Utterance(self.ids.next("u"), "app", APP, crime.place, told(crime.text, crime, now), None, "posted")
        victim = self.town.get(crime.victim)
        hearers = [victim.id, *(v.id for v in self.town.villagers if v.household == victim.household),
                   *(v.id for v in self.town.present(crime.place))]
        case.roots[news.id] = "news"
        await engine.deliver(news, list(dict.fromkeys(hearers)))
        engine.feed.on_case(case_json(case, self.town, self.routine, now))
        engine.feed.on_post(news, crime.id)

    def _drop(self, case: CaseFile, now: float) -> None:
        """Forget a case that never opened; the next waits crime_every_days as after a close."""
        self.files.pop(case.crime.id, None)
        self.last_closed = now

    def _stage(self, day: int, phase: str) -> None:
        crime = stage_crime(self.town, self.routine, self.rng, day, phase, self.ids.next("case"),
                            exclude=self._involved())
        if crime is None:
            return
        self.town.move(crime.culprit, crime.place)
        records = [*witness_memories(crime, self.town, self.routine, self.rng, self.ids),
                   *scene_clues(crime, self.town, self.routine, self.rng, self.ids)]
        clip = camera_clip(crime, self.town, self.ids)
        self.files[crime.id] = CaseFile(crime, {r.id: r for r in [*records, *([clip] if clip else [])]}, "setup")

    async def _remember(self, engine, case: CaseFile, m: Record) -> None:
        """Tell the witness what they saw, or the victim in their own words what they found, rooted in the case."""
        text = found_it(case.crime, m.clock) if m.kind == "discovery" else m.text
        u = Utterance(self.ids.next("u"), "memory", self.town.get(m.holder).name, case.crime.place, text, None, "saw")
        case.roots[u.id] = "memory"
        m.utterance = u.id
        await engine.deliver(u, [m.holder], addressed=True)
