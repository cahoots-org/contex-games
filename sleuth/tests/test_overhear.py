import os
import random

import pytest

from sleuth.actions import CONFRONT, DENY, RETELL, SPEAK, WARN
from sleuth.config import Config
from sleuth.models import Utterance
from sleuth.overhear import Overhear
from sleuth.tests.helpers import Always, StubBaselines, StubContex
from sleuth.town import NEWCOMER

URL = os.environ.get("SLEUTH_CONTEX_URL")


def line(text="nice weather", place="bar", action=SPEAK, style="faithful", speaker="v1", verb="said"):
    return Utterance("u-1", speaker, "Bert", place, text, None, verb, action=action, style=style)


async def make(results=None, error=None, rate=0.0, roll=0.99):
    contex = StubContex(results, error)
    overhear = Overhear(contex, StubBaselines(0.6), Config(session="s1", overhear_rate=rate), Always(roll))
    return overhear, contex


@pytest.mark.asyncio
async def test_only_the_players_place():
    overhear, _ = await make(rate=1.0, roll=0.0)
    assert await overhear.keep(line(place="bar"), "bar") == "random"
    assert await overhear.keep(line(place="gym"), "bar") is None
    assert await overhear.keep(line(speaker=NEWCOMER), "bar") is None
    assert await overhear.keep(line(action="join_group", verb="announced"), "bar") is None


@pytest.mark.asyncio
async def test_card_hops_are_not_overheard():
    overhear, contex = await make(rate=1.0, roll=0.0)
    assert await overhear.keep(line(action=CONFRONT), "bar", hop=True) is None
    assert contex.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "style"), [
    (CONFRONT, "faithful"), (DENY, "delighted"), (SPEAK, "mock"), (SPEAK, "shift_blame"),
])
async def test_heated_kept(action, style):
    overhear, contex = await make()
    assert await overhear.keep(line(action=action, style=style), "bar") == "heated"
    assert contex.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize("style", ["exaggerated", "delighted", "worried", "conspiratorial", "add_detail"])
async def test_lively_kept(style):
    overhear, contex = await make(roll=0.0)
    assert await overhear.keep(line(action=RETELL, style=style), "bar") == "lively"
    assert contex.queries == []


@pytest.mark.asyncio
async def test_lively_rate():
    overhear = Overhear(StubContex(), StubBaselines(0.6), Config(overhear_rate=1.0), random.Random(7))
    kept = [await overhear.keep(line(style="delighted"), "bar") for _ in range(4000)]
    assert set(kept) == {"lively", None}
    assert 0.37 < kept.count("lively") / len(kept) < 0.43


@pytest.mark.asyncio
async def test_random_rate():
    contex = StubContex()
    overhear = Overhear(contex, StubBaselines(0.6), Config(overhear_rate=0.125), random.Random(7))
    kept = [await overhear.keep(line(), "bar") for _ in range(4000)]
    assert set(kept) == {"random", None}
    assert 0.1 < kept.count("random") / len(kept) < 0.15


@pytest.mark.asyncio
async def test_listening_hears_every_line_but_not_whispers_hops_or_other_places():
    overhear, contex = await make(roll=0.99)
    assert await overhear.keep(line(), "bar", listening=True) == "listen"
    assert await overhear.keep(line(speaker=NEWCOMER), "bar", listening=True) is None
    assert await overhear.keep(line(), "bar", hop=True, listening=True) is None
    assert await overhear.keep(line(action=WARN), "bar", listening=True) is None
    assert await overhear.keep(line(place="gym"), "bar", listening=True) is None
    assert contex.queries == []


