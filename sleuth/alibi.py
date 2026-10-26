"""What residents say about where they, and their housemates, were during a crime."""

from typesafe_sdk import Choice

from sleuth.cases import CaseFile
from sleuth.decide import warmth_words
from sleuth.models import Villager

ANSWERS = {"honest": "Say honestly you were asleep and can't vouch for them.",
           "cover": "Say they were home with you all night."}


def claim(file: CaseFile, vid: str, routine) -> tuple[list[str], bool]:
    """The places the resident says they were during the crime, and whether that is the truth: a culprit who is a
    regular at the scene says so truthfully."""
    if vid != file.crime.culprit:
        return file.whereabouts.get(vid, []), True
    places = file.alibi or [routine.place(vid, file.crime.phase)]
    return places, places == [file.crime.place]


def _vouches(file: CaseFile, speaker: Villager, about: Villager) -> bool:
    """Whether speaker can vouch for about: housemates, on the night of a crime."""
    return file.crime.phase == "night" and speaker.id != about.id and speaker.household == about.household


def household_question(file: CaseFile, speaker: Villager, about: Villager) -> Choice | None:
    """Jev's question for speaker's word on where about was that night; None when there is none or it was answered."""
    if not _vouches(file, speaker, about) or f"{speaker.id}:{about.id}" in file.words:
        return None
    tie = speaker.relationships.get(about.id, "housemate")
    feeling = warmth_words(speaker.warmth.get(about.id, 0.0))
    return Choice(instructions=f"Asked where {about.name}, their {tie} whom they feel {feeling} toward, was that "
                               f"night, how does {speaker.name} answer?", criteria=ANSWERS)


def household_word(file: CaseFile, speaker: Villager, about: Villager, answer: str | None = None) -> tuple[str, bool] | None:
    """A housemate's word on where about was on the night of the crime, and whether it is sound.

    It comes from Jev's answer to household_question and is kept for the case; None when there is none.
    """
    if not _vouches(file, speaker, about):
        return None
    key = f"{speaker.id}:{about.id}"
    if key in file.words:
        return tuple(file.words[key])
    if answer is None:
        return None
    if answer == "cover":
        word = f"{about.name} was home with me all night.", about.id != file.crime.culprit
    else:
        word = f"I was asleep. I can't say where {about.name} was.", True
    file.words[key] = list(word)
    return word
