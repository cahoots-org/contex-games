"""The browser front end: one page, a small JSON API, and a WebSocket of feed events."""

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.datastructures import Headers
from starlette.websockets import WebSocketClose

from sleuth.case import CAMERA_PLACES, LOG_PLACES, record_json
from sleuth.cases import Cases, case_json
from sleuth.feed import RESTING, Event, Feed
from sleuth.game import Game
from sleuth.player import Player, Refusal
from sleuth.players import Players, new_owner_id
from sleuth.town import PLACES, Town
from sleuth.traits import describe, face
from sleuth.usage import Usage

log = logging.getLogger(__name__)

PAGE = Path(__file__).parent / "static" / "index.html"
MAX_BODY_BYTES = 8192
USAGE_POLL_SECONDS = 3.0
# How many messages a tab may fall behind before its socket is closed.
CLIENT_QUEUE = 256
BAD_WALK = 'Send JSON like {"place": "bar"}.'
BAD_INTERVIEW = 'Send JSON like {"villager_id": "v1", "text": "Where were you last night?"}.'
BAD_PUBLISH = 'Send JSON like {"culprit_id": "v1", "record_ids": ["r-1"]}.'
COOKIE = "sleuth_player"
COOKIE_SECONDS = 365 * 24 * 3600
RELOAD = "Reload the page to rejoin the town."
LOCAL_HOSTS = ("127.0.0.1", "localhost")


class Guard:
    """Refuse writes from other origins and, on a local server, requests for other hosts (DNS rebinding)."""

    def __init__(self, app, port: int, host: str = "127.0.0.1"):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"} if host in LOCAL_HOSTS else None

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = Headers(scope=scope)
            host = headers.get("host", "")
            origin = headers.get("origin")
            writes = scope["type"] == "websocket" or scope["method"] not in ("GET", "HEAD")
            foreign = self.hosts is not None and host not in self.hosts
            if foreign or (writes and origin is not None and origin not in (f"http://{host}", f"https://{host}")):
                if scope["type"] == "websocket":
                    await WebSocketClose(1008)(scope, receive, send)
                else:
                    await PlainTextResponse("Forbidden", 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def villagers(town: Town) -> list[dict]:
    return sorted(
        ({"id": v.id, "name": v.name, "occupation": v.occupation,
          "looks": describe(v.traits), "face": face(v.traits)} for v in town.villagers),
        key=lambda v: v["name"],
    )


def offer(clients: dict[asyncio.Queue, str], queue: asyncio.Queue, message: dict) -> None:
    """Queue the message for a tab; a tab too far behind stops getting messages and is told to close."""
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        clients.pop(queue, None)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(None)


def player_for(players: Players, cookie: str | None) -> Player | None:
    """The run of the owner the cookie names, if it names one."""
    return players.live(cookie) if cookie else None


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status)


async def _payload(request: Request, bad: str, too_long: str) -> dict | JSONResponse:
    """The request's JSON object, or the 413 or 400 response for a body that is too big or not one."""
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            return _error(413, too_long)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return _error(400, bad)
    return payload if isinstance(payload, dict) else _error(400, bad)


