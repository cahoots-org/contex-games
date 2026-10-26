"""One Jev request per turn: what does this villager do, and to whom."""

import logging
import random
from dataclasses import dataclass

from typesafe_sdk import Choice, Score

from sleuth.actions import (
    ACTION_NOT_FOR, ACTIONS, IGNORE, MOVE, STYLED, STYLES, TARGET_KIND,
    available_actions,
)
from sleuth.contex_client import Match
from sleuth.models import Villager
from sleuth.town import PLACES

log = logging.getLogger(__name__)

MAX_OPTIONS = 255
# Actions Jev rates below this are never drawn.
MIN_ACTION_PROBABILITY = 0.1
MAX_RECENT = 10

ACTION_INSTRUCTIONS = (
    "You are deciding what one resident of a small modern town does next. "
    "Judge from their personality, grudge, relationships, and what they just heard. "
    "Residents care about news that touches their work, family, standing, fears, or someone "
    "they love or resent, and usually pass it on, argue about it, or act on it. "
    "They do nothing about news that does not concern them, or that they have already "
    "heard: if the same story is among their recent memories, they have dealt with it. "
    "News that alarms them can move them to walk elsewhere."
)

GOSSIP_LEVELS = ["keeps news to themselves", "shares now and then", "loves to share", "can't hold anything in"]
GOSSIP_INSTRUCTIONS = "Given their personality, how readily does this resident pass news on to whoever they meet?"


@dataclass
class TurnView:
    villager: Villager
    place: str
    present: list[Villager]
    new: list[Match]
    recent: list[Match]
    # Whether to ask how much of a gossip the villager is, which is asked once per villager.
    ask_gossip: bool = False
    # The news of the case the villager is the culprit of, while it is set up or open.
    case: str | None = None
    # At night residents stay home, so they can't walk off.
    night: bool = False
    # Whether the culprit, pressed by a podcaster, may warn someone about them now.
    warn: bool = False


@dataclass(frozen=True)
class Decision:
    action: str
    source: Match | None
    target: str | None
    style: str | None
    # How readily the villager passes news on, in [0, 1], when it was asked.
    gossip: float | None = None


def _text(m: Match) -> str:
    return m.data.get("text", "")


def _person(v: Villager, other: Villager) -> str:
    kind = v.relationships.get(other.id)
    return f"{other.name}, {other.occupation}" + (f", their {kind}" if kind else "")


def warmth_words(w: float) -> str:
    """How a tie's warmth reads to Jev."""
    if w >= 0.6:
        return "close"
    if w >= 0.2:
        return "friendly"
    if w > -0.2:
        return "cool"
    return "hostile"


def _state(view: TurnView) -> dict:
    v = view.villager
    state = {
        "villager": {
            "name": v.name, "occupation": v.occupation, "personality": v.personality,
            "grudge": v.grudge,
        },
        "relationships_here": {
            p.name: f"{v.relationships[p.id]}, {warmth_words(v.warmth.get(p.id, 0.0))}"
            for p in view.present if p.id in v.relationships
        },
        "place": view.place,
        "present": [p.name for p in view.present],
        "just_heard": [_text(m) for m in view.new],
        "recent_memories": [_text(m) for m in view.recent[:MAX_RECENT]],
    }
    if view.case:
        state["your_secret"] = f"You did this, and people are talking about it: {view.case}"
    return state


def _action_criteria(view: TurnView) -> dict:
    out = {}
    for a in available_actions(view):
        note = ACTION_NOT_FOR.get(a)
        out[a] = {"what": ACTIONS[a], "not_for": note} if note else ACTIONS[a]
    return out


def _questions(view: TurnView) -> dict[str, Choice | Score]:
    qs = {"action": Choice(instructions=ACTION_INSTRUCTIONS, criteria=_action_criteria(view))}
    if view.ask_gossip:
        qs["gossip"] = Score(instructions=GOSSIP_INSTRUCTIONS, criteria=GOSSIP_LEVELS)
    if len(view.new) > 1:
        qs["source"] = Choice(
            instructions="Which of the things this resident just heard does the action respond to? "
            "Pick the one that matters most to them.",
            criteria={m.data_key: _text(m) for m in view.new},
        )
    if view.present:
        qs["villager_target"] = Choice(
            instructions="Which person nearby is this resident addressing?",
            # Villagers beyond the first 255 in `present` order are dropped.
            criteria={p.id: _person(view.villager, p) for p in view.present[:MAX_OPTIONS]},
        )
    if not view.night:
        qs["place_target"] = Choice(
            instructions="Which place does this resident walk to?",
            criteria={p: None for p in PLACES if p != view.place},
        )
    if any(a in STYLED for a in available_actions(view)):
        qs["style"] = Choice(
            instructions="In what manner would this resident say it, given their personality and what they heard?",
            criteria=dict(STYLES),
        )
    return qs


def _scaled(resp, key: str, levels: list[str]) -> float | None:
    """A score scaled from its levels to [0, 1], or None when it is missing."""
    score = getattr(getattr(resp, "scores", {}).get(key), "score", None)
    if not isinstance(score, (int, float)):
        return None
    return min(1.0, max(0.0, score / (len(levels) - 1)))


async def decide(jev, view: TurnView) -> Decision:
    """Ask Jev once and keep only the answers the chosen action needs.

    The action is drawn from Jev's probabilities, so a likely but not top
    choice still happens some of the time. Options below MIN_ACTION_PROBABILITY
    are dropped first; if none remain, the most probable one is taken.
    """
    resp = await jev.system_one(state=_state(view), questions=_questions(view))
    pick = {k: c.choice for k, c in resp.choices.items()}
    odds = resp.choices["action"].probabilities
    likely = {a: p for a, p in odds.items() if p >= MIN_ACTION_PROBABILITY}
    if likely:
        action = random.choices(list(likely), weights=list(likely.values()))[0]
    else:
        action = max(odds, key=odds.get)
    log.debug("%s: action odds %s, drew %s", view.villager.id, odds, action)
    gossip = _scaled(resp, "gossip", GOSSIP_LEVELS) if view.ask_gossip else None
    if action == IGNORE:
        return Decision(IGNORE, None, None, None, gossip)
    if len(view.new) > 1:
        source = next(m for m in view.new if m.data_key == pick["source"])
    else:
        source = view.new[0] if view.new else None
    kind = TARGET_KIND.get(action)
    target_key = {
        "villager": "villager_target",
        "place": "place_target",
    }.get(kind)
    target = pick.get(target_key) if target_key else None
    # A move keeps a manner in case the villager shares the news where they arrive.
    style = pick.get("style") if action in STYLED or action == MOVE else None
    return Decision(action, source, target, style, gossip)
