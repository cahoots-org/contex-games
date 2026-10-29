"""Plain data types for villagers and utterances."""

from dataclasses import dataclass, field


@dataclass
class Villager:
    id: str
    name: str
    occupation: str
    personality: str
    grudge: str
    needs: list[str]
    relationships: dict[str, str]
    traits: dict[str, str] = field(default_factory=dict)
    home: str = ""
    household: str = ""
    # How warmly they feel toward each tie, keyed like relationships, in [-1, 1].
    warmth: dict[str, float] = field(default_factory=dict)
    wardrobe: list[str] = field(default_factory=list)
    quirks: list[str] = field(default_factory=list)


@dataclass
class Utterance:
    id: str
    speaker: str
    speaker_name: str
    place: str
    text: str
    parent: str | None
    verb: str = "said"
    depth: int = 0
    audience: str = "one"
    action: str | None = None
    style: str | None = None

    def to_data(self) -> dict:
        """Payload for Contex, which embeds every field, so it holds only what the game reads back.

        The place stays out: it would pull every line said there toward news about that place.
        """
        return {"id": self.id, "text": f"{self.speaker_name} {self.verb}: {self.text}"}
