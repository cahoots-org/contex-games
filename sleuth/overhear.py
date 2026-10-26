"""What the player overhears of the talk at their place."""

import logging
import random

from sleuth.actions import CONFRONT, DENY, PREACH, RETELL, SPEAK
from sleuth.calibration import Baselines
from sleuth.config import Config
from sleuth.contex_client import ContexClient
from sleuth.models import Utterance
from sleuth.town import NEWCOMER

log = logging.getLogger(__name__)

# Speech a bystander can overhear; warnings already show in the feed.
SPOKEN = (RETELL, DENY, CONFRONT, SPEAK, PREACH)
HEATED_ACTIONS = (CONFRONT, DENY)
HEATED_STYLES = ("mock", "shift_blame")
LIVELY_STYLES = ("exaggerated", "delighted", "worried", "conspiratorial", "add_detail")


def audible(u: Utterance) -> bool:
    """Whether the line is speech a bystander can hear, not a whisper or a warning."""
    return u.speaker != NEWCOMER and u.action in SPOKEN


class Overhear:
    def __init__(self, contex: ContexClient, baselines: Baselines, config: Config, rng: random.Random):
        self.contex = contex
        self.baselines = baselines
        self.config = config
        self.rng = rng

    async def keep(
        self, utterance: Utterance, player_place: str, hop: bool = False, listening: bool = False,
    ) -> str | None:
        """Why the player overhears the line (listen, heated, lively, or random), or None when they don't.

        A listening player hears every such line.
        Only speech at the player's place that is not their own whisper or a hop on a rumor card is overheard.
        """
        u = utterance
        if hop or u.place != player_place or not audible(u):
            return None
        if listening:
            return "listen"
        if u.action in HEATED_ACTIONS or u.style in HEATED_STYLES:
            return "heated"
        lively = u.style in LIVELY_STYLES
        if lively and self.rng.random() < self.config.lively_rate:
            return "lively"
        if not lively and self.rng.random() < self.config.overhear_rate:
            return "random"
        return None

