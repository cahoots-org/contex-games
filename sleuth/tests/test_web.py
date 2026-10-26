import asyncio
import json
import random
import re
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from sleuth.case import WHEN, Crime, Record
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.models import Villager
from sleuth.player import SHRUGS, Player
from sleuth.players import Players, new_player_id
from sleuth.town import PLACES, Town
from sleuth.traits import COLOURS
from sleuth.tests import helpers
from sleuth.usage import Usage
from sleuth import web
from sleuth.web import create_app

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}/ws"


def receive(ws, timeout=5.0):
    """ws.receive_json with a timeout, so a missing message fails instead of hanging."""
    got = []
    reader = threading.Thread(target=lambda: got.append(ws.receive_json()), daemon=True)
    reader.start()
    reader.join(timeout)
    assert got, "no WebSocket message"
    return got[0]


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr(web, "USAGE_POLL_SECONDS", 0.05)
    town, lineage = Town(), Lineage()
    town.add(Villager("v1", "Marta Hale", "herbalist", "anxious", "the miller", ["SECRET NEED"], {"v2": "rival"}), "library")
    town.add(Villager("v2", "Bert Cole", "miller", "jolly", "none", ["OTHER NEED"], {}), "gym")
    feed = Feed(lineage, town, out=None)
    config = Config()
    game = Game()
    engine = helpers.FakeEngine()
    players = Players()

    def join(owner):
        player = Player(engine, town, lineage, Ids(), feed, config, game=game, player_id=new_player_id(), owner=owner)
        players.add(player)
        players.prune()
        return player

    usage = Usage(Config())
    cases = engine.cases = Cases(config, town, None, random.Random(1), Ids())
    app = create_app(players=players, join=join, feed=feed, usage=usage, port=PORT)
    with TestClient(app, base_url=BASE) as client:
        client.get("/")
        player = players.live(client.cookies[web.COOKIE])
        yield SimpleNamespace(
            client=client, town=town, feed=feed, app=app, usage=usage, player=player, config=config,
            players=players, join=join, engine=engine, cases=cases, game=game,
        )


def as_owner(client, owner):
    """Make the client's cookie name that owner."""
    client.cookies.clear()
    client.cookies.set(web.COOKIE, owner)


def test_state_lists_villagers_and_replay(game):
    game.feed.say("hello")
    state = game.client.get("/api/state").json()
    assert not {"goals", "world_goal", "trophies", "beliefs"} & state.keys()
    assert [v["name"] for v in state["villagers"]] == ["Bert Cole", "Marta Hale"]
    assert state["places"] == list(PLACES) and state["boot"]
    assert state["events"][-1]["text"] == "hello"
    assert state["place"] == "cafe"
    assert (state["time"]["day"], state["time"]["phase"]) == (1, "morning")
    assert 0 <= state["time"]["fraction"] < 0.25 and state["time"]["day_seconds"] > 0
    assert "NEED" not in game.client.get("/api/state").text


def test_state_counts_each_conversation_and_names_where_records_are_kept(game):
    game.player.threads = {"v1": [{"question": "?", "line": "!", "records": []}] * 2}
    state = game.client.get("/api/state").json()
    assert state["talked"] == {"v1": 2}
    assert set(state["records_at"]) == {"grocery", "bar", "town hall", "elm street", "gym", "library"}


def test_state_lists_each_villagers_looks_and_face(game):
    game.town.get("v1").traits = {"height": "tall", "hair": "bald", "coat": "denim jacket", "car": "bicycle"}
    marta = next(v for v in game.client.get("/api/state").json()["villagers"] if v["id"] == "v1")
    assert marta["looks"] == "tall, bald, in a denim jacket, with a bicycle"
    assert marta["face"] == {"hair": None, "coat": COLOURS["denim jacket"], "height": 2}




def test_inspect_card_never_includes_needs(game):
    response = game.client.get("/api/villagers/v1")
    card = response.json()
    assert (card["occupation"], card["grudge"]) == ("herbalist", "the miller")
    assert card["relationships"] == [{"id": "v2", "name": "Bert Cole", "kind": "rival"}]
    assert "needs" not in card and "NEED" not in response.text
    assert game.client.get("/api/villagers/v9").status_code == 404


