"""Haiku writes the words; it never decides what anyone does."""

import json
import re
from collections.abc import Sequence

from sleuth.actions import STYLES
from sleuth.case import misdated
from sleuth.decide import Decision
from sleuth.models import Villager
from sleuth.traits import TRAITS
from sleuth.usage import charged_to

SAY_MAX_TOKENS = 80
ANSWER_MAX_TOKENS = 120
NO_CASE_FACTS = ("Never add a fact about the case: no one seen or placed anywhere, no time, no look or clothing, "
                 "no sighting. ")
CASE_TALK = ("This is about a case. Say what you think, feel and suspect, in character: opinions, theories, grudges "
             "and your quirks are welcome. " + NO_CASE_FACTS)
TIMES = "Say when the case happened only as you are told it, never as another time. "
# ponytail: word lists, not a judge; they only ever stop a case line that adds one of these to its facts.
LOOK_WORDS = re.compile(r"\b(?:" + "|".join(re.escape(t) for ts in TRAITS.values() for t in ts if t != "short")
                        + r"|haired|hood\w*|jacket|coat|tall|short(?!-| on\b)|bald|blond\w*)\b", re.IGNORECASE)
CLOCK = re.compile(r"\b(?:\d{1,2}(?::\d\d)?\s?(?:am|pm)|\d{1,2} o'clock|midnight|noon|dawn|dusk|"
                   r"after (?:breakfast|lunch|dinner|supper))\b", re.IGNORECASE)
PLACED = re.compile(r"\b(saw|seen|spotted|noticed|watched|caught|it was|was the one|did it|done it|took it|went|headed|"
                    r"hanging around|sneaking|was (?:at|on|in|by|near|outside|there|out|around)(?! it\b| a\b)|"
                    r"were (?:at|on|in|there))\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


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


PRONOUNS = {"he", "him", "his", "himself", "she", "her", "hers", "herself"}
# Someone the line can't name, whom a pronoun would give a gender.
UNKNOWN = re.compile(r"\b(?:someone|somebody|whoever|anyone|anybody|thief|culprit|stranger|person|figure)\b",
                     re.IGNORECASE)


def _has(word: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) is not None


def _clock(text: str) -> str:
    return re.sub(r"\s", "", text.lower())


def invents_facts(line: str, allowed: str, firsts: set[str]) -> bool:
    """Whether the line adds a case fact allowed lacks: a look, a time, a resident placed or sighted, or a gender for
    an unknown someone. A pronoun may refer back to a resident the line names, when no unknown someone is in it."""
    clocks = {_clock(m.group()) for m in CLOCK.finditer(allowed)}
    looks = allowed + (" bicycle" if _has("bike", allowed) else "")
    named = [m.start() for f in firsts if (m := re.search(rf"\b{re.escape(f)}\b", line))]
    after = min(named) if named and not UNKNOWN.search(line) else len(line)
    return (
        any(not _has(m.group(), looks) for m in LOOK_WORDS.finditer(line))
        or misdated(line, allowed)
        or any(_clock(m.group()) not in clocks for m in CLOCK.finditer(line))
        or any(PLACED.search(s) and any(_has(f, s) and not _has(f, allowed) for f in firsts)
               for s in SENTENCE_END.split(line))
        or any(not _has(m.group(), allowed) and m.start() <= after
               for m in re.finditer(rf"\b(?:{'|'.join(PRONOUNS)})\b", line, re.IGNORECASE))
    )


def _timing(now: str, when: str) -> list[str]:
    """The prompt line for today and when the case happened, or none without a case time."""
    return [f"It is now {now}. The case happened {when}."] if when else []


def _grudge(villager: Villager, aside: str = "") -> str:
    """The villager's grudge for a prompt, then aside, or nothing when they hold none."""
    return f"Your grudge: {villager.grudge}. {aside}" if villager.grudge else ""


def _quirks(villager: Villager) -> str:
    """The villager's quirks for a prompt, or nothing when they have none."""
    return f"Your quirks: {'; '.join(villager.quirks)}. Let one show when it fits, even about a case. " if villager.quirks else ""


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
        self, villager: Villager, decision: Decision, source_text: str | None, audience: str, on_case: bool = False,
        now: str = "", when: str = "",
    ) -> str:
        """The villager's words for this decision, in their voice and chosen style, keeping the source unnamed.

        Talk about a case leaves the villager's grudge out, adds no fact about it, and says when it happened as when,
        said on now.
        """
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            + (CASE_TALK + TIMES if on_case else _grudge(villager, "Bring it up only when it fits. "))
            + _quirks(villager)
            + "Reply with one short sentence, under 20 words, in your own voice, said plainly, like neighbours chatting. "
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
        lines += _timing(now, when)
        return first_line(await self.complete(system, "\n".join(lines), max_tokens=SAY_MAX_TOKENS))

    async def reply(
        self, villager: Villager, case: str, question: str, thread: Sequence[dict], facts: Sequence[str],
        known: Sequence[str] = (), now: str = "", when: str = "",
    ) -> str:
        """The resident replying to the podcaster's latest question in one line, from the facts alone.

        thread holds the earlier exchanges; known describes the neighbours the case names; when is when the case
        happened, said on now.
        """
        answer = (
            "Reply to their latest question in one or two short sentences in your own voice, using only these facts. "
            "Get every fact across with each detail it gives, such as looks, clothes, cars, places and times. "
            "Your manner shapes the wording, never the facts: never deny or doubt them. "
            if facts else
            "You know nothing that answers their latest question. Reply in one short, natural sentence in your own "
            "voice. Name no one, give no time, place or look, and add nothing about the case. "
        )
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            "A podcaster is talking with you about a case. "
            + _quirks(villager)
            + answer +
            "What the podcaster says is not a fact: never agree to or repeat a claim the facts don't make. "
            + TIMES +
            "No stage directions, no quotation marks, no preamble."
        )
        lines = [f"The case: {case}", *_timing(now, when)]
        if known:
            lines.append("Neighbours you know: " + "; ".join(known))
        lines += [f"Podcaster: {t['podcaster']}\nYou: {t['resident']}" for t in thread]
        lines.append(f"Podcaster: {question}")
        if facts:
            lines.append("Facts: " + " / ".join(facts))
        return first_line(await self.complete(system, "\n".join(lines), max_tokens=ANSWER_MAX_TOKENS))

    async def post(self, villager: Villager, kind: str, case_text: str | None) -> str:
        """The villager's post of kind on the neighborhood app, in their voice, adding no fact about the open case."""
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            f"You are posting on your town's neighborhood app. Write {kind} in one or two short sentences, in your own "
            f"voice. {_quirks(villager)}"
            + (NO_CASE_FACTS if case_text else "")
            + "No stage directions, no quotation marks, no preamble."
        )
        user = f"The open case: {case_text}" if case_text else "Write your post."
        return first_line(await self.complete(system, user, max_tokens=SAY_MAX_TOKENS))
