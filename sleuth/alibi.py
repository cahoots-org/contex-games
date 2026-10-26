"""What residents say about where they, and their housemates, were during a crime."""

from typesafe_sdk import Choice

from sleuth.cases import CaseFile
from sleuth.decide import warmth_words
from sleuth.models import Villager

ANSWERS = {"honest": "Say honestly you were asleep and can't vouch for them.",
           "cover": "Say they were home with you all night."}


def claim(file: CaseFile, vid: str, routine) -> tuple[list[str], bool]:
    """The places the resident says they were during the crime, and whether that is the truth."""
    if vid != file.crime.culprit:
        return file.whereabouts.get(vid, []), True
    return file.alibi or [routine.place(vid, file.crime.phase)], False


async def household_word(jev, file: CaseFile, speaker: Villager, about: Villager) -> tuple[str, bool] | None:
    """A housemate's word on where about was on the night of the crime, and whether it is sound; asked once per case."""
    crime = file.crime
    if crime.phase != "night" or speaker.id == about.id or speaker.household != about.household:
        return None
    key = f"{speaker.id}:{about.id}"
    if key in file.words:
        return tuple(file.words[key])
    state = {"speaker": {"name": speaker.name, "personality": speaker.personality},
             "housemate": {"name": about.name, "tie": speaker.relationships.get(about.id, "housemate"),
                           "feeling": warmth_words(speaker.warmth.get(about.id, 0.0))},
             "crime": crime.text}
    question = Choice(instructions=f"Asked where {about.name} was that night, how does {speaker.name} answer?",
                      criteria=ANSWERS)
    resp = await jev.system_one(state=state, questions={"answer": question})
    if resp.choices["answer"].choice == "cover":
        word = f"{about.name} was home with me all night.", about.id != crime.culprit
    else:
        word = f"I was asleep. I can't say where {about.name} was.", True
    file.words[key] = list(word)
    return word
