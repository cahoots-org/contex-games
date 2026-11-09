"""What listeners loved about a held episode."""

from sleuth.case import Record
from sleuth.cases import CaseFile
from sleuth.episode import label
from sleuth.town import Town

# The listeners each line of credit adds to a held episode's.
CREDIT_BONUS = 50
# The reception of a held episode that earned no credit.
SOLID = "A solid episode."


def _first(town: Town, vid: str) -> str:
    return (town.name_of(vid) or "someone").split()[0]


def credits(file: CaseFile, cited: list[Record], notebook: dict[str, Record], town: Town) -> list[str]:
    """What listeners loved about a held episode on the case, each at most once: a false sighting or trace left out
    for what was cited against it, the accomplice's alibi broken by what was cited, a liar's story held with what
    exposes it, and a case cracked with no witness but the victim."""
    ids = {r.id for r in cited}
    mine = [r for r in notebook.values() if r.case == file.crime.id]
    lines = []
    caught = next((r for r in mine if r.kind in ("memory", "clue") and not r.sound and r.id not in ids
                   and r.disproof in ids), None)
    if caught:
        lines.append(f"Listeners loved how you caught {label(caught, town)}.")
    if file.accomplice and any(r.kind == "statement" and r.holder == file.accomplice and not r.sound
                               and r.disproof in ids for r in mine):
        lines.append(f"Listeners loved how you broke {_first(town, file.accomplice)}'s alibi for "
                     f"{_first(town, file.crime.culprit)}.")
    liar = next((vid for vid, secret in file.liars.items()
                 if any(r.kind == "statement" and r.holder == vid and r.who is None and not r.sound for r in mine)
                 and (secret["exposer"] in notebook
                      or any(r.kind == "statement" and r.holder == secret["exposer"] and r.who == vid and r.sound
                             for r in mine))), None)
    if liar:
        lines.append(f"Listeners loved that you didn't fall for {_first(town, liar)}'s story.")
    if not any(r.kind == "memory" and r.holder != file.crime.victim for r in file.records.values()):
        lines.append("Listeners loved that you cracked it without a single witness.")
    return lines or [SOLID]
