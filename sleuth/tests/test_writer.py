
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
async def test_describe_group_parses_name_and_creed():
    client = StubClient('Sure:\n```json\n{"name": "The Quiet Hand", "creed": "Say less."}\n```')
    writer = Writer(client, "haiku-test")

    name, creed = await writer.describe_group(villager(), ["bread is life"])

    assert (name, creed) == ("The Quiet Hand", "Say less.")


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
async def test_answer_names_the_topic_and_what_was_heard_in_one_line():
    client = StubClient("Tom told me at the mill, aye.", "Not a word.")
    writer = Writer(client, "haiku-test")
    line = await writer.answer(villager(), "the mill", ["Tom at the mill: the mill is haunted"])
    assert line == "Tom told me at the mill, aye."
    call = client.messages.calls[0]
    user = call["messages"][0]["content"]
    assert call["max_tokens"] == SAY_MAX_TOKENS
    assert "the mill" in user and "Tom at the mill: the mill is haunted" in user
    assert "Ada" in call["system"]
    await writer.answer(villager(), "the well", [])
    assert "nothing about it" in client.messages.calls[1]["messages"][0]["content"]
    assert "You know everyone in the town" in call["system"]


@pytest.mark.asyncio
async def test_answer_is_told_who_the_neighbours_in_the_question_are():
    client = StubClient("The tanner? Keeps to himself.")
    writer = Writer(client, "haiku-test")
    await writer.answer(villager(), "Everard Coke", [], ["Everard Coke, the tanner"])
    assert "Neighbours you know: Everard Coke, the tanner" in client.messages.calls[0]["messages"][0]["content"]


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