def test_inspect_shows_traits_home_and_household_not_warmth(game):
    marta, bert = game.town.get("v1"), game.town.get("v2")
    marta.traits = {"height": "tall", "hair": "bald", "coat": "grey hoodie", "car": "bicycle"}
    for v in (marta, bert):
        v.home, v.household = "elm street", "h01"
    marta.relationships["v2"], bert.relationships["v1"] = "sibling", "sibling"
    marta.warmth["v2"] = bert.warmth["v1"] = 0.73
    response = game.client.get("/api/villagers/v1")
    body = response.json()
    assert body["traits"] == marta.traits and body["home"] == "elm street"
    assert body["traits_text"] == "tall, bald, in a grey hoodie, with a bicycle"
    assert body["household"] == [{"id": "v2", "name": "Bert Cole", "kind": "sibling"}]
    assert "warmth" not in json.dumps(body) and "0.73" not in response.text


def test_inspect_shows_no_household_for_a_villager_without_one(game):
    assert game.client.get("/api/villagers/v2").json()["household"] == []


def test_page_is_served(game):
    response = game.client.get("/")
    assert response.status_code == 200 and "Sleuth" in response.text




def test_a_body_too_deeply_nested_to_parse_is_a_bad_request(game, monkeypatch):
    def too_deep(body):
        raise RecursionError

    monkeypatch.setattr(web.json, "loads", too_deep)
    assert game.client.post("/api/walk", content=b"[" * 8000).status_code == 400


def test_walk_moves_the_player_and_reports_problems(game):
    post = game.client.post
    assert post("/api/walk", json={"place": "gym"}).json() == {"ok": True}
    assert game.client.get("/api/state").json()["place"] == "gym"
    moon = post("/api/walk", json={"place": "moon"})
    assert moon.status_code == 400 and "There's no moon" in moon.json()["error"]
    bad = post("/api/walk", content=b"nope")
    assert bad.status_code == 400 and bad.json() == {"error": web.BAD_WALK}
    assert post("/api/walk", content=b"x" * 10000).status_code == 413




ASK = {"villager_id": "v1", "text": "Where were you last night?"}


def open_case(game, culprit="v2"):
    crime = Crime("case-1", "steal", "bike", culprit, "v1", "library", 1, "night", 1422, "rival",
                  "Someone stole Marta Hale's bike at the library last night.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open")
    return game.cases.files["case-1"]


def test_an_evening_case_reads_last_night_once_night_falls(game):
    crime = Crime("case-1", "steal", "bike", "v2", "v1", "library", 1, "evening", 1100, "rival",
                  f"Someone stole Marta Hale's bike at the library {WHEN}.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open")
    game.game.phase = "evening"
    assert game.client.get("/api/case").json()["case"]["text"].endswith("this evening.")
    game.game.phase = "night"
    assert game.client.get("/api/case").json()["case"]["text"].endswith("last night.")


def test_state_offers_the_intro_until_the_player_starts_or_is_onboarded(game):
    assert game.client.get("/api/state").json()["intro"] is True
    game.player.threads = {"v1": [{"question": "?", "line": "!", "records": []}]}
    assert game.client.get("/api/state").json()["intro"] is False
    game.player.threads = {}
    game.players.onboarded.add(game.player.owner)
    assert game.client.get("/api/state").json()["intro"] is False


def test_a_player_in_the_practice_town_is_shown_that_town_its_case_and_checklist(game):
    real = game.client.get("/api/state").json()
    assert real["steps"] is None
    game.player.begin_tutorial()
    for path in ("/api/state", "/api/case"):
        body = game.client.get(path).json()
        assert (body["case"]["title"], body["case"]["private"], body["case"]["nearby"]) == ("Ruth Okafor's tote bag", True, ["t3"])
        assert body["steps"][0]["text"] == "Ask Ruth Okafor, the victim, what happened"
    state = game.client.get("/api/state").json()
    assert {v["id"] for v in state["villagers"]} == {"t1", "t2", "t3", "t4", "t5", "t6"}
    assert state["time"]["phase"] == "afternoon" and state["boot"] == real["boot"] + ":practice"
    assert game.client.get("/api/villagers/t5").json()["name"] == "Cal Hughes"
    assert game.client.get("/api/villagers/v1").status_code == 404


