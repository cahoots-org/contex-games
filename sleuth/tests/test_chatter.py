from random import Random

import pytest

from sleuth.chatter import chatter
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.tests.helpers import StubClient
from sleuth.town import Town
from sleuth.writer import SAY_MAX_TOKENS, Writer

QUIRK = "blames the town council for everything"


def town():
    t = Town()
    t.add(Villager("v1", "Ada Reyes", "baker", "warm", "", ["bread"], {}, home="elm street", quirks=[QUIRK]), "cafe")
    t.add(Villager("v2", "Cal Hughes", "clerk", "calm", "", ["ledgers"], {}, home="oak street"), "bar")
    return t


@pytest.mark.asyncio
async def test_a_post_is_one_haiku_call_in_the_residents_voice():
    client = StubClient("Someone left their bins out again. Typical council.")
    post = await chatter(Writer(client, "haiku-test"), town(), Random(1), Ids(), None)
    [call] = client.messages.calls
    assert call["max_tokens"] == SAY_MAX_TOKENS and QUIRK in call["system"] and "neighborhood app" in call["system"]
    assert (post.speaker, post.speaker_name, post.place, post.verb) == ("v1", "Ada Reyes", "elm street", "posted")
    assert post.text == "Someone left their bins out again. Typical council." and post.parent is None


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["I saw Cal at the library at 9pm.", "Pray for our town.", ""])
async def test_a_post_that_adds_a_case_fact_or_faith_is_dropped(line):
    post = await chatter(Writer(StubClient(line), "haiku-test"), town(), Random(1), Ids(),
                         "Someone stole Ada Reyes's bike on Elm Street last night.")
    assert post is None


@pytest.mark.asyncio
async def test_nobody_posts_without_quirks():
    t = town()
    t.get("v1").quirks = []
    client = StubClient("Hm.")
    assert await chatter(Writer(client, "haiku-test"), t, Random(1), Ids(), None) is None
    assert client.messages.calls == []


@pytest.mark.asyncio
async def test_theories_only_while_a_case_is_open():
    case = "Someone stole Ada Reyes's bike on Elm Street last night."
    client = StubClient(*["Hm."] * 100)
    writer = Writer(client, "haiku-test")
    for seed in range(50):
        await chatter(writer, town(), Random(seed), Ids(), None)
    assert not any("theory" in c["system"] for c in client.messages.calls)
    assert not any(case in c["messages"][0]["content"] for c in client.messages.calls)
    for seed in range(50):
        await chatter(writer, town(), Random(seed), Ids(), case)
    opened = client.messages.calls[50:]
    assert any("theory" in c["system"] for c in opened)
    assert all(f"The open case: {case}" in c["messages"][0]["content"] for c in opened)
