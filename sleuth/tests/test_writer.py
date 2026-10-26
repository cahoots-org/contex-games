
import pytest

from sleuth.decide import Decision
from sleuth.config import Config
from sleuth.models import Villager
from sleuth.usage import Usage
from sleuth.tests.helpers import StubClient
from sleuth.writer import SAY_MAX_TOKENS, Writer, first_line


def villager():
    return Villager("v001", "Ada", "baker", "sharp-tongued", "owes me flour", ["bread"], {})


@pytest.mark.asyncio
async def test_say_includes_style_and_audience_in_prompt():
    client = StubClient("He did it, I tell you.")
    writer = Writer(client, "haiku-test")
    decision = Decision("confront", None, "v002", "exaggerated")

    text = await writer.say(villager(), decision, "Bob stole a loaf", "Bob, to his face")

    call = client.messages.calls[0]
    prompt = call["system"] + call["messages"][0]["content"]
    assert text == "He did it, I tell you."
    assert call["model"] == "haiku-test"
    assert "bigger and more dramatic" in prompt
    assert "Bob, to his face" in prompt
    assert "Bob stole a loaf" in prompt
    assert "sharp-tongued" in prompt


@pytest.mark.asyncio
async def test_say_caps_tokens():
    client = StubClient("Hm.")
    await Writer(client, "haiku-test").say(villager(), Decision("speak", None, None, None), None, "all")
    assert client.messages.calls[0]["max_tokens"] == 80


@pytest.mark.asyncio
async def test_complete_records_usage():
    usage = Usage(Config())
    await Writer(StubClient("Hm.", "Ha."), "haiku-test", usage).complete("s", "u")
    assert usage.tokens["haiku"] == [120, 30]


@pytest.mark.asyncio
async def test_say_mentions_a_grudge_only_when_there_is_one():
    client = StubClient("Hm.", "Hm.")
    writer = Writer(client, "haiku-test")
    kindly = Villager("v002", "Bea", "weaver", "warm", "", ["cloth"], {})
    decision = Decision("speak", None, None, None)

    await writer.say(kindly, decision, "Bob stole a loaf", "all")
    await writer.say(villager(), decision, "Bob stole a loaf", "all")

    kind_say, sour_say = (c["system"] for c in client.messages.calls)
    assert "grudge" not in kind_say.lower()
    assert "Your grudge: owes me flour." in sour_say
    assert all("relish and curiosity, not malice" in s for s in (kind_say, sour_say))


@pytest.mark.asyncio
async def test_say_tells_it_as_a_juicy_secret_in_the_conspiratorial_manner():
    client = StubClient("Between us, he did it.")
    await Writer(client, "haiku-test").say(villager(), Decision("speak", None, None, "conspiratorial"), "Bob stole a loaf", "all")
    assert "Manner: Share it as a juicy secret, in a hushed, confiding way, using words only." in client.messages.calls[0]["messages"][0]["content"]


def test_first_line_drops_stage_directions():
    raw = "*lowers voice conspiratorially* Mark my words, the taxes are *really* climbing."
    assert first_line(raw) == "Mark my words, the taxes are climbing."


@pytest.mark.asyncio
async def test_answer_tells_the_podcaster_only_the_facts_given():
    client = StubClient("Saw someone tall, that's all.", "No idea.")
    writer = Writer(client, "haiku-test")
    line = await writer.answer(villager(), "Someone stole a bike.", ["Around 9pm someone tall walked off."],
                               ["Dana Reyes, the clerk"])
    assert line == "Saw someone tall, that's all."
    call = client.messages.calls[0]
    user = call["messages"][0]["content"]
    assert call["max_tokens"] == SAY_MAX_TOKENS and "Ada" in call["system"]
    assert ("Answer the podcaster in one short sentence in your own voice, using only these facts. "
            "If there are none, say you know nothing about it.") in call["system"]
    assert "Someone stole a bike." in user and "Around 9pm someone tall walked off." in user
    assert "Dana Reyes, the clerk" in user
    await writer.answer(villager(), "Someone stole a bike.", [])
    assert "Facts: none." in client.messages.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_complete_turns_thinking_off_and_reads_only_text():
    class Messages:
        calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            thinking = type("Block", (), {"type": "thinking", "thinking": "hmm"})()
            text = type("Block", (), {"type": "text", "text": " Aye. "})()
            usage = type("Usage", (), {"input_tokens": 1, "output_tokens": 1})()
            return type("Response", (), {"content": [thinking, text], "usage": usage})()

    client = type("Client", (), {"messages": Messages()})()
    assert await Writer(client, "haiku-test").complete("sys", "hi") == "Aye."
    assert client.messages.calls[0]["thinking"] == {"type": "disabled"}
