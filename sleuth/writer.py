"""Haiku writes the words; it never decides what anyone does."""

import json
import re
from collections.abc import Sequence

from sleuth.actions import STYLES
from sleuth.decide import Decision
from sleuth.models import Villager
from sleuth.usage import charged_to

SAY_MAX_TOKENS = 80
TURN_AWAY_MAX_TOKENS = 60


STAGE_DIRECTION = re.compile(r"\*[^*]*\*")


def first_line(text: str) -> str:
    """The first line of a reply, without stage directions or surrounding quotes."""
    line = text.strip().split("\n")[0]
    line = re.sub(r"\s{2,}", " ", STAGE_DIRECTION.sub("", line))
    return line.strip().strip('"\u201c\u201d').strip()


def extract_json(text: str):
    """Parse the first JSON array or object in text, ignoring fences and prose."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                return decoder.raw_decode(text, i)[0]
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON in model output: {text[:200]!r}")


def _grudge(villager: Villager, aside: str = "") -> str:
    """The villager's grudge for a prompt, then aside, or nothing when they hold none."""
    return f"Your grudge: {villager.grudge}. {aside}" if villager.grudge else ""


class Writer:
    def __init__(self, client, model: str, usage=None):
        self.client = client
        self.model = model
        self.usage = usage

    async def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        """One Haiku call, returning the reply text."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Haiku 5.5 may think before answering; these short lines don't need it, and it costs output tokens.
            thinking={"type": "disabled"},
        )
        if self.usage:
            self.usage.record("haiku", response.usage.input_tokens, response.usage.output_tokens, charged_to.get())
        return "".join(b.text for b in response.content if b.type == "text").strip()

    async def say(
        self, villager: Villager, decision: Decision, source_text: str | None, audience: str,
    ) -> str:
        """The villager's words for this decision, in their voice and chosen style, keeping the source unnamed."""
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            + _grudge(villager, "Bring it up only when it fits. ")
            + "Reply with one or two short sentences, under 30 words, in your own voice, the way people gossip. "
            "You gossip with relish and curiosity, not malice, unless your manner says otherwise. "
            "Keep to what you heard, changed only as your manner says. "
            "If what you heard is about you, answer as yourself. "
            "No stage directions, no quotation marks around the reply, no preamble."
        )
        lines = [f"Action: {decision.action}.", f"Listening: {audience}."]
        if decision.style:
            lines.append(f"Manner: {STYLES[decision.style]}")
        if source_text:
            lines.append(f"What you heard: {source_text}")
            lines.append("Do not say or hint who started this story.")
        return first_line(await self.complete(system, "\n".join(lines), max_tokens=SAY_MAX_TOKENS))

    async def turn_away(self, villager: Villager) -> str:
        """The villager refusing to hear the newcomer any more, in one line."""
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            "You have grown wary of the newcomer who keeps whispering to you. Refuse to hear "
            "them out in one short sentence, about 15 words, in your own voice. "
            "Never mention suspicion or why. "
            "No stage directions, no quotation marks, no preamble."
        )
        return first_line(
            await self.complete(system, "The newcomer is whispering to you again.", max_tokens=TURN_AWAY_MAX_TOKENS)
        )

    async def answer(self, villager: Villager, topic: str, heard: Sequence[str], known: Sequence[str] = ()) -> str:
        """The villager telling the newcomer what folk have said about the topic, in one line.

        known describes the neighbours the question names, whom the villager knows even with no gossip about them.
        """
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            "You know everyone in the town by name and trade. "
            "The newcomer asks what folk have been saying about something. Answer in one short sentence, "
            "under 30 words, in your own voice, naming who told you and where. If you heard nothing about it, "
            "say so. Never mention suspicion. No stage directions, no quotation marks, no preamble."
        )
        said = "What you heard: " + " / ".join(heard) if heard else "What you heard: nothing about it."
        user = f"The newcomer asks about: {topic}\n{said}"
        if known:
            user += "\nNeighbours you know: " + "; ".join(known)
        return first_line(await self.complete(system, user, max_tokens=SAY_MAX_TOKENS))

    async def describe_group(
        self, villager: Villager, inspiration: list[str],
    ) -> tuple[str, str]:
        """A name and creed for a group the villager founds."""
        system = (
            f"You are {villager.name}, a {villager.occupation} ({villager.personality}). "
            "You are founding a town group. Reply with only a JSON object "
            '{"name": "...", "creed": "..."}: a short name and a one-sentence creed.'
        )
        user = "What inspired you:\n" + "\n".join(f"- {t}" for t in inspiration)
        parsed = extract_json(await self.complete(system, user))
        return parsed["name"], parsed["creed"]

