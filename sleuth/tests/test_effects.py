import pytest

from sleuth.actions import (
    ALIBI, BLAME, MOVE, RETELL, SPEAK, WARN,
)
from sleuth.contex_client import Match
from sleuth.decide import Decision
from sleuth.effects import act
from sleuth.facts import Facts
from sleuth.lineage import Ids, Lineage
from sleuth.models import Utterance, Villager
from sleuth.town import Town


class StubWriter:
    def __init__(self, line="words"):
        self.line = line
        self.say_calls = []

        self.on_case = []

    async def say(self, villager, decision, source_text, audience, on_case=False):
        self.say_calls.append((decision.action, source_text, audience))
        self.on_case.append(on_case)
        return self.line



class RecordingHub:
    def __init__(self):
        self.delivered = []
        self.addressed = []
        self.facts = {}
        self.covers = []
        self.warning = None
        self.warned = []
        self.case_roots = set()

    def on_case(self, uid):
        return uid in self.case_roots

    def warn(self, vid, target):
        self.warned.append((vid, target))
        return self.warning

    def cover_story(self, vid, action):
        return self.facts.get(action)

    def mark_cover(self, vid, uid):
        self.covers.append((vid, uid))

    async def deliver(self, utterance, listener_ids, addressed=False):
        self.delivered.append((utterance, listener_ids))
        self.addressed.append(addressed)

def make(vid, name):
    return Villager(vid, name, "baker", "calm", "none", [], {})


class Setup:
    def __init__(self):
        self.town = Town()
        for vid, name in (("v1", "Bert"), ("v2", "Ada"), ("v3", "Cy")):
            self.town.add(make(vid, name))
        self.writer = StubWriter()
        self.hub = RecordingHub()
        self.lineage = Lineage()
        self.ids = Ids()
        self.facts = Facts()

    async def act(self, who, decision, **kw):
        await act(
            decision, self.town.get(who), town=self.town, writer=self.writer,
            hub=self.hub, lineage=self.lineage, ids=self.ids, facts=self.facts, **kw,
        )


def source(uid="u-0"):
    return Match("k", {"id": uid, "text": "Bert stole bread"})


@pytest.mark.asyncio
async def test_retell_delivers_to_target_with_parent_lineage():
    s = Setup()
    s.lineage.record("u-0", None)
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    utt, listeners = s.hub.delivered[0]
    assert listeners == ["v2"]
    assert utt.parent == "u-0"
    assert s.lineage.root(utt.id) == s.lineage.root("u-0")
    assert s.writer.say_calls == [(RETELL, "Bert stole bread", "Ada")]


@pytest.mark.asyncio
async def test_retell_to_target_who_moved_away_delivers_nothing():
    s = Setup()
    s.town.move("v2", "bar")
    await s.act("v1", Decision(RETELL, source(), "v2", None))
    assert s.hub.delivered == []


@pytest.mark.asyncio
async def test_speak_reaches_everyone_present_but_speaker():
    s = Setup()
    await s.act("v1", Decision(SPEAK, None, None, None))
    utt, listeners = s.hub.delivered[0]
    assert sorted(listeners) == ["v2", "v3"]
    assert utt.parent is None
    assert utt.place == "cafe"


@pytest.mark.asyncio
async def test_speaker_never_receives_own_utterance():
    s = Setup()
    await s.act("v1", Decision(SPEAK, None, None, None))
    await s.act("v1", Decision(RETELL, None, "v2", None))
    assert all("v1" not in ids for _, ids in s.hub.delivered)


@pytest.mark.asyncio
async def test_move_changes_place_without_delivery():
    s = Setup()
    await s.act("v1", Decision(MOVE, None, "bar", None))
    assert s.town.place_of("v1") == "bar"
    assert s.hub.delivered == []


@pytest.mark.asyncio
async def test_a_villager_who_moves_may_share_the_news_where_they_arrive():
    s = Setup()
    s.town.move("v2", "bar")
    await s.act("v1", Decision(MOVE, source(), "bar", "worried"), share_chance=1.0)
    utt, listeners = s.hub.delivered[0]
    assert listeners == ["v2"] and utt.place == "bar" and utt.parent == "u-0" and utt.action == RETELL
    assert s.writer.say_calls == [(RETELL, "Bert stole bread", "Ada")]


@pytest.mark.asyncio
async def test_a_move_shares_nothing_without_luck_news_or_company():
    s = Setup()
    s.town.move("v2", "bar")
    await s.act("v1", Decision(MOVE, source(), "bar", None), share_chance=0.0)
    await s.act("v1", Decision(MOVE, None, "cafe", None), share_chance=1.0)
    await s.act("v1", Decision(MOVE, source(), "gym", None), share_chance=1.0)
    assert s.hub.delivered == []


