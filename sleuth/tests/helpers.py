"""Test doubles and helpers shared by the Sleuth tests."""

import asyncio
from types import SimpleNamespace

from sleuth.config import Config
from sleuth.contex_client import Match
from sleuth.facts import Facts
from sleuth.feed import Feed
from sleuth.lineage import Ids, Lineage
from sleuth.models import Villager
from sleuth.player import Player
from sleuth.players import Players
from sleuth.reputation import Reputation
from sleuth.town import Town

PID = "p-1"
TIMEOUT = 2.0


class StubRoutine:
    """Each resident's place per phase, from a dict."""

    def __init__(self, places):
        self.places = places

    def place(self, vid, phase):
        return self.places.get(vid, {}).get(phase)


class Always:
    """A stand-in for random.Random whose random() is always the same value."""

    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class FakeMind:
    def __init__(self, villager):
        self.villager = villager
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results: list[list[Match]] = []
        self.matches: list[Match] = []
        self.heard = []
        self.seen = set()
        self.polls = 0

    async def open(self):
        pass

    async def hear(self, key, data):
        self.heard.append((key, data))

    async def poll(self):
        self.polls += 1
        fresh = self.results.pop(0) if self.results else [Match(f"k{self.polls}", {"id": "u-0", "text": "news"})]
        self.matches = fresh
        self.seen = {m.data_key for m in fresh}
        return fresh

    async def renew(self):
        pass

    async def pushes(self):
        while True:
            yield await self.queue.get()


def make(vid):
    return Villager(vid, vid.upper(), "baker", "calm", "none", ["bread"], {})


async def wait_for(predicate, timeout=TIMEOUT):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class StubJev:
    def __init__(self, answers, scores=None):
        self.answers = answers
        self.scores = scores
        self.questions = {}
        self.state = None
        self.calls = 0

    async def system_one(self, state, questions):
        self.calls += 1
        self.state = state
        self.questions = questions
        choices = {
            k: SimpleNamespace(choice=v, probabilities={v: 1.0})
            for k, v in self.answers.items() if k in questions
        }
        if self.scores is None:
            return SimpleNamespace(choices=choices)
        scores = {k: SimpleNamespace(score=v, confidence=0.9) for k, v in self.scores.items() if k in questions}
        return SimpleNamespace(choices=choices, scores=scores)


class StubBaselines:
    """A fixed threshold per need, with a default for the rest."""

    def __init__(self, default, **by_need):
        self.default = default
        self.by_need = by_need

    def threshold(self, need):
        return self.by_need.get(need, self.default)

    def matches(self, need, similarity):
        return similarity >= self.threshold(need)

    async def load(self, texts, persist=True):
        pass

    async def measure(self, text):
        return self.default


class StubContex:
    """Answers each query from results keyed by query text; records every call."""

    def __init__(self, results=None, error=None):
        self.results = results or {}
        self.error = error
        self.default = []
        self.queries = []
        self.published = []

    async def publish(self, project_id, data_key, data):
        self.published.append((project_id, data_key, data))

    async def query(self, project_id, query, **kwargs):
        self.queries.append((project_id, query, kwargs))
        if self.error:
            raise self.error
        return self.results.get(query, self.default)


class FakeEngine:
    def __init__(self, contex=None, baselines=None):
        self.contex = contex or StubContex()
        self.baselines = baselines or StubBaselines(0.5)
        self.facts = Facts()
        self.heard = []
        self.recalls = []
        self.cases = None
        self.routine = None
        self.jev = None
        self.reputation = Reputation(Config())
        self.pressed = []
        self.delivered = []
        self.players = Players()
        self.testimony_ids = set()

    def testimony(self, uid):
        return uid in self.testimony_ids

    async def deliver(self, utterance, listener_ids, addressed=False):
        self.delivered.append((utterance, listener_ids, addressed))

    async def recall_heard(self, vid, text):
        self.recalls.append((vid, text))
        return self.heard

    async def press(self, file, player_id):
        self.pressed.append(file)


class StubWriter:
    """Records what each reply was given, and replies with line."""

    def __init__(self, line="Can't say I know much."):
        self.line = line
        self.calls = []

    async def reply(self, villager, case, question, thread, facts, known=(), now="", when=""):
        self.calls.append((villager.id, case, question, list(thread), list(facts), list(known), now, when))
        return self.line


def stub_player(pid=PID, place="cafe", listening=False):
    """An active player standing at place."""
    return SimpleNamespace(
        id=pid, owner=pid, place=place, active=lambda: True, listening=lambda: listening,
    )


def make_player(*names, cooldown=0.0):
    town, lines = Town(), []
    config = Config(cooldown_seconds=cooldown)
    engine = FakeEngine()
    lineage = Lineage()
    for i, name in enumerate(names, 1):
        town.add(Villager(f"v{i}", name, "baker", "calm", "none", [], {}), "bar")
    feed = Feed(lineage, town, out=lines.append)
    player = Player(engine, town, lineage, Ids(), feed, config, player_id=PID)
    return player, town, lines, engine, lineage


class StubMessages:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        block = type("Block", (), {"type": "text", "text": self.texts.pop(0)})()
        usage = type("Usage", (), {"input_tokens": 120, "output_tokens": 30})()
        return type("Response", (), {"content": [block], "usage": usage})()


class StubClient:
    def __init__(self, *texts):
        self.messages = StubMessages(texts)


