
import pytest

from sleuth.decide import Decision
from sleuth.config import Config
from sleuth.models import Villager
from sleuth.usage import Usage
from sleuth.tests.helpers import StubClient
from sleuth.writer import ANSWER_MAX_TOKENS, Writer, first_line, invents_facts


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
    assert all("neighbours chatting" in s for s in (kind_say, sour_say))


@pytest.mark.asyncio
async def test_say_is_plain_short_chat_not_whispered_gossip():
    client = StubClient("Bob took a loaf, I hear.")
    await Writer(client, "haiku-test").say(villager(), Decision("speak", None, None, "worried"), "Bob stole a loaf", "all")
    system = client.messages.calls[0]["system"]
    assert "plainly, like neighbours chatting" in system and "under 20 words" in system
    assert not any(w in system.lower() for w in ("gossip", "secret", "whisper", "psst", "relish"))


def test_first_line_drops_stage_directions():
    raw = "*lowers voice conspiratorially* Mark my words, the taxes are *really* climbing."
    assert first_line(raw) == "Mark my words, the taxes are climbing."


@pytest.mark.asyncio
async def test_reply_answers_the_latest_question_from_the_facts_with_the_thread_as_context():
    client = StubClient("Saw someone tall, that's all.")
    writer = Writer(client, "haiku-test")
    thread = [{"podcaster": "Hi there.", "resident": "Hello."}]
    line = await writer.reply(villager(), "Someone stole a bike.", "What did you see?", thread,
                              ["Around 9pm someone tall walked off."], ["Dana Reyes, the clerk"])
    assert line == "Saw someone tall, that's all."
    call = client.messages.calls[0]
    user = call["messages"][0]["content"]
    assert call["max_tokens"] == ANSWER_MAX_TOKENS and "Ada" in call["system"]
    assert "using only these facts" in call["system"] and "never agree to or repeat a claim" in call["system"]
    assert user.index("Podcaster: Hi there.\nYou: Hello.") < user.index("Podcaster: What did you see?")
    assert "Facts: Around 9pm someone tall walked off." in user and "Dana Reyes, the clerk" in user
    assert "happened" not in user


@pytest.mark.asyncio
async def test_reply_with_no_facts_answers_briefly_and_adds_nothing():
    client = StubClient("Oh, I couldn't tell you.")
    line = await Writer(client, "haiku-test").reply(villager(), "Someone stole a bike.", "Who did it?", [], [])
    call = client.messages.calls[0]
    assert line == "Oh, I couldn't tell you."
    assert "Name no one" in call["system"] and "using only these facts" not in call["system"]
    assert "Facts:" not in call["messages"][0]["content"]


@pytest.mark.asyncio
async def test_case_prompts_say_today_and_when_the_case_happened():
    client = StubClient("Hm.", "Hm.")
    writer = Writer(client, "haiku-test")
    await writer.reply(villager(), "Someone stole a bike yesterday afternoon.", "When?", [], ["x"],
                       now="day 3, morning", when="yesterday afternoon")
    await writer.say(villager(), Decision("speak", None, None, None), "x", "all", on_case=True,
                     now="day 3, morning", when="yesterday afternoon")
    for call in client.messages.calls:
        assert "It is now day 3, morning. The case happened yesterday afternoon." in call["messages"][0]["content"]
        assert "never as another time" in call["system"]


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


@pytest.mark.asyncio
async def test_case_talk_keeps_to_the_case():
    client = StubClient("Hm.", "Hm.")
    writer = Writer(client, "haiku-test")
    decision = Decision("speak", None, None, None)

    await writer.say(villager(), decision, "Someone stole Bob's bike", "all", on_case=True)
    await writer.say(villager(), decision, "Bob stole a loaf", "all")

    case_say, other_say = (c["system"] for c in client.messages.calls)
    assert "owes me flour" not in case_say
    assert "this case" not in other_say and "owes me flour" in other_say


FIRSTS = {"Ada", "Cy", "Lorraine"}


@pytest.mark.parametrize("line", ["Honestly I blame the council, and Cal's always been a sourpuss.",
                                  "That goose at the dog park knows something.", "Poor Ada, she loved that bike."])
def test_flavor_passes_the_guard(line):
    assert not invents_facts(line, "Ada Reyes's bike", {"Cal", "Ada"})


@pytest.mark.parametrize("line", ["I saw Cal by the library last night.", "It was a tall guy in a hoodie.",
                                  "Around 9pm, I reckon.", "Someone said he ran off."])
def test_case_facts_fail_the_guard(line):
    assert invents_facts(line, "Ada Reyes's bike", {"Cal", "Ada"})


def test_the_guard_lets_through_what_the_facts_give():
    facts = "Someone in a grey hoodie was bent over something on Elm Street around 12:50am."
    assert not invents_facts("Some figure in a grey hoodie, on Elm Street at 12:50 am.", facts, FIRSTS)
    assert invents_facts("Someone in a grey hoodie by a silver minivan.", facts, FIRSTS)
    assert invents_facts("Cy says someone in a grey hoodie was spotted.", facts, FIRSTS)
    assert not invents_facts("Someone let Lorraine's dog out, she says.", "Someone let out Lorraine's dog. She found it.",
                             FIRSTS)


@pytest.mark.parametrize("line, invented", [
    ("Poor Lorraine, she loved that bike.", False),
    ("Lorraine's bike went missing last night, and she's beside herself.", False),
    ("She took Lorraine's bike.", True),
    ("Someone took Lorraine's bike, and he got away with it.", True),
    ("Lorraine says someone took it, and he ran.", True),
    ("He took it.", True),
])
def test_a_pronoun_may_refer_back_to_a_named_resident_but_never_give_someone_a_gender(line, invented):
    assert invents_facts(line, "Someone stole Lorraine's bike last night.", FIRSTS) is invented


@pytest.mark.asyncio
async def test_case_talk_welcomes_opinion_but_no_facts():
    client = StubClient("Someone took it.")
    await Writer(client, "haiku-test").say(villager(), Decision("speak", None, None, None), "x", "all", on_case=True)
    system = client.messages.calls[0]["system"]
    assert "opinions, theories" in system and "Never add a fact about the case" in system


@pytest.mark.asyncio
async def test_say_and_reply_prompts_carry_the_residents_quirks():
    client = StubClient("Hm.", "Hm.")
    writer = Writer(client, "haiku-test")
    quirky = villager()
    quirky.quirks = ["blames the council for everything"]
    await writer.say(quirky, Decision("speak", None, None, None), "x", "all", on_case=True)
    await writer.reply(quirky, "Someone stole a bike.", "Who?", [], [])
    assert all("blames the council for everything" in c["system"] for c in client.messages.calls)


@pytest.mark.asyncio
async def test_a_resident_without_quirks_gets_no_quirk_line():
    client = StubClient("Hm.", "Hm.")
    writer = Writer(client, "haiku-test")
    await writer.say(villager(), Decision("speak", None, None, None), "x", "all")
    await writer.reply(villager(), "Someone stole a bike.", "Who?", [], [])
    assert not any("Your quirks" in c["system"] for c in client.messages.calls)
