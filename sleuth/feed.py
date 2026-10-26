"""The feed: typed events about the game, sent to every sink and kept for replay."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass

from sleuth.lineage import Lineage
from sleuth.models import Utterance
from sleuth.town import STREETS, Town, at, place_name

REPLAY_EVENTS = 500
TIME_LINES = {
    "morning": "Day {day}: morning in town.",
    "afternoon": "It's the afternoon.",
    "evening": "Evening: people head home from work.",
    "night": "Night falls, and the streets go quiet.",
}
RESTING = "The town is resting for today. Come back after midnight UTC."
WAKING = "The town wakes up for a new day."


@dataclass(frozen=True)
class Event:
    id: int
    at: float
    kind: str
    # What the terminal prints; empty when it prints nothing.
    line: str
    data: dict
    # Who sees the event; None means everyone in the village.
    player: str | None = None

    def to_json(self, viewer: str | None = None) -> dict:
        """The event for viewer's page: only the author of an action sees it as theirs, with its verdict."""
        data = dict(self.data)
        if "by" in data:
            data["mine"] = data.pop("by") == viewer
            if not data["mine"]:
                data.pop("verdict", None)
        return {"id": self.id, "at": self.at, "kind": self.kind, **data}


Sink = Callable[[Event], None]


def terminal(out: Callable[[str], None]) -> Sink:
    def sink(event: Event) -> None:
        if event.line:
            out(event.line)

    return sink


class Feed:
    def __init__(self, lineage: Lineage, town: Town, out: Callable[[str], None] | None = print):
        self.lineage = lineage
        self.town = town
        self.sinks: list[Sink] = [terminal(out)] if out else []
        self.recent: deque[Event] = deque(maxlen=REPLAY_EVENTS)
        self._last_id = 0
        # Players in the practice town, who see only their own events and the town's rest.
        self.practising: set[str] = set()

    def to_state(self) -> dict:
        """Recent events and the last event id as plain JSON."""
        return {"recent": [asdict(e) for e in self.recent], "last_id": self._last_id}

    def restore(self, state: dict) -> None:
        """Replace the events with a saved state."""
        self.recent.clear()
        self.recent.extend(Event(**e) for e in state["recent"])
        self._last_id = state["last_id"]

    def ensure_past(self, n: int) -> None:
        """Make the next event id come after n."""
        self._last_id = max(self._last_id, n)

    def emit(self, kind: str, line: str = "", /, player: str | None = None, **data) -> Event:
        """Send an event to every sink."""
        self._last_id += 1
        event = Event(self._last_id, time.time(), kind, line, data, player)
        self.recent.append(event)
        for sink in self.sinks:
            sink(event)
        return event

    def say(self, line: str, player: str | None = None) -> Event:
        """Send a plain line of text."""
        return self.emit("system", line, player=player, text=line)

    def on_steps(self, steps: list[dict], *, player: str) -> None:
        """The checklist of a new player's practice case, ticked from what they have done."""
        self.emit("steps", player=player, steps=steps)

    def sees(self, player: str, event: Event) -> bool:
        """Whether the event is meant for that player."""
        if event.player is not None:
            return event.player == player
        return player not in self.practising or event.kind == "rest"

    def forget(self, player: str) -> None:
        """Drop the events meant only for that player."""
        kept = [e for e in self.recent if e.player != player]
        self.recent.clear()
        self.recent.extend(kept)

    def replay(self, player: str) -> list[Event]:
        """The recent events that player sees."""
        return [e for e in self.recent if self.sees(player, e)]

    def view(self, player: str, sink: Sink) -> Sink:
        """A sink passing on to sink only the events that player sees."""
        def seen(event: Event) -> None:
            if self.sees(player, event):
                sink(event)

        return seen

    def on_interview(self, villager_id: str, name: str, question: str, line: str, records: list[dict], *,
                     case_id: str, player: str) -> None:
        """The podcaster's question to a resident, the reply, and the records it added to their notebook."""
        self.emit("interview", f'{name}: "{line}"', player=player, villager_id=villager_id, name=name,
                  question=question, line=line, records=records, case_id=case_id)

    def on_case(self, case: dict, player: str | None = None) -> None:
        """A case opened or changed in the neighborhood app."""
        self.emit("case", case["text"], player=player, case=case)

    def on_post(self, utterance: Utterance, case_id: str, player: str | None = None) -> None:
        """The neighborhood app's news of a case, or room talk rooted in it."""
        u = utterance
        self.emit("post", f'{u.speaker_name} posted: "{u.text}"', player=player, case_id=case_id, speaker=u.speaker_name,
                  text=u.text, app=u.speaker == "app")

    def on_pulled(self, place: str, records: list[dict], *, case_id: str, player: str) -> None:
        """The footage and logs the podcaster pulled at place into their notebook."""
        line = f"You pulled the records {at(place)}."
        self.emit("pulled", line, player=player, place=place, records=records, text=line, case_id=case_id)

    def on_searched(self, place: str, records: list[dict], *, case_id: str, player: str) -> None:
        """What the podcaster found searching the crime place, added to their notebook."""
        line = f"You searched {place_name(place) if place in STREETS else f'the {place}'}."
        self.emit("searched", line, player=player, place=place, records=records, text=line, case_id=case_id)

    def on_episode(self, case_id: str, name: str, held: bool, *, by: str, cited: int, verdict: str,
                   player: str | None = None) -> None:
        """A podcaster's episode named a resident citing some records, and whether it held up, which its author sees
        as verdict."""
        line = f"A podcaster's episode names {name}" + (", and it holds up. Case closed." if held else ".")
        self.emit("episode", line, player=player, case_id=case_id, name=name, held=held, text=line, by=by, cited=cited,
                  verdict=verdict)

    def on_case_closed(self, case_id: str, line: str, player: str | None = None) -> None:
        self.emit("case_closed", line, player=player, case_id=case_id, text=line)

    def on_time(self, day: int, phase: str) -> None:
        line = TIME_LINES[phase].format(day=day)
        self.emit("time", line, text=line, day=day, phase=phase)

    def on_rest(self, resting: bool) -> None:
        """The village has started resting for the day, or woken."""
        line = RESTING if resting else WAKING
        self.emit("rest", line, text=line, resting=resting)

    def on_place(self, place: str, player: str | None = None) -> None:
        """The player is now at place; the terminal prints nothing."""
        self.emit("place", player=player, place=place)
