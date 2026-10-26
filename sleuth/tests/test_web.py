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

from sleuth.case import Crime, Record
from sleuth.cases import CaseFile, Cases
from sleuth.config import Config
from sleuth.feed import Feed
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.models import Villager
from sleuth.player import Player
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
    app = create_app(
        players=players, join=join, town=town, feed=feed, usage=usage, port=PORT,
        game=game, cases=cases,
    )
    with TestClient(app, base_url=BASE) as client:
        client.get("/")
        player = players.live(client.cookies[web.COOKIE])
        yield SimpleNamespace(
            client=client, town=town, feed=feed, app=app, usage=usage, player=player, config=config,
            players=players, join=join, engine=engine, cases=cases,
        )
    for p in players:
        p.close()


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


def test_state_lists_each_villagers_looks_and_face(game):
    game.town.get("v1").traits = {"height": "tall", "hair": "bald", "coat": "denim jacket", "car": "bicycle"}
    marta = next(v for v in game.client.get("/api/state").json()["villagers"] if v["id"] == "v1")
    assert marta["looks"] == "tall, bald, in a denim jacket, with a bicycle"
    assert marta["face"] == {"hair": None, "coat": COLOURS["denim jacket"], "height": 2}


def test_page_draws_faces_from_traits_and_lists_looks(game):
    html = game.client.get("/").text
    assert "v.face" in html and "CLOTHES" not in html and "HAIR" not in html
    assert "who(v, `${v.occupation}: ${v.looks}`)" in html


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


def test_page_has_the_walk_listen_and_ask_controls(game):
    html = game.client.get("/").text
    for needle in ("Walk here", "Look around", "Recently said ${atPlace(place)}", "/api/walk", "/api/listen", "/api/interview", 'case "listen"', 'case "interview"',
                   'id="notebook"', '"Interview"'):
        assert needle in html
    assert "/api/ask" not in html and 'case "asked"' not in html
    assert "ariaDisabled" in html
    assert "innerHTML" not in html and "Listen here" not in html and "You listen at" not in html


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


def test_listen_starts_and_a_second_is_refused(game):
    assert game.client.post("/api/listen").json() == {"ok": True}
    again = game.client.post("/api/listen")
    assert again.status_code == 400 and again.json() == {"error": "You just looked around."}


def open_case(game, culprit="v2"):
    crime = Crime("case-1", "steal", "bike", culprit, "v1", "library", 1, "night", 1422, "rival",
                  "Someone stole Marta Hale's bike at the library last night.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open")
    return game.cases.files["case-1"]


def test_interview_reports_problems_and_answers_through_the_feed(game):
    post = game.client.post
    post("/api/walk", json={"place": "library"})
    none = post("/api/interview", json={"villager_id": "v1"})
    assert (none.status_code, none.json()) == (400, {"error": "There's no open case."})
    open_case(game)
    with game.client.websocket_connect(WS) as ws:
        assert post("/api/interview", json={"villager_id": "v1"}).json() == {"ok": True}
        event = receive(ws)
        while event["kind"] != "interview":
            event = receive(ws)
    assert (event["villager_id"], event["line"]) == ("v1", "Marta Hale doesn't know anything about it.")
    away = post("/api/interview", json={"villager_id": "v2"})
    assert (away.status_code, away.json()) == (400, {"error": "Bert Cole is at the gym. Walk there to talk to them."})
    bad = post("/api/interview", json={})
    assert (bad.status_code, bad.json()) == (400, {"error": web.BAD_INTERVIEW})
    assert post("/api/ask", json={"villager_id": "v1", "topic": "x"}).status_code in (404, 405)


def test_a_guarded_resident_is_a_conflict(game):
    open_case(game)
    game.client.post("/api/walk", json={"place": "library"})
    game.engine.reputation.nudge("v1", game.player.id, -1)
    refused = game.client.post("/api/interview", json={"villager_id": "v1"})
    assert refused.status_code == 409 and "Marta Hale" in refused.json()["error"]