def test_interview_reports_problems_and_answers_through_the_feed(game):
    post = game.client.post
    post("/api/walk", json={"place": "library"})
    none = post("/api/interview", json=ASK)
    assert (none.status_code, none.json()) == (400, {"error": "There's no open case."})
    open_case(game)
    with game.client.websocket_connect(WS) as ws:
        assert post("/api/interview", json=ASK).json() == {"ok": True}
        event = receive(ws)
        while event["kind"] != "interview":
            event = receive(ws)
    assert (event["villager_id"], event["question"]) == ("v1", ASK["text"]) and event["line"] in SHRUGS
    thread = game.client.get("/api/villagers/v1").json()["thread"]
    assert thread == [{"question": ASK["text"], "line": event["line"], "records": []}]
    assert post("/api/interview", json={"villager_id": "v1"}).json() == {"error": web.BAD_INTERVIEW}
    assert post("/api/interview", json={**ASK, "villager_id": "v2"}).json() == {"ok": True}
    bad = post("/api/interview", json={})
    assert (bad.status_code, bad.json()) == (400, {"error": web.BAD_INTERVIEW})
    assert post("/api/ask", json={"villager_id": "v1", "topic": "x"}).status_code in (404, 405)


def test_a_guarded_resident_is_a_conflict(game):
    open_case(game)
    game.client.post("/api/walk", json={"place": "library"})
    game.engine.reputation.nudge("v1", game.player.id, -1)
    refused = game.client.post("/api/interview", json=ASK)
    assert refused.status_code == 409 and "Marta Hale" in refused.json()["error"]


def test_the_case_and_notebook_say_the_crime_time_from_today(game):
    crime = Crime("case-1", "steal", "bike", "v2", "v1", "library", 2, "afternoon", 800, "rival",
                  f"Someone stole Marta Hale's bike at the library {WHEN}.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open")
    said = Record("r-1", "case-1", "statement", "gym", "9:00am", f"Bert Cole says they were at the gym {WHEN}.", "v2")
    game.player.notebook = {said.id: said}
    for day, when in ((2, "this afternoon"), (3, "yesterday afternoon"), (4, "two days ago, in the afternoon")):
        game.game.day = day
        body = game.client.get("/api/case").json()
        assert body["case"]["text"] == f"Someone stole Marta Hale's bike at the library {when}."
        assert [r["text"] for r in body["notebook"]] == [f"Bert Cole says they were at the gym {when}."]
    html = game.client.get("/").text
    assert 'fetch("/api/case")' in html


def test_state_notebook_hides_soundness(game):
    assert game.client.get("/api/state").json()["notebook"] == []
    open_case(game)
    lie = Record("r-1", "case-1", "statement", "gym", "9:00am", "Bert Cole says they were at the gym last night.", "v2",
                 sound=False)
    old = Record("r-2", "case-0", "statement", "gym", "9:00am", "from an old case", "v2")
    game.player.notebook = {r.id: r for r in (lie, old)}
    body = game.client.get("/api/state").json()
    assert body["notebook"] == [{"id": "r-1", "kind": "statement", "place": "gym", "day": 0,
                                 "clock": "9:00am", "text": lie.text, "from": "Bert Cole", "holder": "v2"}]
    assert "sound" not in json.dumps(body["notebook"])


def test_a_closed_case_s_notebook_stays_until_the_next_case_opens(game):
    file = open_case(game)
    said = Record("r-1", "case-1", "statement", "gym", "9:00am", "Bert Cole says they were at the gym.", "v2")
    game.player.notebook = {said.id: said}
    file.state = "closed"
    body = game.client.get("/api/state").json()
    assert body["case"] is None and [r["id"] for r in body["notebook"]] == ["r-1"]
    crime = Crime("case-2", "steal", "bike", "v1", "v2", "gym", 1, "night", 1422, "rival", "Someone stole a bike.")
    game.cases.files["case-2"] = CaseFile(crime, {}, "open")
    body = game.client.get("/api/case").json()
    assert body["case"]["id"] == "case-2" and body["notebook"] == []
    game.cases.files["case-2"].state = "closed"
    assert game.client.get("/api/case").json()["notebook"] == []


