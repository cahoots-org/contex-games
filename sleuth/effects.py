"""Turn a villager's decision into town changes and speech."""

import random
from collections.abc import Sequence
from typing import Protocol

from sleuth.actions import (
    ALIBI, BLAME, CONFRONT, DENY, FOUND_GROUP, IGNORE, JOIN_GROUP, LEAVE_GROUP, MOVE, PREACH, RETELL, SPEAK,
)
from sleuth.decide import Decision
from sleuth.facts import Facts
from sleuth.lineage import Ids, Lineage
from sleuth.models import Group, Utterance, Villager
from sleuth.town import Town
from sleuth.writer import Writer

DIRECT = (RETELL, DENY, CONFRONT)
ROOM = "room"
ONE = "one"


class Hub(Protocol):
    async def deliver(self, utterance: Utterance, listener_ids: list[str], addressed: bool = False) -> None: ...

    async def publish_group(self, group: Group) -> None: ...

    def cover_story(self, vid: str, action: str) -> str | None: ...

    def mark_cover(self, vid: str, uid: str) -> None: ...


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
    inspiration: Sequence[str] = (),
    share_chance: float = 0.0,
) -> None:
    """Apply the decision to the town and deliver any speech it produces.

    A villager who moves shares the news with someone where they arrive with share_chance.
    """
    action = decision.action
    vid = villager.id
    place = town.place_of(vid)
    source_id = decision.source.data["id"] if decision.source else None
    source_text = decision.source.data.get("text") if decision.source else None
    heard_from = facts.get(source_id) if source_id else None

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
                shared, villager, town=town, writer=writer, hub=hub, lineage=lineage, ids=ids, facts=facts,
                inspiration=inspiration,
            )
    elif action in DIRECT:
        if decision.target in others():
            text = await writer.say(villager, decision, source_text, town.get(decision.target).name)
            await say(text, [decision.target], ONE)
    elif action in (ALIBI, BLAME):
        if decision.target in others() and (fact := hub.cover_story(vid, action)) is not None:
            text = await writer.say(villager, decision, fact, town.get(decision.target).name)
            await say(text, [decision.target], ONE, root=True, cover=True)
    elif action == SPEAK:
        text = await writer.say(villager, decision, source_text, place)
        await say(text, others(), ROOM)
    elif action == FOUND_GROUP:
        name, creed = await writer.describe_group(villager, list(inspiration))
        group = town.found_group(vid, name, creed)
        await hub.publish_group(group)
        await say(f"{villager.name} founded {name}: {creed}", others(), ROOM, "announced")
    elif action == JOIN_GROUP:
        group = next(g for g in town.visible_groups(vid) if g.id == decision.target)
        town.join(vid, group.id)
        await say(f"{villager.name} joined {group.name}", others(), ROOM, "announced")
    elif action == LEAVE_GROUP:
        town.leave(vid, decision.target)
    elif action == PREACH:
        group = next(g for g in town.member_groups(vid) if g.id == decision.target)
        text = await writer.say(villager, decision, source_text, group.name)
        await say(text, list(group.members), ROOM, "preached")