def test_state_notebook_hides_soundness(game):
    assert game.client.get("/api/state").json()["notebook"] == []
    open_case(game)
    lie = Record("r-1", "case-1", "statement", "gym", "9:00am", "Bert Cole says they were at the gym last night.", "v2",
                 sound=False)
    old = Record("r-2", "case-0", "statement", "gym", "9:00am", "from an old case", "v2")
    game.player.notebook = {r.id: r for r in (lie, old)}
    body = game.client.get("/api/state").json()
    assert body["notebook"] == [{"id": "r-1", "kind": "statement", "place": "gym", "clock": "9:00am",
                                 "text": lie.text, "from": "Bert Cole"}]
    assert "sound" not in json.dumps(body["notebook"])


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


def test_villager_moves_reach_the_websocket(game):
    with game.client.websocket_connect(WS) as ws:
        game.town.move("v1", "bar")
        event = receive(ws)
    assert event["kind"] == "villagers"
    assert {v["name"]: v["place"] for v in event["villagers"]}["Marta Hale"] == "bar"


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


def test_the_feed_has_speech_and_quiet_lines(game):
    html = game.client.get("/").text
    rove = re.search(r"const ROVE = \"(.*)\";", html).group(1)
    assert rove == ".fold-more"
    for needle in ('"speech"', '"quiet"'):
        assert needle in html
    for gone in ("moved by", "rails", "toggleThread", "cardScene", "innerHTML"):
        assert gone not in html


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


def test_the_panel_has_a_sort(game):
    html = game.client.get("/").text
    for text in ('id="sort"', "By what you know"):
        assert text in html
    assert "innerHTML" not in html


def test_a_phone_gets_two_tabs(game):
    html = game.client.get("/").text
    assert 'role="tablist"' in html
    for tab, controls in (
        ('id="tab-hear"', 'aria-controls="hear-panel"'),
        ('id="tab-village"', 'aria-controls="town"'),
    ):
        assert tab in html and controls in html
    for gone in ("drawer-toggle", "setDrawer", "innerHTML"):
        assert gone not in html
    # The columns are tab panels only on a phone, so a wide screen keeps its landmarks and names.
    assert 'role="tabpanel"' not in html and 'matchMedia("(max-width: 760px)")' in html
    assert '<main id="hear-panel">' in html and 'aria-label="Residents"' in html and "rumors-panel" not in html


RESTING = "The town is resting for today. Come back after midnight UTC."


def spend_the_day(game):
    game.usage.record("haiku", 50_000_000, 0)


def test_case_actions_refused_while_resting(game):
    assert game.client.get("/api/state").json()["resting"] is False
    spend_the_day(game)
    post = game.client.post
    for path, body in (
        ("/api/interview", {"villager_id": "v1"}),
        ("/api/pull", {}),
        ("/api/publish", {"culprit_id": "v1", "record_ids": ["r-1"]}),
    ):
        refused = post(path, json=body)
        assert (refused.status_code, refused.json()) == (409, {"error": RESTING}), path
    assert post("/api/walk", json={"place": "library"}).json() == {"ok": True}
    assert post("/api/listen").json() == {"ok": True}
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


def phone_css(html: str) -> str:
    """The rules under the phone breakpoint."""
    at = html.index("@media (max-width: 760px) {")
    return bracketed(html, html.index("{", at))


def test_a_phone_header_is_one_line_with_a_menu(game):
    html = game.client.get("/").text
    for needle in ('id="menu-toggle"', 'aria-controls="menu"', 'class="menu" id="menu"'):
        assert needle in html
    assert 'id="mood"' not in html and 'id="heat"' not in html and 'id="gameover"' not in html
    menu = re.search(r'<div class="menu" id="menu">(.*?)</div>', html, re.S).group(1)
    assert 'id="usage"' in menu and "trophies" not in menu
    phone = phone_css(html)
    assert ".hud { display: contents; }" in phone and ".menu.open { display: flex; }" in phone
    assert "width: 44px; height: 44px;" in phone and ".conn { order: 3; margin-left: auto; font-size: 0; }" in phone