def eventually(check, timeout=5.0):
    """Whether check comes true within timeout, for state another thread changes."""
    done = threading.Event()
    deadline = time.monotonic() + timeout
    while not check() and time.monotonic() < deadline:
        done.wait(0.01)
    return check()


def test_loading_the_page_wakes_no_one_but_an_open_socket_does(game):
    assert not game.players.any_playing()
    with game.client.websocket_connect(WS):
        assert eventually(game.players.any_playing)


def test_websocket_receives_the_walk(game):
    with game.client.websocket_connect(WS) as ws:
        assert game.client.post("/api/walk", json={"place": "library"}).json() == {"ok": True}
        event = receive(ws)
    assert (event["kind"], event["place"]) == ("place", "library")


def test_no_residents_current_place_is_sent(game):
    game.town.move("v1", "dog park")
    game.town.move("v2", "hardware store")
    state = game.client.get("/api/state").json()
    assert state["place"] == "cafe"
    assert all("place" not in v for v in state["villagers"])
    assert not re.search("dog park|hardware store", json.dumps(state["villagers"]))
    for vid in ("v1", "v2"):
        card = game.client.get(f"/api/villagers/{vid}")
        assert "place" not in card.json() and not re.search("dog park|hardware store", card.text)


@pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "localhost"])
def test_other_hosts_are_refused(game, host):
    assert game.client.get("/api/state", headers={"host": host}).status_code == 403


def test_cross_origin_writes_are_refused(game):
    post = game.client.post
    body = {"place": "library"}
    assert post("/api/walk", json=body, headers={"origin": "http://evil.example"}).status_code == 403
    assert post("/api/walk", json=body, headers={"origin": f"http://localhost:{PORT}"}).status_code == 403
    assert post("/api/walk", json=body, headers={"origin": BASE}).status_code == 200
    assert post("/api/walk", json=body, headers={"origin": "null"}).status_code == 403
    for headers in ({"origin": "http://evil.example"}, {"origin": "null"}, {"host": "evil.example:8765"}):
        with pytest.raises(WebSocketDisconnect):
            with game.client.websocket_connect(WS, headers=headers) as ws:
                receive(ws)


def test_same_origin_websocket_is_accepted(game):
    with game.client.websocket_connect(WS, headers={"origin": BASE}) as ws:
        game.feed.say("hello")
        assert receive(ws)["text"] == "hello"


def test_closed_tab_is_dropped(game):
    with game.client.websocket_connect(WS):
        assert len(game.app.state.clients) == 1
    deadline = time.monotonic() + 5
    while game.app.state.clients and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not game.app.state.clients


def test_usage_is_in_state_and_reaches_the_websocket(game):
    assert game.client.get("/api/state").json()["usage"]["summary"] == "Your investigation has cost about $0.00 so far"
    with game.client.websocket_connect(WS) as ws:
        game.usage.record("haiku", 100_000, 20_000, player=game.player.id)
        event = receive(ws)
    assert event["kind"] == "usage"
    assert event["usage"]["summary"] == "Your investigation has cost about $0.02 so far"


def test_each_session_sees_only_its_own_cost(game):
    a = game.player
    game.client.cookies.clear()
    b = game.players.live(game.client.get("/").cookies[web.COOKIE])
    game.usage.record("haiku", 10_000_000, 0, player=a.id)
    game.usage.record("haiku", 1_000_000, 0)
    with game.client.websocket_connect(WS) as ws:
        assert game.client.get("/api/state").json()["usage"]["summary"] == "Your investigation has cost about $0.00 so far"
        game.usage.record("haiku", 20_000_000, 0, player=a.id)
        game.usage.record("haiku", 30_000_000, 0, player=b.id)
        event = receive(ws)
    assert event == {"kind": "usage", "usage": {"summary": "Your investigation has cost about $3.00 so far", "cost": 3.0}}
    as_owner(game.client, a.owner)
    assert game.client.get("/api/state").json()["usage"]["summary"] == "Your investigation has cost about $3.00 so far"


def test_first_visit_sets_an_owner_cookie(game):
    game.client.cookies.clear()
    response = game.client.get("/")
    assert response.cookies[web.COOKIE].startswith("o-")
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "max-age=31536000" in header


