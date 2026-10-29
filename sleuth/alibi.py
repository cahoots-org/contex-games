"""What residents say about where they, and their housemates, were during a crime."""

from typesafe_sdk import Choice

from sleuth.case import WHEN
from sleuth.cases import CaseFile
from sleuth.decide import warmth_words
from sleuth.models import Villager
from sleuth.town import at

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
    """Whether speaker can vouch for about: housemates, when the crime, or any part of a death's window, is at night."""
    return "night" in (file.crime.window or [file.crime.phase]) and speaker.id != about.id and speaker.household == about.household


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


def accomplice_word(file: CaseFile, speaker: Villager, about: Villager) -> tuple[str, bool] | None:
    """The accomplice's false word that the culprit was with them, its time as WHEN; None from anyone else, or about
    anyone else."""
    if speaker.id != file.accomplice or about.id != file.crime.culprit:
        return None
    place = (file.whereabouts.get(speaker.id) or [speaker.home])[0]
    return f"{about.name} was with me {at(place)} {WHEN}.", False