def test_a_phone_has_its_tabs_at_the_bottom(game):
    html = game.client.get("/").text
    bottom = html[html.index('<div class="bottom">'):html.index("<script>")]
    assert bottom.index('role="tablist"') < bottom.index('class="composer"') and 'id="whisper"' not in bottom
    phone = phone_css(html)
    assert ".tabs { display: flex; border-bottom: 1px solid var(--rail); }" in phone
    assert "min-height: 44px; background: none; border: 0; border-top: 3px solid transparent;" in phone
    assert "border-top-color: var(--accent)" in phone


def test_a_phone_lists_the_village_one_row_per_place(game):
    html = game.client.get("/").text
    find = re.search(r'<div class="find">(.*?)</div>', html, re.S).group(1)
    assert 'id="search"' in find and 'id="sort"' in find
    render = re.search(r"function renderVillagers\(\) \{(.*?)\n\}", html, re.S).group(1)
    assert "if (phone.matches) {" in render and "tileAction(place), closedTile(place, crowd, hits));" in render
    assert "const shown = phone.matches ? first : first.slice(0, FACES_SHOWN);" in html
    # One tab stop per place, not one per villager; the arrows move along a place's faces.
    assert "if (phone.matches && buttons.length) buttons[0].tabIndex = 0;" in html
    assert 'const face = ev.target.closest(".faces .pick");' in html
    phone = phone_css(html)
    assert ".find { display: flex;" in phone and ".tiles .pick { display: grid; place-items: center; width: 44px; height: 44px; }" in phone
    assert "grid-template-columns: 4rem minmax(0, 1fr) 3.25rem;" in phone


def test_state_shows_the_case_without_its_culprit(game):
    assert game.client.get("/api/state").json()["case"] is None
    crime = Crime("case-1", "steal", "bike", "v2", "v1", "library", 1, "night", 1422, "rival",
                  "Someone stole Marta Hale's bike at the library last night.")
    game.cases.files["case-1"] = CaseFile(crime, {}, "open")
    body = game.client.get("/api/state").json()
    assert body["case"] == {"id": "case-1", "text": crime.text, "place": "library", "phase": "night", "day": 1,
                            "state": "open", "private": False}
    assert "culprit" not in json.dumps(body["case"]) and "Bert Cole" not in json.dumps(body["case"])


def test_page_has_the_case_panel(game):
    page = game.client.get("/").text
    assert '<section class="case" id="case" hidden>' in page and "No open case" in page
    for needle in ("Pull records here", "/api/pull", "/api/publish", 'id="culprit"', 'case "pulled"', 'case "episode"'):
        assert needle in page, needle


def test_publish_reports_problems_and_bad_bodies(game):
    post = game.client.post
    bad = post("/api/publish", json={"culprit_id": "v1", "record_ids": "r-1"})
    assert (bad.status_code, bad.json()) == (400, {"error": web.BAD_PUBLISH})
    none = post("/api/publish", json={"culprit_id": "v1", "record_ids": ["r-1"]})
    assert (none.status_code, none.json()) == (400, {"error": "There's no open case."})
    assert post("/api/pull").json() == {"error": "There's no open case."}


def test_whisper_endpoint_is_gone(game):
    assert game.client.post("/api/whisper", json={"villager_id": "v1", "text": "hi"}).status_code in (404, 405)


def test_the_page_reloads_the_case_when_its_own_closes_and_keeps_a_private_one(game):
    page = game.client.get("/").text
    closed = page[page.index('case "case_closed":'):page.index('case "pulled":')]
    assert "loadState()" in closed
    opened = page[page.index('case "case":'):page.index('case "case_closed":')]
    assert "e.case.private" in opened and "dataset.private" in page