@pytest.mark.asyncio
async def test_act_records_depth_audience_action_style():
    s = Setup()
    s.facts.record(Utterance("u-0", "v3", "Cy", "cafe", "Bert stole bread", None, depth=2))
    recorded_first = []

    async def deliver(utterance, listener_ids, addressed=False):
        recorded_first.append(s.facts.get(utterance.id) is utterance)
        s.hub.delivered.append((utterance, listener_ids))

    s.hub.deliver = deliver
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    await s.act("v1", Decision(SPEAK, source("u-unknown"), None, "angry"))
    got = [(u.depth, u.audience, u.action, u.style) for u, _ in s.hub.delivered]
    assert got == [(3, "one", RETELL, "faithful"), (0, "room", SPEAK, "angry")]
    assert recorded_first == [True] * 2


def test_payload_unchanged():
    u = Utterance("u-1", "v1", "Bert", "cafe", "hi", None, depth=4,
                  audience="room", action=SPEAK, style="sly")
    assert u.to_data() == {"id": "u-1", "text": "Bert said: hi"}


@pytest.mark.asyncio
async def test_alibi_is_told_to_the_target_and_marked_as_cover():
    s = Setup()
    s.hub.facts[ALIBI] = "I was at the gym last night, all night."
    await s.act("v1", Decision(ALIBI, source("u-0"), "v2", "faithful"))
    [(utt, listeners)] = s.hub.delivered
    assert listeners == ["v2"] and utt.parent is None and s.lineage.root(utt.id) == utt.id
    assert s.writer.say_calls == [(ALIBI, "I was at the gym last night, all night.", "Ada")]
    assert s.hub.covers == [("v1", utt.id)]


@pytest.mark.asyncio
async def test_cover_story_does_nothing_without_a_fact_or_a_present_target():
    s = Setup()
    await s.act("v1", Decision(BLAME, None, "v2", None))
    s.hub.facts[BLAME] = "Cy has never liked Ada."
    s.town.move("v2", "bar")
    await s.act("v1", Decision(BLAME, None, "v2", None))
    assert s.hub.delivered == [] and s.hub.covers == []


@pytest.mark.asyncio
async def test_cover_is_marked_before_delivery_so_a_failed_delivery_stays_marked():
    s = Setup()
    s.hub.facts[ALIBI] = "I was at the gym last night, all night."

    async def broken(utterance, listener_ids, addressed=False):
        raise RuntimeError("contex down")

    s.hub.deliver = broken
    with pytest.raises(RuntimeError):
        await s.act("v1", Decision(ALIBI, None, "v2", None))
    assert [vid for vid, _ in s.hub.covers] == ["v1"]


@pytest.mark.asyncio
async def test_a_warning_is_told_to_the_target_as_a_new_line_not_a_cover():
    s = Setup()
    await s.act("v1", Decision(WARN, source("u-0"), "v2", "worried"))
    assert s.hub.delivered == [] and s.hub.warned == [("v1", "v2")]
    s.hub.warning = "The podcaster is stirring up trouble."
    s.town.move("v3", "bar")
    await s.act("v1", Decision(WARN, None, "v3", None))
    assert s.hub.warned == [("v1", "v2")]
    await s.act("v1", Decision(WARN, source("u-0"), "v2", "worried"))
    [(utt, listeners)] = s.hub.delivered
    assert listeners == ["v2"] and utt.parent is None and s.lineage.root(utt.id) == utt.id
    assert s.writer.say_calls[-1] == (WARN, "The podcaster is stirring up trouble.", "Ada") and s.hub.covers == []


@pytest.mark.asyncio
async def test_talk_rooted_in_a_case_and_cover_stories_are_written_as_case_talk():
    s = Setup()
    s.hub.case_roots.add("u-0")
    s.hub.facts[ALIBI] = "I was at the gym."
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    await s.act("v1", Decision(RETELL, source("u-9"), "v2", "faithful"))
    await s.act("v1", Decision(ALIBI, None, "v2", "faithful"))
    assert s.writer.on_case == [True, False, True]


@pytest.mark.asyncio
async def test_case_talk_that_invents_is_dropped():
    s = Setup()
    s.hub.case_roots.add("u-0")
    s.writer.line = "A hooded man stole it, and he had a little dog with him."
    await s.act("v1", Decision(SPEAK, source("u-0"), None, "add_detail"))
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    assert s.hub.delivered == []
    s.writer.line = "Ada, did you hear Bert stole bread?"
    await s.act("v1", Decision(RETELL, source("u-0"), "v2", "faithful"))
    assert [u.text for u, _ in s.hub.delivered] == ["Ada, did you hear Bert stole bread?"]


@pytest.mark.asyncio
async def test_a_cover_story_that_invents_is_told_plainly():
    s = Setup()
    s.hub.facts[ALIBI] = "I was at the gym last night, all night."
    s.writer.line = "I was at the gym with my dog, ask Cy."
    await s.act("v1", Decision(ALIBI, None, "v2", "faithful"))
    [(utt, _)] = s.hub.delivered
    assert utt.text == "I was at the gym last night, all night."


@pytest.mark.asyncio
async def test_talk_off_any_case_is_not_checked():
    s = Setup()
    s.writer.line = "He had a little dog with him."
    await s.act("v1", Decision(SPEAK, source("u-9"), None, None))
    assert [u.text for u, _ in s.hub.delivered] == ["He had a little dog with him."]
