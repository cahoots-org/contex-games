import json
from dataclasses import replace
from random import Random

import pytest

from sleuth import cases as cases_mod
from sleuth.case import NO_WITNESS, logs
from sleuth.cases import case_json
from sleuth.lineage import Ids
from sleuth.liars import COVERED_ME, HOBBIES, SECRETS, pick_liar
from sleuth.tests.helpers import StubRoutine
from sleuth.tests.test_case import RESIDENTS, make_routine
from sleuth.tests.test_cases import culprit_file, make_cases, podcaster, tick, tiered
from sleuth.tests.test_falsehoods import serious_cases
from sleuth.tests.test_player import ask, interviewing, notebook

# For each kind: who is where at night other than home, Ivy's (v6) ties, and who works where of a morning.
FITS = {
    "somewhere": ({"v6": "bar"}, {}, {}),
    "hobby": ({"v6": "library"}, {}, {}),
    "surprise": ({"v6": "cafe", "v7": "cafe"}, {"v7": "friend", "v8": "sister"}, {}),
    "job": ({"v6": "cafe"}, {}, {"v2": "cafe", "v6": "gym"}),
    "covering": ({"v6": "cafe", "v7": "cafe"}, {"v7": "friend"}, {}),
}


def fitted(kind):
    """A theft of Dana's (v1) bike by Fay (v3) on a night that fits kind, its whereabouts and log records."""
    cases, _, town = make_cases()
    out, ties, work = FITS[kind]
    town.get("v6").relationships.update(ties)
    whereabouts = {vid: [street, *([out[vid]] if vid in out else [])] for vid, _, _, street in RESIDENTS}
    routine = StubRoutine({vid: {"morning": place} for vid, place in work.items()})
    crime = culprit_file(cases).crime
    return crime, whereabouts, town, routine, logs(crime, whereabouts, town, Random(0), Ids())


@pytest.mark.parametrize("kind", list(SECRETS))
def test_each_secret_kind_has_someone_or_something_to_expose_it(kind):
    crime, whereabouts, town, routine, records = fitted(kind)
    vid, secret = pick_liar(crime, whereabouts, town, routine, Random(0), set(), records, kinds=(kind,))
    assert vid == "v6" and secret["kind"] == kind and secret["claimed"] == "oak street"
    assert secret["place"] in whereabouts["v6"] and secret["text"].startswith("Ivy was ")
    if kind in ("somewhere", "hobby"):
        [log] = [r for r in records if r.id == secret["exposer"]]
        assert (log.who, log.place) == ("v6", secret["place"])
    else:
        assert secret["exposer"] in town and secret["exposer"] != "v6"
    if kind == "hobby":
        assert any(h in secret["text"] for h in HOBBIES)
    assert pick_liar(crime, whereabouts, town, routine, Random(0), {"v6"}, records, kinds=(kind,)) is None


def test_no_one_lies_who_is_home_the_whole_time():
    crime, whereabouts, town, routine, records = fitted("somewhere")
    whereabouts["v6"] = ["oak street"]
    assert pick_liar(crime, whereabouts, town, routine, Random(0), set(), records) is None


def test_a_liar_never_claims_to_have_been_at_the_scene():
    crime, whereabouts, town, routine, _ = fitted("somewhere")
    whereabouts["v6"], whereabouts["v2"] = ["oak street"], ["elm street", "bar"]
    records = logs(crime, whereabouts, town, Random(0), Ids())
    assert pick_liar(crime, whereabouts, town, routine, Random(0), set(), records) is None
    routine.places["v2"] = {"night": "library"}
    vid, secret = pick_liar(crime, whereabouts, town, routine, Random(0), set(), records)
    assert vid == "v2" and secret["claimed"] == "library"
    assert secret["text"] == "Eli was at the bar when they'd said they were at the library"
    routine.places["v2"] = {"night": "bar"}
    assert pick_liar(crime, whereabouts, town, routine, Random(0), set(), records) is None


def test_a_liar_was_never_truly_at_the_scene():
    crime, whereabouts, town, routine, records = fitted("somewhere")
    assert pick_liar(replace(crime, place="bar"), whereabouts, town, routine, Random(0), set(), records) is None


def liar_file():
    """Ivy (v6) at the bar the night Fay stole Dana's bike, saying she was home; the bar's log shows her."""
    player, file, engine, writer = interviewing()
    crime, whereabouts, town, routine, records = fitted("somewhere")
    file.whereabouts = whereabouts
    file.records = {r.id: r for r in records}
    [log] = [r for r in records if r.who == "v6"]
    file.liars = {"v6": {"kind": "somewhere", "place": "bar", "claimed": "oak street", "exposer": log.id,
                         "text": "Ivy was at the bar when they'd said they were home",
                         "said": "Ivy was at the bar when they'd said they were home"}}
    return player, file, engine, writer, log