def test_two_sessions_play_as_two_players(game):
    a = game.client.cookies[web.COOKIE]
    game.client.post("/api/walk", json={"place": "library"})
    game.client.cookies.clear()
    b = game.client.get("/").cookies[web.COOKIE]
    state = game.client.get("/api/state")
    body = state.json()
    assert a != b and a not in state.text
    assert body["place"] == "cafe" and not [e for e in body["events"] if e["kind"] == "place"]


def test_a_players_socket_gets_none_of_another_players_events(game):
    a = game.client.cookies[web.COOKIE]
    game.client.cookies.clear()
    b = game.players.live(game.client.get("/").cookies[web.COOKIE])
    with game.client.websocket_connect(WS) as ws:
        as_owner(game.client, a)
        assert game.client.post("/api/walk", json={"place": "library"}).json() == {"ok": True}
        game.feed.say("ping", player=b.id)
        assert receive(ws)["text"] == "ping"


def test_two_tabs_of_one_player_both_get_its_events(game):
    with game.client.websocket_connect(WS) as ws1, game.client.websocket_connect(WS) as ws2:
        game.client.post("/api/walk", json={"place": "library"})
        assert receive(ws1)["kind"] == receive(ws2)["kind"] == "place"


def test_an_unknown_cookie_asks_for_a_reload(game):
    as_owner(game.client, "p-forged")
    response = game.client.get("/api/state")
    assert (response.status_code, response.json()) == (401, {"error": web.RELOAD})
    assert game.client.get("/api/villagers/v1").status_code == 401
    assert game.client.post("/api/walk", json={"place": "library"}).status_code == 401
    with game.client.websocket_connect(WS) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1008
    assert game.client.get("/").cookies[web.COOKIE] != "p-forged"


def test_a_new_run_resets_the_page(game):
    boot = game.client.get("/api/state").json()["boot"]
    game.client.cookies.clear()
    game.client.get("/")
    assert game.client.get("/api/state").json()["boot"] != boot


def test_state_never_names_or_counts_other_players(game):
    other = game.join("o-other")
    game.feed.say("for the other one", player=other.id)
    response = game.client.get("/api/state")
    assert other.id not in response.text and "o-other" not in response.text and "for the other one" not in response.text
    assert "players" not in response.json()




def outside_brackets(text: str) -> str:
    """text with everything inside (), [] and {} dropped."""
    out, depth = [], 0
    for ch in text:
        depth -= ch in ")]}"
        if depth == 0:
            out.append(ch)
        depth += ch in "([{"
    return "".join(out)


def bracketed(text: str, at: int) -> str:
    """What sits inside the bracket opened at text[at]."""
    depth, i = 1, at + 1
    while depth:
        depth += (text[i] in "([{") - (text[i] in ")]}")
        i += 1
    return text[at + 1:i - 1]


def test_no_replace_children_call_can_render_null(game):
    """replaceChildren, unlike el, writes a null child as the text "null"."""
    html = game.client.get("/").text
    calls = [bracketed(html, m.end() - 1) for m in re.finditer(r"replaceChildren\(", html)]
    assert calls
    for args in calls:
        assert "null" not in outside_brackets(args), args
        for spread in re.finditer(r"\.\.\.\[", args):
            items = bracketed(args, spread.end() - 1)
            after = args[spread.end() + len(items) + 1:]
            assert "null" not in outside_brackets(items) or after.startswith(".filter(Boolean)"), items






RESTING = "The town is resting for today. Come back after midnight UTC."


def spend_the_day(game):
    game.usage.record("haiku", 50_000_000, 0)


def test_case_actions_refused_while_resting(game):
    assert game.client.get("/api/state").json()["resting"] is False
    spend_the_day(game)
    post = game.client.post
    for path, body in (
        ("/api/interview", ASK),
        ("/api/pull", {}),
        ("/api/search", {}),
        ("/api/publish", {"culprit_id": "v1", "record_ids": ["r-1"]}),
    ):
        refused = post(path, json=body)
        assert (refused.status_code, refused.json()) == (409, {"error": RESTING}), path
    assert post("/api/walk", json={"place": "library"}).json() == {"ok": True}
    assert post("/api/listen").status_code in (404, 405)
    assert game.client.get("/api/state").json()["resting"] is True


