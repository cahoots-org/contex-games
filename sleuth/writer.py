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
CASE_TALK = ("This is about a case. Talk only about what you know of this case and how you feel about it. "
             "Leave your other worries out. Add no person, animal or detail that what you heard doesn't give, and "
             "never guess whether anyone was a man or a woman. ")
TIMES = "Say when the case happened only as you are told it, never as another time. "
# ponytail: a word list, not a judge; it only ever stops a case line that adds one of these to its facts.
INVENTED = re.compile(
    r"\b(he|him|his|himself|she|her|hers|herself|man|men|woman|women|guy|guys|lady|ladies|gal|bloke|fella|fellow|"
    r"boy|girl|gentleman|mr|mrs|ms|dogs?|pup\w*|cats?|kitten\w*|birds?|parrots?|horses?|rabbits?|hamsters?|"
    r"hood\w*|hats?|caps?|beard\w*|glasses|tattoo\w*|coat|jacket|raincoat|puffer|flannel|denim|pickup|truck|"
    r"sedan|hatchback|minivan|van|car|bicycle|bike|tall|bald|blond\w*|haired)\b", re.IGNORECASE)


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


def strangers(line: str, allowed: str, firsts: set[str]) -> bool:
    """Whether the line names someone by first name whom allowed does not."""
    return any(re.search(rf"\b{re.escape(f)}\b", line) and not re.search(rf"\b{re.escape(f)}\b", allowed)
               for f in firsts)


def invents(line: str, allowed: str, firsts: set[str]) -> bool:
    """Whether the line adds to allowed a resident, a gender, an animal or a look."""
    known = set(re.findall(r"\w+", allowed.lower()))
    return strangers(line, allowed, firsts) or any(w.lower() not in known for w in INVENTED.findall(line))


def _timing(now: str, when: str) -> list[str]:
    """The prompt line for today and when the case happened, or none without a case time."""
    return [f"It is now {now}. The case happened {when}."] if when else []


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
        self, villager: Villager, decision: Decision, source_text: str | None, audience: str, on_case: bool = False,
        now: str = "", when: str = "",
    ) -> str:
        """The villager's words for this decision, in their voice and chosen style, keeping the source unnamed.

        Talk about a case keeps to the case, without the villager's grudge or other worries, and says when it
        happened as when, said on now.
        """
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            + (CASE_TALK + TIMES if on_case else _grudge(villager, "Bring it up only when it fits. "))
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
        system = (
            f"You are {villager.name}, a {villager.occupation} in a small town. "
            f"Your personality: {villager.personality}. "
            "A podcaster is talking with you about a case. "
            "Reply to their latest question in one or two short sentences in your own voice, using only these facts. "
            "Get every fact across with each detail it gives, such as looks, clothes, cars, places and times. "
            "Your manner shapes the wording, never the facts: never deny or doubt them. "
            "What the podcaster says is not a fact: never agree to or repeat a claim the facts don't make. "
            + TIMES +
            "No stage directions, no quotation marks, no preamble."
        )
        lines = [f"The case: {case}", *_timing(now, when)]
        if known:
            lines.append("Neighbours you know: " + "; ".join(known))
        lines += [f"Podcaster: {t['podcaster']}\nYou: {t['resident']}" for t in thread]
        lines += [f"Podcaster: {question}", "Facts: " + " / ".join(facts)]
        return first_line(await self.complete(system, "\n".join(lines), max_tokens=ANSWER_MAX_TOKENS))
