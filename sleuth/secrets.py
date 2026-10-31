"""Innocent residents who lie about where they were, each to hide a secret someone or something on file gives away."""

from random import Random

from sleuth.case import LOG_PLACES, Crime, Record
from sleuth.town import STREETS, Town

# Each kind's reason, said after "{name} was", and what exposes it: the place's log, or a person who says so.
SECRETS = {
    "somewhere": ("at the {place} when they'd said they were home", "log"),
    "surprise": ("planning a surprise for {tie}", "co-conspirator"),
    "job": ("interviewing for a job at the {place}", "coworker"),
    "hobby": ("at a {hobby} class they'd rather no one knew about", "log"),
    "covering": ("covering for {friend}, who'd been up to something small", "friend"),
}
HOBBIES = ("line dancing", "pottery", "magic tricks", "competitive yo-yo")
# Where a hobby class is held.
CLASS_PLACES = ("gym", "library")
# Workplaces no one interviews at.
NO_INTERVIEWS = ("school",)


def pick_liar(crime: Crime, whereabouts: dict[str, list[str]], town: Town, routine, rng: Random, barred: set[str],
              records: list[Record], kinds=tuple(SECRETS)) -> tuple[str, dict] | None:
    """A resident, not the culprit, victim or anyone barred, who was somewhere other than home during the crime and
    says they were home, with a secret of one of kinds, each fitting kind as likely, whose exposer exists: a log of
    theirs on file, or someone not the culprit or victim who knows. None when no one fits."""
    logged = {(r.who, r.place): r.id for r in records if r.kind == "log" and r.sound and not r.trail}
    knows = [v for v in town.villagers if v.id not in (crime.culprit, crime.victim)]
    options: dict[str, list] = {kind: [] for kind in kinds}
    for v in town.villagers:
        if v.id in barred or v.id in (crime.culprit, crime.victim):
            continue
        ties = [o for o in knows if o.id in v.relationships]
        for place in dict.fromkeys(p for p in whereabouts.get(v.id, []) if p not in STREETS):
            log = logged.get((v.id, place))
            with_them = [o for o in ties if place in whereabouts.get(o.id, [])]
            found = {
                "somewhere": [(log, {})] if log and place in LOG_PLACES else [],
                "hobby": [(log, {"hobby": rng.choice(HOBBIES)})] if log and place in CLASS_PLACES else [],
                "surprise": [(o.id, {"tie": t.name}) for o in with_them for t in ties if t.id != o.id],
                "job": [(o.id, {}) for o in knows if o.id != v.id and routine.place(o.id, "morning") == place]
                if place not in NO_INTERVIEWS and routine.place(v.id, "morning") != place else [],
                "covering": [(o.id, {"friend": o.name}) for o in with_them],
            }
            for kind in kinds:
                options[kind] += [(v, place, exposer, words) for exposer, words in found[kind]]
    fitting = [kind for kind in kinds if options[kind]]
    if not fitting:
        return None
    kind = rng.choice(fitting)
    v, place, exposer, words = rng.choice(options[kind])
    reason = SECRETS[kind][0].format(place=place, **words)
    return v.id, {"kind": kind, "place": place, "claimed": v.home, "exposer": exposer,
                  "text": f"{v.name.split()[0]} was {reason}"}
