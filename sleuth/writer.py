"""Haiku writes the words; it never decides what anyone does."""

import json
import re
from collections.abc import Sequence

from sleuth.actions import STYLES
from sleuth.decide import Decision
from sleuth.models import Villager
from sleuth.usage import charged_to

SAY_MAX_TOKENS = 80
ANSWER_MAX_TOKENS = 120


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

    async def answer(self, villager: Villager, case: str, facts: Sequence[str], known: Sequence[str] = ()) -> str:
        """The resident answering the podcaster about the case in one line, from the facts alone.

        known describes the neighbours the case names, whom the resident knows by name and trade.
        """
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            "A podcaster is asking about a case. "
            "Answer the podcaster in one or two short sentences in your own voice, using only these facts. "
            "Get every fact across with each detail it gives, such as looks, clothes, cars, places and times. "
            "Your manner shapes the wording, never the facts: never deny or doubt them. "
            "If there are none, say you know nothing about it. "
            "No stage directions, no quotation marks, no preamble."
        )
        said = "Facts: " + " / ".join(facts) if facts else "Facts: none."
        user = f"The case: {case}\n{said}"
        if known:
            user += "\nNeighbours you know: " + "; ".join(known)
        return first_line(await self.complete(system, user, max_tokens=ANSWER_MAX_TOKENS))