def test_everyone_hears_when_the_village_rests_and_wakes(game, monkeypatch):
    now = [datetime(2026, 10, 23, 23, 0, tzinfo=UTC).timestamp()]
    monkeypatch.setattr(time, "time", lambda: now[0])
    with game.client.websocket_connect(WS) as ws:
        spend_the_day(game)
        event = receive(ws)
        while event["kind"] != "rest":
            event = receive(ws)
        assert (event["resting"], event["text"]) == (True, RESTING)
        now[0] = datetime(2026, 10, 24, 0, 1, tzinfo=UTC).timestamp()
        event = receive(ws)
        while event["kind"] != "rest":
            event = receive(ws)
        assert event["resting"] is False and event["text"]


def test_the_page_shows_a_resting_banner(game):
    html = game.client.get("/").text
    for needle in ('id="resting"', 'case "rest"', "state.resting", "setResting(", RESTING):
        assert needle in html


def test_healthz_answers_without_starting_a_run(game):
    game.client.cookies.clear()
    runs = list(game.players)
    response = game.client.get("/healthz")
    assert (response.status_code, response.text) == (200, "ok")
    assert list(game.players) == runs and web.COOKIE not in response.cookies


def guarded(host):
    inner = FastAPI()
    inner.get("/")(lambda: "read")
    inner.post("/")(lambda: "wrote")
    return TestClient(web.Guard(inner, PORT, host))


def test_a_public_guard_takes_any_host_but_only_same_origin_writes():
    client = guarded("0.0.0.0")
    site = {"host": "sleuth.usecontex.com"}
    assert client.get("/", headers=site).status_code == 200
    assert client.post("/", headers={**site, "origin": "https://sleuth.usecontex.com"}).status_code == 200
    assert client.post("/", headers={**site, "origin": "https://evil.example"}).status_code == 403


def test_a_local_guard_still_refuses_other_hosts():
    client = guarded("127.0.0.1")
    assert client.get("/", headers={"host": "sleuth.usecontex.com"}).status_code == 403
    assert client.get("/", headers={"host": f"127.0.0.1:{PORT}"}).status_code == 200


def test_the_page_opens_a_secure_socket_on_https(game):
    assert 'location.protocol === "https:" ? "wss" : "ws"' in game.client.get("/").text


def close_code(ws, timeout=5.0):
    """The code the server closes the socket with, skipping messages before it; fails instead of hanging."""
    codes = []

    def read():
        try:
            while True:
                ws.receive_json()
        except WebSocketDisconnect as closed:
            codes.append(closed.code)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    assert codes, "the socket stayed open"
    return codes[0]


def test_a_socket_that_falls_too_far_behind_is_closed(game, monkeypatch):
    monkeypatch.setattr(web, "CLIENT_QUEUE", 1)
    with game.client.websocket_connect(WS) as ws:
        assert eventually(lambda: game.app.state.clients)
        # Said on the server's loop in one go, so the tab can't catch up between lines.
        game.client.portal.call(lambda: [game.feed.say(f"line {n}") for n in range(3)])
        assert close_code(ws) == 1013
    assert eventually(lambda: not game.app.state.clients)


def test_offer_drops_a_full_queue_for_a_close():
    queue = asyncio.Queue(2)
    clients = {queue: "p-1"}
    for n in range(3):
        web.offer(clients, queue, {"n": n})
    assert clients == {} and queue.qsize() == 1 and queue.get_nowait() is None


def test_the_cookie_is_secure_over_https(game):
    plain = TestClient(game.app, base_url=BASE).get("/")
    secure = TestClient(game.app, base_url=f"https://127.0.0.1:{PORT}").get("/")
    assert "secure" not in plain.headers["set-cookie"].lower()
    assert "secure" in secure.headers["set-cookie"].lower()


def test_a_pruned_run_leaves_no_sent_snapshots(game, monkeypatch):
    now = [time.time()]
    monkeypatch.setattr(time, "time", lambda: now[0])
    visitor = TestClient(game.app, base_url=BASE)
    visitor.get("/")
    gone = game.players.live(visitor.cookies[web.COOKIE])
    visitor.get("/api/state")
    game.app.state.sent["usage"][gone.id] = {}
    now[0] += game.config.idle_after_seconds
    TestClient(game.app, base_url=BASE).get("/")
    assert game.players.get(gone.id) is None
    assert all(gone.id not in kind for kind in game.app.state.sent.values())










