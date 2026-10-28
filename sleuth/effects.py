"""Turn a villager's decision into town changes and speech."""

import random
import re
from typing import Protocol

from sleuth.actions import (
    ALIBI, BLAME, CONFRONT, DENY, IGNORE, MOVE, RETELL, SPEAK, WARN,
)
from sleuth.decide import Decision
from sleuth.facts import Facts
from sleuth.faith import FAITH, GORE
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.town import Town
from sleuth.case import retime
from sleuth.writer import Writer, invents_facts, invents_people

DIRECT = (RETELL, DENY, CONFRONT)
# ponytail: a phrase list, not a judge; it only ever drops a retold line that claims to have seen it.
FIRST_HAND = re.compile(r"\bI (?:saw|spotted|watched|noticed|caught)\b", re.I)
ROOM = "room"
ONE = "one"


class Hub(Protocol):
    async def deliver(self, utterance: Utterance, listener_ids: list[str], addressed: bool = False) -> None: ...

    def cover_story(self, vid: str, action: str) -> str | None: ...

    def mark_cover(self, vid: str, uid: str) -> None: ...

    def warn(self, vid: str, target: str) -> str | None: ...

    def on_case(self, uid: str) -> tuple[str, str] | None: ...

    def somber(self, uid: str | None = None, culprit: str | None = None) -> bool: ...


async def act(
    decision: Decision,
    villager: Villager,
    *,
    town: Town,
    writer: Writer,
    hub: Hub,
    lineage: Lineage,
    ids: Ids,
    facts: Facts,
    share_chance: float = 0.0,
    mood: str = "",
) -> None:
    """Apply the decision to the town and deliver any speech it produces.

    A villager who moves shares the news with someone where they arrive with share_chance. Talk passed on may drift
    and embellish, but a retold case line that claims to have seen it is dropped. A cover story or warning that adds
    to its fact or gives another time is told as its plain fact. A line of faith or anything grisly is dropped, or
    told plainly. A case line heard days ago is retold with the case's time said today. Talk about a death is sober.
    Speech carries the mood of the villager's street.
    """
    action = decision.action
    vid = villager.id
    place = town.place_of(vid)
    source_id = decision.source.data["id"] if decision.source else None
    source_text = decision.source.data.get("text") if decision.source else None
    heard_from = facts.get(source_id) if source_id else None
    timing = hub.on_case(source_id) if source_id else None
    on_case = timing is not None
    grave = on_case and hub.somber(source_id)
    if timing and source_text:
        source_text = retime(source_text, timing[1])

    async def say(
        text: str, listeners: list[str], audience: str, verb: str = "said", addressed: bool = False,
        root: bool = False, cover: bool = False,
    ) -> str:
        """Record and deliver an utterance descended from the decision's source, or starting a new line if root."""
        parent = None if root else source_id
        uid = ids.next("u")
        lineage.record(uid, parent)
        depth = heard_from.depth + 1 if heard_from and parent else 0
        utterance = Utterance(
            uid, vid, villager.name, place, text, parent, verb,
            depth=depth, audience=audience, action=action, style=decision.style,
        )
        facts.record(utterance)
        if cover:
            hub.mark_cover(vid, uid)
        await hub.deliver(utterance, [i for i in listeners if i != vid], addressed=addressed)
        return uid

    async def words(facts_text: str | None, audience: str, case: bool, plain: str | None = None,
                    somber: bool = False, retold: bool = False) -> str | None:
        """The writer's line; plain or nothing when it is of faith or grisly or names someone or somewhere the town
        lacks, when retold on a case claims to have seen it or names its teller, or when otherwise on a case adds what
        facts_text and the people at hand don't."""
        text = await writer.say(villager, decision, facts_text, audience, case, *(timing or ("", "")), mood=mood,
                                somber=somber, retold=case and retold)
        names = [v.name for v in (*town.villagers, *town.departed)]
        if FAITH.search(text) or GORE.search(text) or invents_people(text, names):
            return plain
        if case and retold:
            # A victim retelling their own case's news would speak of themselves by name, as someone else.
            first = re.escape(villager.name.split()[0])
            return plain if FIRST_HAND.search(text) or re.search(rf"\b{first}\b", text) else text
        allowed = " ".join([villager.name, audience, facts_text or "", *(timing or ())])
        if case and invents_facts(text, allowed, {v.name.split()[0] for v in town.villagers}):
            return plain
        return text

    def others() -> list[str]:
        return [v.id for v in town.present(place, exclude=vid)]

    if action == IGNORE:
        return
    if action == MOVE:
        town.move(vid, decision.target)
        arrived = [v.id for v in town.present(decision.target, exclude=vid)]
        if decision.source and arrived and random.random() < share_chance:
            shared = Decision(RETELL, decision.source, random.choice(arrived), decision.style)
            await act(
                shared, villager, town=town, writer=writer, hub=hub, lineage=lineage, ids=ids, facts=facts, mood=mood,
            )
    elif action in DIRECT:
        if decision.target in others():
            if text := await words(source_text, town.get(decision.target).name, on_case, somber=grave, retold=True):
                await say(text, [decision.target], ONE)
    elif action in (ALIBI, BLAME):
        if decision.target in others() and (fact := hub.cover_story(vid, action)) is not None:
            text = await words(fact, town.get(decision.target).name, True, fact, hub.somber(culprit=vid))
            await say(text, [decision.target], ONE, root=True, cover=True)
    elif action == WARN:
        if decision.target in others() and (fact := hub.warn(vid, decision.target)) is not None:
            text = await words(fact, town.get(decision.target).name, True, fact, hub.somber(culprit=vid))
            await say(text, [decision.target], ONE, root=True)
    elif action == SPEAK:
        if text := await words(source_text, place, on_case, somber=grave, retold=True):
            await say(text, others(), ROOM)