@pytest.mark.asyncio
async def test_a_liar_s_claim_is_disproved_by_the_log_that_shows_them():
    player, file, engine, writer, log = liar_file()
    await ask(player, "v6", "where_were_you")
    [said] = notebook(player)
    assert (said.text, said.sound, said.disproof) == ("Ivy Burke says they were on Oak Street {when}.", False, log.id)


@pytest.mark.asyncio
async def test_the_exposer_gives_the_liar_away_when_asked():
    player, file, engine, writer, _ = liar_file()
    file.liars["v6"] = {**file.liars["v6"], "kind": "covering", "place": "cafe", "exposer": "v7",
                        "text": "Ivy was covering for Jo Tran, who'd been up to something small",
                        "said": COVERED_ME.format(first="Ivy")}
    await ask(player, "v8", "where_was", who="v6")
    assert not [r for r in notebook(player) if "covering" in r.text]
    await ask(player, "v7", "where_was", who="v6")
    [said] = [r for r in notebook(player) if r.holder == "v7"]
    assert (said.text, said.sound, said.who) == (
        "Jo Tran: Ivy was covering for me. I'd been up to something small.", True, "v6")
    await ask(player, "v6", "where_were_you")
    [claim] = [r for r in notebook(player) if r.holder == "v6"]
    assert (claim.sound, claim.disproof) == (False, None)


def test_naming_a_liar_brings_out_their_secret():
    cases, engine, town = make_cases()
    file = culprit_file(cases)
    cases.now = 2.0
    file.liars = {"v6": {"kind": "job", "place": "cafe", "claimed": "oak street", "exposer": "v2",
                         "text": "Ivy was interviewing for a job at the cafe"}}
    cases.on_wrong(engine, file, "p-1", "v6")
    [post] = [e for e in engine.feed.recent if e.kind == "post"]
    assert post.data["text"] == "Ivy Burke wasn't home last night: Ivy was interviewing for a job at the cafe."
    assert post.data["app"] and post.data["case_id"] == file.crime.id
    config = cases.config
    assert engine.reputation.get("v6", "p-1") == pytest.approx(config.reputation_wrong + config.reputation_accused)
    cases.on_wrong(engine, file, "p-1", "v5")
    cases.on_wrong(engine, file, "p-2", "v6")
    assert len([e for e in engine.feed.recent if e.kind == "post"]) == 1


@pytest.fixture
def lying(monkeypatch):
    monkeypatch.setattr(cases_mod, "LIAR_CHANCE", 1.0)
    monkeypatch.setitem(NO_WITNESS, "serious", 0.0)


# Who is out at night: Ivy and Jo at the cafe, Kit at the bar, Eli at the library.
OUT = {"v2": "library", "v6": "cafe", "v7": "cafe", "v8": "bar"}


@pytest.mark.asyncio
async def test_serious_cases_get_innocent_liars_who_are_not_witnesses(lying):
    staged = await serious_cases(range(40), night=OUT)
    liars = [(f, vid, s) for f, _ in staged for vid, s in f.liars.items()]
    assert liars
    for file, vid, secret in liars:
        holders = {r.holder for r in file.records.values()}
        assert vid not in (file.crime.culprit, file.crime.victim, file.accomplice) and vid not in holders
        assert secret["place"] in file.whereabouts[vid] and secret["claimed"] != secret["place"]


@pytest.mark.asyncio
async def test_a_secret_stays_hidden_until_named(lying):
    for seed in range(40):
        cases, engine, town = make_cases(offenders=8)
        cases.routine = make_routine(OUT)
        cases.rng = Random(seed)
        engine.players.add(podcaster("serious"))
        tiered(cases, "petty", opened=2.0)
        await tick(cases, engine)
        file = next((f for f in cases.open_shared("serious") if f.liars), None)
        if file:
            break
    [(vid, secret)] = file.liars.items()
    shown = json.dumps([[e.kind, e.line, e.data] for e in engine.feed.recent])
    shown += json.dumps(case_json(file, town, cases.routine, 2.0))
    shown += json.dumps([u.text for u, _, _ in engine.delivered])
    assert secret["text"] not in shown
    cases.on_wrong(engine, file, "p-1", vid)
    assert any(secret["text"] in e.data["text"] for e in engine.feed.recent if e.kind == "post")


@pytest.mark.asyncio
async def test_a_petty_case_never_has_a_liar(lying):
    for seed in range(30):
        cases, engine, town = make_cases(offenders=8)
        cases.routine = make_routine(OUT)
        cases.rng = Random(seed)
        await tick(cases, engine)
        assert [f.liars for f in cases.open_shared("petty")] == [{}]