def test_state_shows_the_case_without_its_culprit(game):
    assert game.client.get("/api/state").json()["case"] is None
    crime = Crime("case-1", "steal", "bike", "v2", "v1", "library", 1, "night", 1422, "rival",
                  "Someone stole Marta Hale's bike at the library last night.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open", whereabouts={"v2": ["library"]})
    game.cases.routine = helpers.StubRoutine({"v2": {"night": "gym"}})
    game.town.move("v2", "library")
    body = game.client.get("/api/state").json()
    assert body["case"] == {"id": "case-1", "text": crime.text, "place": "library", "phase": "night", "day": 1,
                            "state": "open", "private": False, "title": "Marta Hale's bike", "victim": "v1",
                            "nearby": []}
    assert "culprit" not in json.dumps(body["case"]) and "Bert Cole" not in json.dumps(body["case"])




def test_publish_reports_problems_and_bad_bodies(game):
    post = game.client.post
    bad = post("/api/publish", json={"culprit_id": "v1", "record_ids": "r-1"})
    assert (bad.status_code, bad.json()) == (400, {"error": web.BAD_PUBLISH})
    none = post("/api/publish", json={"culprit_id": "v1", "record_ids": ["r-1"]})
    assert (none.status_code, none.json()) == (400, {"error": "There's no open case."})
    assert post("/api/pull").json() == {"error": "There's no open case."}
    assert post("/api/search").json() == {"error": "There's no open case."}


def test_whisper_endpoint_is_gone(game):
    assert game.client.post("/api/whisper", json={"villager_id": "v1", "text": "hi"}).status_code in (404, 405)


def test_page_is_built_around_the_case(game):
    html = game.client.get("/").text
    order = ['id="case"', 'id="notebook"', 'id="here"', 'id="talk"', 'id="people"', 'id="convo"']
    assert [html.index(n) for n in order] == sorted(html.index(n) for n in order)
    for needle in ('id="publish-open"', 'id="culprit"', "/api/publish", "/api/interview", "/api/walk", "/api/pull",
                   "/api/search", 'case "interview"', 'case "pulled"', 'case "searched"', 'case "steps"', "usually nearby", 'id="intro"',
                   "@media (max-width: 600px)"):
        assert needle in html, needle
    for gone in ("/api/listen", "Look around", "tiles", "card-title", 'role="tablist"', "innerHTML"):
        assert gone not in html, gone


def test_the_notebook_groups_entries_by_kind(game):
    html = game.client.get("/").text
    assert 'const GROUPS = ["Seen", "Clip", "Logs", "Said", "Found", "Heard"];' in html
    for kind in ("memory", "clip", "log", "statement", "clue", "discovery"):
        assert f"{kind}: " in html[html.index("const GROUP_OF"):], kind


def test_the_page_reloads_the_case_when_its_own_closes_and_keeps_a_private_one(game):
    page = game.client.get("/").text
    closed = page[page.index('case "case_closed":'):page.index('case "pulled":')]
    assert "loadState()" in closed
    opened = page[page.index('case "case":'):page.index('case "case_closed":')]
    assert "e.case.private" in opened and "caseNow.private" in opened



def test_a_verdict_clears_when_another_case_opens(game):
    page = game.client.get("/").text
    changed = page[page.index("function setCase(c)"):page.index("caseNow = open;")]
    assert 'if (open) say("case-status", "");' in changed


def test_search_and_pull_show_only_while_they_can_be_used(game):
    file = open_case(game)
    game.player.place = "library"
    assert game.client.get("/api/state").json()["searched"] == []
    assert game.client.post("/api/search").status_code == 200
    assert game.client.get("/api/case").json()["searched"] == [file.crime.id]
    page = game.client.get("/").text
    where = page[page.index("function drawWhere()"):page.index("function setSteps")]
    assert "!searched.has(caseNow.id)" in where and "caseNow && recordsAt.includes(here)" in where
