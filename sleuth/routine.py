"""Each villager's work and leisure place, chosen once by Jev and kept beside the seed."""

import asyncio
import json
import logging
import os
import tempfile

from typesafe_sdk import Choice

from sleuth.config import Config
from sleuth.models import Villager
from sleuth.town import PUBLIC_PLACES

log = logging.getLogger(__name__)

WORK_INSTRUCTIONS = "Where in town does this resident spend their working day, given their occupation?"
LEISURE_INSTRUCTIONS = "Where in town does this resident go to unwind in the evening, given their personality?"

ROUTINE_PLACES = PUBLIC_PLACES


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
            and entry.get("work") in ROUTINE_PLACES
            and entry.get("leisure") in ROUTINE_PLACES
        )

    async def _ask(self, v: Villager) -> None:
        self.entries.pop(v.id, None)
        questions = {
            "work": Choice(instructions=WORK_INSTRUCTIONS, criteria={p: None for p in ROUTINE_PLACES}),
            "leisure": Choice(instructions=LEISURE_INSTRUCTIONS, criteria={p: None for p in ROUTINE_PLACES}),
        }
        state = {"name": v.name, "occupation": v.occupation, "personality": v.personality}
        try:
            async with self._asking:
                resp = await self.jev.system_one(state=state, questions=questions)
            work, leisure = resp.choices["work"].choice, resp.choices["leisure"].choice
            if work not in ROUTINE_PLACES or leisure not in ROUTINE_PLACES:
                raise ValueError("unknown place")
        except Exception:
            log.warning("no routine for %s", v.id, exc_info=True)
            return
        self.entries[v.id] = {"name": v.name, "home": v.home, "work": work, "leisure": leisure}

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
