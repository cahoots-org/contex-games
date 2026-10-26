"""Routing a podcaster's question to a resident to the kind of answer the game can give from its records."""

from dataclasses import dataclass

from typesafe_sdk import Choice

from sleuth.alibi import household_question
from sleuth.cases import CaseFile
from sleuth.decide import MAX_OPTIONS
from sleuth.game import PHASES
from sleuth.models import Villager
from sleuth.town import Town

KINDS = {
    "where_were_you": "where this resident was at some part of the day",
    "where_was": "where someone else was",
    "what_did_you_see": "what this resident saw or found",
    "who_told_you": "who this resident heard something from, or what they heard",
    "who_had_reason": "who would have a reason to do it, like a grudge or a feud with the victim",
    "what_do_you_think_of": "what this resident thinks of someone",
    "none": "none of these",
}
# How many earlier exchanges Jev and Haiku see.
CONTEXT = 4


@dataclass(frozen=True)
class Route:
    kind: str
    who: str | None
    when: str
    # Jev's answer to each housemate's household question, by housemate id.
    words: dict[str, str]


def exchanges(thread: list[dict]) -> list[dict]:
    """The last few exchanges of a thread, as the podcaster's question and the resident's reply."""
    return [{"podcaster": t["question"], "resident": t["line"]} for t in thread[-CONTEXT:]]


async def route(jev, file: CaseFile, villager: Villager, town: Town, question: str, thread: list[dict]) -> Route:
    """One Jev call: what the question asks, about whom and which part of the day, and the housemates' words."""
    crime = file.crime
    others = [v for v in town.villagers if v.id != villager.id][:MAX_OPTIONS]
    state = {"resident": {"name": villager.name, "occupation": villager.occupation,
                          "personality": villager.personality},
             "case": crime.text, "case_part_of_day": crime.phase,
             "conversation": exchanges(thread), "podcaster_asks": question}
    questions = {"kind": Choice(instructions="What is the podcaster asking this resident about? Read the question "
                                             "with the conversation so far.", criteria=KINDS),
                 "when": Choice(instructions="Which part of the day is the question about? If it names none, the "
                                             "case's.", criteria={p: None for p in PHASES})}
    if others:
        questions["who"] = Choice(instructions="Whom else is the question about? Pick who is named, or meant from the "
                                               "conversation.",
                                  criteria={v.id: f"{v.name}, {v.occupation}" for v in others})
    for mate in town.villagers:
        if q := household_question(file, villager, mate):
            questions[f"word:{mate.id}"] = q
    resp = await jev.system_one(state=state, questions=questions)
    pick = {k: c.choice for k, c in resp.choices.items()}
    kind = pick.get("kind") if pick.get("kind") in KINDS else "none"
    who = pick.get("who") if pick.get("who") in town and pick.get("who") != villager.id else None
    when = pick.get("when") if pick.get("when") in PHASES else crime.phase
    words = {k.removeprefix("word:"): v for k, v in pick.items() if k.startswith("word:")}
    return Route(kind, who, when, words)
