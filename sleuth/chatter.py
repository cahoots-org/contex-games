"""App chatter: now and then a resident posts on the neighborhood app, in their own voice."""

from random import Random

from sleuth.faith import FAITH, GORE
from sleuth.lineage import Ids
from sleuth.models import Utterance
from sleuth.town import Town
from sleuth.writer import Writer, invents_facts

POSTS = {"lost": "a lost-pet or lost-item post", "note": "a passive-aggressive note to the neighbours",
         "gripe": "a gripe about something in town, true to your quirks",
         "theory": "your own theory about the open case, as opinion, not fact"}


async def chatter(writer: Writer, town: Town, rng: Random, ids: Ids, case_text: str | None,
                  somber: bool = False) -> Utterance | None:
    """A random resident's post of a random kind, a theory only while a case is open, somber when it is a death; None
    when nobody has quirks or the line is empty, of faith, grisly, or adds a case fact."""
    quirky = [v for v in town.villagers if v.quirks]
    if not quirky:
        return None
    v = rng.choice(quirky)
    kind = rng.choice([k for k in POSTS if case_text or k != "theory"])
    line = await writer.post(v, POSTS[kind], case_text, somber)
    firsts = {o.name.split()[0] for o in town.villagers}
    if not line or FAITH.search(line) or GORE.search(line) or invents_facts(line, case_text or "", firsts):
        return None
    return Utterance(ids.next("u"), v.id, v.name, v.home, line, None, "posted")
