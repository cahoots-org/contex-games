"""The town's cases as they happen: staged, checked for solvability, opened in the neighborhood app, gone cold."""

import logging
import math
from dataclasses import asdict, dataclass, field
from random import Random

from sleuth.case import (
    CRIMES, WHEN, Crime, Record, camera_clip, crime_title, discovery, found_it, logs, make_solvable, scene_clues, stage_crime, told,
    witness_memories,
)
from sleuth.config import Config
from sleuth.game import PHASES
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.offenders import Offenders
from sleuth.town import STREETS, Town, at

log = logging.getLogger(__name__)

APP = "The neighborhood app"
COLD = "The case went cold. It was {name}."
THANKS = "Got my {item} back thanks to that podcast!"
# How many crimes are drawn in one go for a solvable one.
DRAWS = 10


@dataclass
class CaseFile:
    crime: Crime
    records: dict[str, Record]
    state: str  # "open" | "closed"
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
            "private": c.owner is not None, "title": crime_title(c, town), "victim": c.victim,
            "nearby": nearby}


class Cases:
    def __init__(self, config: Config, town: Town, routine, rng: Random, ids: Ids):
        self.config = config
        self.town = town
        self.routine = routine
        self.rng = rng
        self.ids = ids
        self.files: dict[str, CaseFile] = {}
        self.offenders = Offenders(config)
        # Game time (day + phase index / 4) of the last tick.
        self.now = 0.0
        # Everyone's whereabouts through the part of the day the last tick finished.
        self.finished: dict[str, list[str]] | None = None

    def to_state(self) -> dict:
        """Every case file and the offenders as plain JSON."""
        return {"files": [asdict(f) for f in self.files.values()], "offenders": self.offenders.to_state()}

    def restore(self, state: dict) -> None:
        """Replace the case files and offenders with a saved state, leaving out cases saved before they opened."""
        self.offenders.restore(state["offenders"])
        self.files = {}
        for f in state["files"]:
            if f["state"] == "setup":
                continue
            records = {k: Record(**r) for k, r in f["records"].items()}
            self.files[f["crime"]["id"]] = CaseFile(**{**f, "crime": Crime(**f["crime"]), "records": records})

    def shared(self) -> CaseFile | None:
        return next((f for f in self.files.values() if f.state != "closed" and f.crime.owner is None), None)

    def private(self, player_id: str) -> CaseFile | None:
        """The player's private open case."""
        return next((f for f in self.files.values() if f.state == "open" and f.crime.owner == player_id), None)

    def for_player(self, player_id: str) -> CaseFile | None:
        """The player's private open case, otherwise the shared open case."""
        return self.private(player_id) or next(
            (f for f in self.files.values() if f.state == "open" and f.crime.owner is None), None)

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
        """Close a case, solved or not."""
        file.state, file.solved_by = "closed", solved_by

    async def on_held(self, engine, file: CaseFile, player_id: str) -> None:
        """A held episode closes the case and wins the town's regard; a petty culprit is exposed, and the next case
        opens."""
        crime = file.crime
        self.close(file, player_id)
        engine.feed.on_case_closed(crime.id, "")
        town = [v.id for v in self.town.villagers if v.id != crime.culprit]
        engine.reputation.nudge_all(player_id, self.config.reputation_right, town)
        if crime.tier == "petty":
            self._expose(engine, file, player_id)
        await self.ensure(engine)

    def on_wrong(self, engine, file: CaseFile, player_id: str, accused: str) -> None:
        """A wrong episode costs the town's regard, and the accused's most of all."""
        engine.reputation.nudge_all(player_id, self.config.reputation_wrong, [v.id for v in self.town.villagers])
        engine.reputation.nudge(accused, player_id, self.config.reputation_accused)

    def _expose(self, engine, file: CaseFile, player_id: str) -> None:
        """The town learns what the culprit did, and they lie low, cold to the podcaster; the victim's household warms
        to the podcaster, and the victim says thanks on the app."""
        crime, config = file.crime, self.config
        victim = self.town.get(crime.victim)
        self.offenders.exposed[crime.culprit] = f"{CRIMES[crime.template].did} {victim.name}'s {crime.item}"
        if offender := self.offenders.active.get(crime.culprit):
            offender.quiet_until = int(self.now) + config.exposed_quiet_days
        engine.reputation.nudge(crime.culprit, player_id, config.reputation_exposed)
        household = {victim.id, *(v.id for v in self.town.villagers if victim.household and v.household == victim.household)}
        engine.reputation.nudge_all(player_id, config.reputation_ally, household)
        thanks = Utterance("", victim.id, victim.name, crime.place, THANKS.format(item=crime.item), None, "posted")
        engine.feed.on_post(thanks, crime.id)

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

    def hidden(self, day: int, phase: str) -> set[str]:
        """Culprits of cases not closed whose crime was that day and part of it, whom no photo of it shows."""
        return {f.crime.culprit for f in self.files.values()
                if f.state != "closed" and (f.crime.day, f.crime.phase) == (day, phase)}

    def cautious(self, day: int) -> dict[str, str]:
        """The crime-day outfit of each open case's culprit, which they won't wear on later days."""
        worn = {f.crime.culprit: self.town.outfit(f.crime.culprit, f.crime.day) for f in self.files.values()
                if f.state != "closed" and f.crime.day < day}
        return {vid: coat for vid, coat in worn.items() if coat}

    def dress(self, day: int) -> None:
        """Dress the town for day, culprits avoiding their crime's outfit."""
        self.town.dress(day, self.rng, self.cautious(day), math.ceil(self.config.case_days) + 2)

    async def on_tick(self, engine, day: int, phase: str, finished: dict[str, list[str]]) -> None:
        """Dress the town, let exposed offenders reform of a morning, let old cases go cold, and open a new shared case
        when none is open."""
        self.dress(day)
        if phase == "morning":
            self.offenders.new_day(day, self.rng)
        now = self.now = day + PHASES.index(phase) / len(PHASES)
        self.finished = finished
        for case in [f for f in self.files.values() if f.state == "open"]:
            if now - case.opened >= self.config.case_days:
                self.close(case, None)
                self.offenders.escaped_with(case.crime.culprit)
                cold = COLD.format(name=self.town.name_of(case.crime.culprit))
                engine.feed.on_case_closed(case.crime.id, cold)
        await self.ensure(engine)

    async def ensure(self, engine, now: float | None = None) -> None:
        """Open a shared case set in the part of the day just finished, unless one is open, its culprit a ready petty
        offender; now is the game time, else the last tick's. Up to DRAWS crimes are drawn for one that is solvable."""
        if now is not None:
            self.now = now
        if self.shared() is not None:
            return
        before = self.now - 1 / len(PHASES)
        day, phase = math.floor(before), PHASES[int(before % 1 * len(PHASES))]
        pictured = {vid for p in engine.album.photos if (p.day, p.phase) == (day, phase) for vid in p.people}
        self.offenders.top_up(self.town, self.rng)
        culprits = self.offenders.ready(day, "petty")
        for _ in range(DRAWS):
            crime = stage_crime(self.town, self.routine, self.rng, day, phase, self.ids.next("case"),
                                exclude=self._involved() | pictured, culprits=culprits)
            if crime is None:
                return
            try:
                if await self._open(engine, crime, pictured):
                    return
            except Exception:
                log.exception("opening %s failed", crime.id)
                self.files.pop(crime.id, None)

    def _involved(self) -> set[str]:
        """The culprits and victims of every case not yet closed."""
        return {vid for f in self.files.values() if f.state != "closed" for vid in (f.crime.culprit, f.crime.victim)}

    async def _open(self, engine, crime: Crime, pictured: set[str]) -> bool:
        """Leave the crime's evidence, witnessed by no one pictured elsewhere then, and, if it narrows to the culprit,
        open the case: tell its witnesses and victim what they saw and found, and post the news. False if it cannot be
        made solvable."""
        self.dress(crime.day)
        whereabouts = dict(self.finished or {v.id: [p] for v in self.town.villagers
                                             if (p := self.routine.place(v.id, crime.phase))})
        whereabouts[crime.culprit] = [crime.place]
        clip = camera_clip(crime, self.town, self.ids)
        records = [*witness_memories(crime, self.town, self.routine, self.rng, self.ids, pictured),
                   *scene_clues(crime, self.town, self.routine, self.rng, self.ids), *([clip] if clip else []),
                   *logs(crime, whereabouts, self.town, self.rng, self.ids)]
        added = make_solvable(crime, records, self.town, self.routine, self.rng, self.ids, pictured)
        if added is None:
            return False
        records += [*added, discovery(crime, self.town, self.rng, self.ids)]
        case = self.files[crime.id] = CaseFile(crime, {r.id: r for r in records}, "open", opened=self.now,
                                               whereabouts=whereabouts)
        for m in records:
            if m.kind in ("memory", "discovery"):
                await self._remember(engine, case, m)
        news = Utterance(self.ids.next("u"), "app", APP, crime.place, told(crime.text, crime, self.now), None, "posted")
        victim = self.town.get(crime.victim)
        hearers = [victim.id, *(v.id for v in self.town.villagers if v.household == victim.household),
                   *(v.id for v in self.town.present(crime.place))]
        case.roots[news.id] = "news"
        await engine.deliver(news, list(dict.fromkeys(hearers)))
        engine.feed.on_case(case_json(case, self.town, self.routine, self.now))
        engine.feed.on_post(news, crime.id)
        return True

    async def _remember(self, engine, case: CaseFile, m: Record) -> None:
        """Tell the witness what they saw, or the victim in their own words what they found, rooted in the case."""
        text = found_it(case.crime, m.clock) if m.kind == "discovery" else m.text
        u = Utterance(self.ids.next("u"), "memory", self.town.get(m.holder).name, case.crime.place, text, None, "saw")
        case.roots[u.id] = "memory"
        m.utterance = u.id
        await engine.deliver(u, [m.holder], addressed=True)
