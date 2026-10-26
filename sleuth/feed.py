"""The feed: typed events about the game, sent to every sink and kept for replay."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass

from sleuth.game import Summary
from sleuth.lineage import Lineage
from sleuth.models import Utterance
from sleuth.suspicion import HEAT_LINES
from sleuth.town import NEWCOMER, Town

REPLAY_EVENTS = 500
LISTENING = ("checking", "busy", "heard")
RESOLVED = ("kept", "took_the_bait", "warned", "moved_on")
LEANING = ("brushed_off", "near_miss")
TIME_LINES = {
    "morning": "Day {day} dawns over the village.",
    "afternoon": "The sun is high over the village.",
    "evening": "Evening falls, and lamps are lit.",
    "night": "Night settles over the village.",
}
GAME_OVER = {"lost": "Game over: you were run out of town."}
RESTING = "The village is resting for today. Come back after midnight UTC."
WAKING = "The village wakes for a new day."


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

    def to_json(self) -> dict:
        return {"id": self.id, "at": self.at, "kind": self.kind, **self.data}


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
        # Each closed player's id, with the id of the last event they see.
        self._closed: dict[str, int] = {}
        self._listening: dict[str, tuple[str, str]] = {}
        # ponytail: grows by one id per whisper the player sends; a session sends far fewer than would matter.
        self._resolved: set[str] = set()
        self._answered: set[str] = set()

    def to_state(self) -> dict:
        """Recent events, the last event id, closed players and whisper states as plain JSON."""
        return {"recent": [asdict(e) for e in self.recent], "last_id": self._last_id, "closed": dict(self._closed),
                "listening": {wid: list(held) for wid, held in self._listening.items()},
                "resolved": sorted(self._resolved), "answered": sorted(self._answered)}

    def restore(self, state: dict) -> None:
        """Replace the events and whisper states with a saved state."""
        self.recent.clear()
        self.recent.extend(Event(**e) for e in state["recent"])
        self._last_id = state["last_id"]
        self._closed = dict(state["closed"])
        self._listening = {wid: tuple(held) for wid, held in state["listening"].items()}
        self._resolved, self._answered = set(state["resolved"]), set(state["answered"])

    def ensure_past(self, n: int) -> None:
        """Make the next event id come after n."""
        self._last_id = max(self._last_id, n)

    def emit(self, kind: str, line: str = "", /, player: str | None = None, **data) -> Event | None:
        """Send an event to every sink; drop one addressed to a closed player and return None."""
        if player in self._closed:
            return None
        self._last_id += 1
        event = Event(self._last_id, time.time(), kind, line, data, player)
        self.recent.append(event)
        for sink in self.sinks:
            sink(event)
        return event

    def say(self, line: str, player: str | None = None) -> Event | None:
        """Send a plain line of text."""
        return self.emit("system", line, player=player, text=line)

    def close(self, player: str) -> None:
        """Send that player nothing newer than what has been sent so far."""
        self._closed[player] = self.recent[-1].id if self.recent else 0

    def sees(self, player: str, event: Event) -> bool:
        """Whether the event is meant for that player and came before their feed closed."""
        closed_at = self._closed.get(player)
        if closed_at is not None and event.id > closed_at:
            return False
        return event.player is None or event.player == player

    def replay(self, player: str) -> list[Event]:
        """The recent events that player sees."""
        return [e for e in self.recent if self.sees(player, e)]

    def view(self, player: str, sink: Sink) -> Sink:
        """A sink passing on to sink only the events that player sees."""
        def seen(event: Event) -> None:
            if self.sees(player, event):
                sink(event)

        return seen

    def on_heat(self, label: str, player: str | None = None) -> None:
        self.emit("heat", HEAT_LINES[label], player=player, label=label)

    def on_game_over(self, summary: Summary, player: str | None = None) -> None:
        lines = [GAME_OVER[summary.outcome], *summary.reasons]
        self.emit("gameover", "\n".join(lines), player=player, outcome=summary.outcome, reasons=list(summary.reasons))

    def on_whisper_status(self, whisper_id: str, villager_id: str, name: str, state: str, **extra) -> None:
        """Report where a whisper stands: checking, busy (with until), heard, brushed_off or near_miss (then with hint),
        not_carried, or what the villager did with it: kept, took_the_bait (with told), warned, answered
        (not final), or moved_on once a conversation ends.

        A whisper already resolved only takes another outcome: a late heard, brush-off, near miss or not-carried is
        dropped. An answered whisper drops a late listening state, brush-off or near miss.
        The terminal prints only a brush-off or near miss once its hint is settled. A miss also carries continues,
        whether the villager's next whisper continues the exchange.
        """
        if whisper_id in self._resolved and state not in RESOLVED:
            return
        if whisper_id in self._answered and (state in LISTENING or state in LEANING):
            return
        if state == "answered":
            self._answered.add(whisper_id)
        if state in LISTENING:
            self._listening[whisper_id] = (villager_id, name)
        else:
            self._listening.pop(whisper_id, None)
        if state in RESOLVED:
            self._resolved.add(whisper_id)
        text = ""
        if state in LEANING and "hint" in extra:
            hint = extra["hint"]
            if state == "near_miss":
                text = f'{name} leans in: "{hint}"' if hint else f"{name} leans in."
            else:
                text = f'{name} brushes you off: "{hint}"' if hint else f"{name} shrugs it off."
        self.emit("whisper_status", text, player=self.lineage.player_of(whisper_id), whisper_id=whisper_id,
                  villager_id=villager_id, name=name, state=state, **extra)

    def listening(self, villager_id: str) -> list[tuple[str, str]]:
        """The (whisper id, name) of each whisper the villager is still hearing."""
        return [(wid, name) for wid, (vid, name) in self._listening.items() if vid == villager_id]

    def on_refusal(self, villager_id: str, name: str, line: str | None = None, player: str | None = None) -> None:
        text = f'{name} turns away from you: "{line}"' if line else f"{name} turns away from you."
        self.emit("refusal", text, player=player, villager_id=villager_id, name=name, line=line)

    def on_storm_off(
        self, villager_id: str, name: str, line: str | None = None, *, player: str, verb: str = "storms off",
    ) -> None:
        """The villager broke off with the player, as verb says, with their parting words if any."""
        text = f'{name} {verb}: "{line}"' if line else f"{name} {verb}."
        self.emit("stormed_off", text, player=player, villager_id=villager_id, name=name, line=line, verb=verb)

    def on_denied(self, name: str, line: str | None, player: str) -> None:
        """The rumor's subject denied it aloud, in their own words."""
        self.emit("denied", f'{name}: "{line}"', player=player, name=name, line=line)

    def on_answer(self, villager_id: str, name: str, topic: str, line: str, *, player: str) -> None:
        """The villager's answer to the player asking what folk say about the topic."""
        self.emit("asked", f'{name}, asked about {topic}: "{line}"', player=player,
                  villager_id=villager_id, name=name, topic=topic, line=line)

    def on_warning(self, speaker_id: str, speaker_name: str, target_id: str, target_name: str, player: str) -> None:
        """A villager warned another about player."""
        self.emit(
            "warning", f"{speaker_name} warned {target_name} about you.", player=player,
            speaker_id=speaker_id, speaker=speaker_name, target_id=target_id, target=target_name,
        )

    def on_reply(self, conversation: str, utterance: Utterance) -> None:
        """A villager answered the newcomer in the conversation started by that whisper."""
        u = utterance
        self.emit("reply", f'{u.speaker_name} answers you: "{u.text}"', player=self.lineage.player_of(conversation),
                  conversation=conversation, villager_id=u.speaker, name=u.speaker_name, text=u.text, uid=u.id)

    def on_case(self, case: dict, player: str | None = None) -> None:
        """A case opened or changed in the neighborhood app."""
        self.emit("case", case["text"], player=player, case=case)

    def on_post(self, utterance: Utterance, case_id: str, player: str | None = None) -> None:
        """A post about the case in the neighborhood app."""
        u = utterance
        self.emit("post", f'{u.speaker_name} posted: "{u.text}"', player=player, case_id=case_id, speaker=u.speaker_name,
                  text=u.text)

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

    def on_listen(self, place: str, lines: list[Utterance], until: float, *, player: str) -> None:
        """The player starts listening at place until then, hearing first the lines said there lately."""
        heard = [f'{u.speaker_name}: "{u.text}"' for u in lines]
        text = "\n".join([f"You listen at the {place}.", *heard]) if heard else f"You listen at the {place}. It has been quiet here."
        self.emit("listen", text, player=player, place=place, until=until, ended=False,
                  lines=[{"speaker": u.speaker, "speaker_name": u.speaker_name, "text": u.text} for u in lines])

    def on_listen_end(self, place: str, *, player: str) -> None:
        """The player stops listening at place."""
        self.emit("listen", "You stop listening.", player=player, place=place, ended=True)

    def on_delivery(self, utterance: Utterance, listener_ids: list[str]) -> None:
        """Emit the player's whisper, a warning, or a town announcement."""
        u = utterance
        names = [self.town.get(i).name for i in listener_ids if i in self.town]
        if u.speaker == NEWCOMER:
            if listener_ids:
                self.emit("whisper", player=self.lineage.player_of(u.id), uid=u.id, target_id=listener_ids[0], target=names[0] if names else "",
                          place=u.place, text=u.text, conversation=u.conversation)
            return
        if u.verb == "warned":
            if listener_ids and u.about is not None:
                self.on_warning(
                    u.speaker, u.speaker_name, listener_ids[0], names[0] if names else listener_ids[0], u.about,
                )
            return
        if u.verb == "announced":
            self.emit("announcement", speaker=u.speaker_name, place=u.place, text=u.text)
