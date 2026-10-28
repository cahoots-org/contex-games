"""Each villager's work and leisure place, chosen once by Jev, the work place fitting the job, and kept beside the
seed."""

import asyncio
import json
import logging
import os
import re
import tempfile

from typesafe_sdk import Choice

from sleuth.config import Config
from sleuth.models import Villager
from sleuth.town import PUBLIC_PLACES

log = logging.getLogger(__name__)

WORK_INSTRUCTIONS = "Where in town does this resident spend their working day, given their occupation?"
LEISURE_INSTRUCTIONS = "Where in town does this resident go to unwind in the evening, given their personality?"

ROUTINE_PLACES = PUBLIC_PLACES
# Work done at home, or away on a night shift, so the resident is home by day.
HOME = "home"
# Where an occupation that names it works; the first match wins, so a retired teacher is home.
WORKPLACES = tuple((place, re.compile(words, re.IGNORECASE)) for place, words in (
    (HOME, r"retired|night[- ]?shift|overnight|from home|remote|stay-at-home|homemaker|freelance"),
    ("library", r"librar|archiv|book ?(?:seller|store|shop)"),
    ("school", r"school|teacher|principal|tutor|custodian|janitor|crossing guard|band director|coach"),
    ("hardware store", r"hardware|plumb|electrician|carpent|handyman|locksmith|mechanic|contractor"),
    ("grocery", r"grocer|cashier|\bdeli\b|produce|stocker|checkout|florist"),
    ("town hall", r"town hall|mayor|clerk|council|municipal|permit|treasurer|planner|zoning|police|sheriff|postal"
                  r"|post office|mail carrier"),
    ("bar", r"\bbar\b|bartend|\bpub\b|brew|tavern|bouncer"),
    ("cafe", r"\bcaf[eé]\b|barista|coffee|baker|bakery|pastry|\bcook\b|chef"),
    ("gym", r"\bgym\b|trainer|fitness|yoga|pilates|swim"),
    ("dog park", r"dog park|\bdog|\bpet\b|groom|veterinar|\bvet\b|park ranger|landscap|garden"),
    (HOME, r"writer|author|novelist|artist|illustrator|painter|potter|musician|composer|photograph|designer"
           r"|programmer|developer|software|translat|accountant|bookkeep|consultant|tailor|seamstress|nurse|doctor"
           r"|dentist|pharmac|therapist|real estate|insurance|trucker|driver|pilot"),
))


def workplace(occupation: str) -> str | None:
    """Where in town the occupation's work is, HOME for work at home or out of town, None when it names nowhere."""
    return next((place for place, words in WORKPLACES if words.search(occupation)), None)


def _work(v: Villager, chosen: str | None) -> str | None:
    """The place the resident's job names, else chosen, HOME being their street."""
    place = workplace(v.occupation) or chosen
    return v.home if place == HOME else place


class Routine:
    """Where each villager is at each part of the day: work, work, leisure, home."""

    def __init__(self, jev, path: str, config: Config):
        self.jev = jev
        self.path = path
        self.entries: dict[str, dict] = {}
        self._asking = asyncio.Semaphore(config.routine_concurrency)

    async def load(self, villagers: list[Villager]) -> None:
        """Read the sidecar, then ask Jev about every villager it lacks."""
        self.entries = self._read()
        stale = [v for v in villagers if not self._known(v)]
        if not stale:
            return
        await asyncio.gather(*(self._ask(v) for v in stale))
        self._write()

    async def add(self, v: Villager) -> None:
        await self._ask(v)
        self._write()

    def place(self, vid: str, phase: str) -> str | None:
        entry = self.entries.get(vid)
        if entry is None:
            return None
        return {"evening": entry["leisure"], "night": entry["home"]}.get(phase, entry["work"])

    def _known(self, v: Villager) -> bool:
        entry = self.entries.get(v.id)
        return (
            entry is not None
            and entry.get("name") == v.name
            and entry.get("home") == v.home
            and entry.get("work") in (*ROUTINE_PLACES, v.home)
            and entry.get("work") == _work(v, entry.get("work"))
            and entry.get("leisure") in ROUTINE_PLACES
        )

    async def _ask(self, v: Villager) -> None:
        self.entries.pop(v.id, None)
        questions = {
            "work": Choice(instructions=WORK_INSTRUCTIONS, criteria={p: None for p in (*ROUTINE_PLACES, HOME)}),
            "leisure": Choice(instructions=LEISURE_INSTRUCTIONS, criteria={p: None for p in ROUTINE_PLACES}),
        }
        state = {"name": v.name, "occupation": v.occupation, "personality": v.personality}
        try:
            async with self._asking:
                resp = await self.jev.system_one(state=state, questions=questions)
            work, leisure = resp.choices["work"].choice, resp.choices["leisure"].choice
            if work not in (*ROUTINE_PLACES, HOME) or leisure not in ROUTINE_PLACES:
                raise ValueError("unknown place")
        except Exception:
            log.warning("no routine for %s", v.id, exc_info=True)
            return
        self.entries[v.id] = {"name": v.name, "home": v.home, "work": _work(v, work), "leisure": leisure}

    def _read(self) -> dict[str, dict]:
        try:
            with open(self.path) as f:
                data = json.load(f)
            return {k: dict(v) for k, v in data.items()}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _write(self) -> None:
        """Save the sidecar; it is only a cache, so a failure is logged and the game goes on."""
        directory = os.path.dirname(os.path.abspath(self.path))
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(self.entries, f)
            os.replace(tmp, self.path)
        except OSError:
            log.warning("saving the routine places failed")
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
