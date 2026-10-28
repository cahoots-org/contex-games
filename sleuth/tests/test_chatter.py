from random import Random

import pytest

from sleuth.actions import ALIBI, RETELL, SPEAK
from sleuth.chatter import chatter
from sleuth.decide import Decision
from sleuth.faith import GORE
from sleuth.lineage import Ids
from sleuth.models import Villager
from sleuth.player import SHRUGS
from sleuth.tests.helpers import StubClient
from sleuth.tests.test_effects import Setup, source
from sleuth.tests.test_player import ask, interviewing, memory_of, replies
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
async def test_a_post_that_swaps_the_victims_item_is_dropped_but_a_lost_pet_is_not():
    case = "Someone robbed Ada Reyes's till at the bar yesterday morning."
    swapped = "Has anyone seen Ada Reyes's cash box? It went missing from the bar."
    assert await chatter(Writer(StubClient(swapped), "haiku-test"), town(), Random(1), Ids(), case) is None
    lost = "Has anyone seen my dog Biscuit? Slipped the collar again, typical council fences."
    assert (await chatter(Writer(StubClient(lost), "haiku-test"), town(), Random(1), Ids(), case)).text == lost


@pytest.mark.asyncio
async def test_a_post_cut_off_by_the_token_limit_keeps_only_its_whole_sentences():
    client = StubClient("Lost my dog Biscuit by the cafe. Please call if you see the big shagg",
                        "Lost my dog Biscuit by the cafe again, that big shagg")
    client.messages.stop_reason = "max_tokens"
    writer = Writer(client, "haiku-test")
    assert (await chatter(writer, town(), Random(1), Ids(), None)).text == "Lost my dog Biscuit by the cafe."
    assert await chatter(writer, town(), Random(1), Ids(), None) is None


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


GORY = "There was blood everywhere, I heard."


@pytest.mark.asyncio
async def test_a_line_with_gore_is_never_said():
    assert await chatter(Writer(StubClient(GORY), "haiku-test"), town(), Random(1), Ids(), None) is None
    s = Setup()
    s.writer.line = GORY
    await s.act("v1", Decision(SPEAK, source("u-9"), None, None))
    s.hub.case_roots.add("u-0")
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    assert s.hub.delivered == []
    s.hub.facts[ALIBI] = "I was at the gym."
    await s.act("v1", Decision(ALIBI, None, "v2", "faithful"))
    assert [u.text for u, _ in s.hub.delivered] == ["I was at the gym."]
    player, file, engine, writer = interviewing()
    memory_of(file, player.ids)
    writer.line = "Someone tall in a grey hoodie, and a knife, I saw it."
    await ask(player, "v2", "what_did_you_see")
    assert "knife" not in replies(player)[0] and "tall" in replies(player)[0]
    writer.line = "Poisoned, if you ask me."
    await ask(player, "v4", "what_did_you_see")
    assert replies(player)[1] in SHRUGS
    writer.line = "Someone tall in a grey hoodie, I'll pray for them."
    await ask(player, "v2", "what_did_you_see")
    assert "pray" not in replies(player)[2]
    writer.line = "I'll pray on it."
    await ask(player, "v4", "what_did_you_see")
    assert replies(player)[3] in SHRUGS


@pytest.mark.asyncio
@pytest.mark.parametrize("line", ["Pray for poor Bert.", "They say there was a knife."])
async def test_retold_talk_with_faith_or_gore_is_dropped(line):
    s = Setup()
    s.hub.case_roots.add("u-0")
    s.writer.line = line
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    await s.act("v1", Decision(SPEAK, source("u-0"), None, "faithful"))
    await s.act("v1", Decision(SPEAK, source("u-9"), None, "faithful"))
    assert s.hub.delivered == []


@pytest.mark.parametrize("line", ["He was stabbed.", "A stabbing, they say.", "She was shot.", "Shot him dead.",
                                  "Someone was shooting.", "There was a gunshot."])
def test_grisly_words_are_caught(line):
    assert GORE.search(line)


@pytest.mark.parametrize("line", ["Things feel stable again.", "Stability, finally.", "Lovely photo shoot today.",
                                  "Got my flu shot.", "Worth a shot.", "I'll take a shot at the pie contest."])
def test_everyday_words_are_not_grisly(line):
    assert not GORE.search(line)