def create_app(
    *, players: Players, join: Callable[[str], Player], town: Town, feed: Feed, usage: Usage, port: int,
    game: Game, host: str = "127.0.0.1", cases: Cases | None = None,
) -> FastAPI:
    clients: dict[asyncio.Queue, str] = {}
    boot = uuid.uuid4().hex
    # What each player's tabs were last sent, by kind.
    sent: dict[str, dict[str, object]] = {"usage": {}}

    def on_event(event: Event) -> None:
        for queue, pid in list(clients.items()):
            if feed.sees(pid, event):
                offer(clients, queue, event.to_json(pid))

    async def watch_each(kind: str, snapshot: Callable[[str], object], seconds: float) -> None:
        """Send each player's tabs their own snapshot whenever it has changed, checking every few seconds."""
        while True:
            await asyncio.sleep(seconds)
            for pid in set(clients.values()):
                now = snapshot(pid)
                if now != sent[kind].get(pid):
                    sent[kind][pid] = now
                    for queue in [q for q, p in clients.items() if p == pid]:
                        offer(clients, queue, {"kind": kind, kind: now})

    async def watch_rest() -> None:
        """Tell everyone when the village starts resting for the day and when it wakes."""
        resting = usage.resting()
        while True:
            await asyncio.sleep(USAGE_POLL_SECONDS)
            if usage.resting() != resting:
                resting = not resting
                feed.on_rest(resting)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        feed.sinks.append(on_event)
        watchers = [
            asyncio.create_task(watch_each("usage", usage.to_json, USAGE_POLL_SECONDS)),
            asyncio.create_task(watch_rest()),
        ]
        try:
            yield
        finally:
            feed.sinks.remove(on_event)
            for w in watchers:
                w.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(Guard, port=port, host=host)
    app.state.clients = clients
    app.state.sent = sent

    @app.get("/healthz")
    async def healthz():
        return PlainTextResponse("ok")

    @app.get("/")
    async def page(request: Request):
        """Serve the page, starting a run for a new visitor."""
        fresh = player_for(players, request.cookies.get(COOKIE)) is None
        if fresh:
            owner = new_owner_id()
            join(owner)
            # Joining may have pruned runs; forget what their tabs were shown.
            kept = {p.id for p in players}
            for shown in sent.values():
                for pid in shown.keys() - kept:
                    del shown[pid]
        response = FileResponse(PAGE)
        if fresh:
            response.set_cookie(
                COOKIE, owner, max_age=COOKIE_SECONDS, httponly=True, samesite="lax", secure=request.url.scheme == "https",
            )
        return response

    @app.get("/api/state")
    async def state(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        return {
            "boot": f"{boot}:{player.id}",
            "places": list(PLACES),
            "place": player.place,
            "time": game.clock(),
            "villagers": villagers(town),
            "talked": {vid: len(thread) for vid, thread in player.threads.items()},
            "records_at": sorted({*CAMERA_PLACES, *LOG_PLACES}),
            "events": [e.to_json(player.id) for e in feed.replay(player.id)],
            "usage": usage.to_json(player.id),
            "resting": usage.resting(),
            "intro": player.owner not in players.onboarded and not player.threads and not player.notebook,
            **case_of(player),
        }

    def case_of(player: Player) -> dict:
        """The player's open case and its notebook, their times said today."""
        case = cases.for_player(player.id) if cases else None
        return {
            "case": case_json(case, town, cases.routine, game.day) if case else None,
            "notebook": [record_json(r, town, case.crime, game.day) for r in player.notebook.values()
                         if case and r.case == case.crime.id],
            "steps": player.steps(),
        }

    @app.get("/api/case")
    async def case(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        return case_of(player)

    @app.get("/api/villagers/{vid}")
    async def inspect(vid: str, request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        if vid not in town:
            name = town.name_of(vid)
            return _error(404, f"{name} has left town." if name else "No resident with that id.")
        v = town.get(vid)
        return {
            "id": v.id,
            "name": v.name,
            "occupation": v.occupation,
            "personality": v.personality,
            "grudge": v.grudge,
            "relationships": [
                {"id": rid, "name": town.name_of(rid) or "someone who left", "kind": kind}
                for rid, kind in v.relationships.items()
            ],
            "traits": v.traits,
            "traits_text": describe(v.traits),
            "home": v.home,
            "household": [
                {"id": o.id, "name": o.name, "kind": v.relationships.get(o.id, "")}
                for o in town.villagers if v.household and o.household == v.household and o.id != v.id
            ],
            "thread": player.thread_json(v.id),
        }

    @app.post("/api/walk")
    async def walk(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        payload = await _payload(request, BAD_WALK, "That request is too long.")
        if isinstance(payload, JSONResponse):
            return payload
        place = payload.get("place")
        if not isinstance(place, str):
            return _error(400, BAD_WALK)
        if problem := player.walk(place.strip().lower()):
            return _error(400, problem)
        return {"ok": True}

    @app.post("/api/interview")
    async def interview(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        payload = await _payload(request, BAD_INTERVIEW, "That request is too long.")
        if isinstance(payload, JSONResponse):
            return payload
        vid, text = payload.get("villager_id"), payload.get("text")
        if not isinstance(vid, str) or not isinstance(text, str):
            return _error(400, BAD_INTERVIEW)
        if usage.resting():
            return _error(409, RESTING)
        if problem := await player.interview(vid, text):
            return _error(409 if isinstance(problem, Refusal) else 400, problem)
        return {"ok": True}

    @app.post("/api/pull")
    async def pull(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        if usage.resting():
            return _error(409, RESTING)
        if problem := player.pull():
            return _error(400, problem)
        return {"ok": True}

    @app.post("/api/search")
    async def search(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        if usage.resting():
            return _error(409, RESTING)
        if problem := player.search():
            return _error(400, problem)
        return {"ok": True}

    @app.post("/api/publish")
    async def publish(request: Request):
        if (player := player_for(players, request.cookies.get(COOKIE))) is None:
            return _error(401, RELOAD)
        payload = await _payload(request, BAD_PUBLISH, "That request is too long.")
        if isinstance(payload, JSONResponse):
            return payload
        culprit, ids = payload.get("culprit_id"), payload.get("record_ids")
        if not isinstance(culprit, str) or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return _error(400, BAD_PUBLISH)
        if usage.resting():
            return _error(409, RESTING)
        if problem := await player.publish(culprit, ids):
            return _error(400, problem)
        return {"ok": True}

    @app.websocket("/ws")
    async def events(socket: WebSocket):
        """Send the player's events until the client goes away; reading is what notices a closed tab."""
        await socket.accept()
        # Accepted first so the browser sees 1008, not a refused handshake; nothing is sent before closing.
        if (player := player_for(players, socket.cookies.get(COOKIE))) is None:
            await socket.close(1008)
            return
        queue: asyncio.Queue = asyncio.Queue(CLIENT_QUEUE)
        sent["usage"].setdefault(player.id, usage.to_json(player.id))
        clients[queue] = player.id
        player.connected()

        async def pump() -> None:
            while (message := await queue.get()) is not None:
                await socket.send_json(message)
            await socket.close(1013)

        sender = asyncio.create_task(pump())
        try:
            while (await socket.receive())["type"] != "websocket.disconnect":
                pass
        finally:
            clients.pop(queue, None)
            player.disconnected()
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)

    return app
