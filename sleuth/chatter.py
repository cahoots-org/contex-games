"""App chatter: now and then a resident posts on the neighborhood app, in their own voice."""

import re
from random import Random

from sleuth.case import CRIMES
from sleuth.faith import FAITH, GORE
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.town import Town
from sleuth.writer import Writer, invents_facts

POSTS = {"lost": "a lost-pet or lost-item post", "note": "a passive-aggressive note to the neighbours",
         "gripe": "a gripe about something in town, true to your quirks",
         "theory": "your own theory about the open case, as opinion, not fact"}
ITEMS = {item for kind in CRIMES.values() for item in kind.items if item}


def swaps_item(line: str, case_text: str, firsts: set[str]) -> bool:
    """Whether a line that names someone in the case gives them a crime item the case doesn't, like a cash box for a
    till."""
    named = any(re.search(rf"\b{re.escape(f)}\b", line) and re.search(rf"\b{re.escape(f)}\b", case_text) for f in firsts)
    return named and any(re.search(rf"\b{re.escape(i)}\b", line, re.IGNORECASE) and i not in case_text for i in ITEMS)


async def chatter(writer: Writer, town: Town, rng: Random, ids: Ids, case_text: str | None,
                  somber: bool = False) -> Utterance | None:
    """A random resident's post of a random kind, a theory only while a case is open, somber when it is a death; None
    when nobody has quirks or the line is empty, of faith, grisly, or adds or swaps a case fact."""
    quirky = [v for v in town.villagers if v.quirks]
    if not quirky:
        return None
    v = rng.choice(quirky)
    kind = rng.choice([k for k in POSTS if case_text or k != "theory"])
    line = await writer.post(v, POSTS[kind], case_text, somber)
    firsts = {o.name.split()[0] for o in town.villagers}
    if (not line or FAITH.search(line) or GORE.search(line) or invents_facts(line, case_text or "", firsts)
            or swaps_item(line, case_text or "", firsts)):
        return None
    return Utterance(ids.next("u"), v.id, v.name, v.home, line, None, "posted")
