"""Someone moving into town when a resident leaves."""

import logging

from sleuth.feed import APP
from sleuth.models import Utterance, Villager
from sleuth.offenders import Offender
from sleuth.town import place_name
from sleuth.town_gen import generate_resident, settle
from sleuth.traits import assign_look

log = logging.getLogger(__name__)


def moved_in(name: str, occupation: str, street: str) -> str:
    """The app's post on a newcomer; the job stands as its own line, so it reads whatever its case or article."""
    return f"{name} moved in on {street}. {occupation[:1].upper()}{occupation[1:]}."


async def move_in(engine, home: str) -> Villager | None:
    """A new resident moves in on home's street, perhaps an offender while there is room, and the app says so: one
    Haiku call and one Jev call. None while the town is full, or when it fails, touching no one else then."""
    town, config, offenders = engine.town, engine.config, engine.cases.offenders
    if town.alive_count >= config.population:
        return None
    try:
        rng = engine.cases.rng
        v = await generate_resident(engine.writer, [*town.villagers, *town.departed], rng)
        seen = [r.traits for f in engine.cases.files.values() if f.state == "open" for r in f.records.values()
                if r.kind in ("memory", "clip", "clue")]
        assign_look(v, town.villagers, rng, seen)
        v.home = home
        await engine.baselines.load(v.needs)
        await engine.routine.add(v)
        await engine.add_villager(v, engine.routine.place(v.id, engine.game.phase) or home)
        settle(v, town.villagers, home, rng)
        if (len(offenders.active) < config.max_offenders and offenders.room(town) > 0
                and rng.random() < config.newcomer_offender_chance):
            offenders.active[v.id] = Offender()
        text = moved_in(v.name, v.occupation, place_name(home))
        engine.feed.on_post(Utterance("", "app", APP, home, text, None, "posted"), None)
        return v
    except Exception:
        log.exception("moving in on %s failed", home)
        return None
