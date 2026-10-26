"""Play Sleuth: python -m sleuth [--web]"""

import argparse
import asyncio
import logging
import os
import random
import signal
import sys

import anthropic
import typesafe_sdk
import uvicorn
from dotenv import load_dotenv

from sleuth.calibration import Baselines
from sleuth.cases import Cases
from sleuth.cli import repl, until_over
from sleuth.config import Config
from sleuth.contex_client import ContexClient
from sleuth.engine import Engine
from sleuth.facts import Facts
from sleuth.feed import Feed, terminal
from sleuth.game import Game
from sleuth.lineage import Ids, Lineage
from sleuth.overhear import Overhear
from sleuth.persist import components, resume_game, save_every, save_quietly, set_aside, state_path, stop
from sleuth.player import Player
from sleuth.players import LOCAL_OWNER, Players, new_player_id
from sleuth.routine import Routine
from sleuth.rumors import Rumors
from sleuth.town import PUBLIC_PLACES, Town
from sleuth.town_gen import SeedMismatch, load_or_generate, world_path
from sleuth.usage import CountingJev, Usage
from sleuth.web import create_app
from sleuth.writer import Writer


async def play(web: bool) -> None:
    config = Config.from_env()
    rng = random.Random()
    usage = Usage(config)
    writer = Writer(anthropic.AsyncAnthropic(), config.haiku_model, usage)
    seed = config.seed_path or world_path(config.session, config.data_dir)
    kept = os.path.exists(seed)
    villagers = await load_or_generate(seed, writer, config.population, rng)
    if not config.seed_path:
        if kept:
            print(f"Kept the village saved as {seed}.")
        else:
            print(f"A new village, saved as {seed}. Set SLEUTH_SEED_PATH={seed} to play it again.")
    town, lineage, ids = Town(), Lineage(), Ids()
    feed = Feed(lineage, town, out=None)
    game = Game(config.memory_moves, config.day_seconds)
    async with ContexClient(config.contex_url) as contex:
        jev = CountingJev(typesafe_sdk.AsyncTypeSafeClient(), usage)
        baselines = Baselines(contex, config)
        facts = Facts()
        overhear = Overhear(contex, baselines, config, rng)
        routine = Routine(jev, seed + ".places.json", config)
        engine = Engine(
            config, town, contex, jev, writer, lineage, ids, feed, game=game,
            baselines=baselines, rumors=Rumors(contex, baselines, config), overhear=overhear,
            routine=routine, facts=facts, cases=Cases(config, town, routine, rng, ids),
        )
        players = Players(usage)
        engine.players = players

        def make(player_id: str, owner: str) -> Player:
            return Player(engine, town, lineage, ids, feed, config, writer, game, player_id=player_id, owner=owner)

        def join(owner: str) -> Player:
            """Start a new run for the owner, dropping stale runs that never played."""
            player = make(new_player_id(), owner)
            players.add(player)
            for gone in players.prune():
                gone.close()
            return player

        parts = components(engine)
        saves = state_path(config.session, config.data_dir)
        # Only a fixed session is started again, so only its game is saved.
        fixed = "SLEUTH_SESSION" in os.environ
        if fixed and not kept:
            set_aside(saves)
        if fixed and resume_game(saves, config.session, parts, make):
            villagers = town.villagers
        saving = None
        try:
            await baselines.load([need for v in villagers for need in v.needs])
            await routine.load(villagers)
            await asyncio.gather(*(
                engine.add_villager(
                    v, town.place_of(v.id) if v.id in town else routine.place(v.id, "morning") or rng.choice(PUBLIC_PLACES),
                ) for v in villagers
            ))

            def save() -> None:
                save_quietly(saves, parts, config.session)

            if fixed:
                saving = asyncio.create_task(save_every(config.save_every_seconds, save))
                loop, main_task = asyncio.get_running_loop(), asyncio.current_task()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, stop, save, main_task)
            await engine.run()
            if web:
                host, port = config.address()
                app = create_app(
                    players=players, join=join, town=town, feed=feed, usage=usage, port=port,
                    suspicion=engine.suspicion, game=game, rumors=engine.rumors, hints=engine.hints, host=host,
                    cases=engine.cases,
                )
                server = uvicorn.Server(uvicorn.Config(
                    app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=1,
                    # Behind a TLS proxy such as Railway's, the forwarded scheme says the page was served over https.
                    proxy_headers=True, forwarded_allow_ips="*",
                ))
                print(f"Sleuth is running at http://{host}:{port} (Ctrl-C to stop)")
                await server.serve()
            else:
                player = join(LOCAL_OWNER)
                # The terminal stays open for as long as the game runs.
                player.connected()
                show = terminal(print)
                for event in feed.replay(player.id):
                    show(event)
                feed.sinks.append(feed.view(player.id, show))
                await until_over(repl(player, town, feed, usage), player)
        finally:
            print(usage.summary())
            if saving is not None:
                saving.cancel()
                await asyncio.gather(saving, return_exceptions=True)
            for run in players:
                run.close()
            await engine.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sleuth")
    parser.add_argument("--web", action="store_true", help="play in the browser instead of the terminal")
    args = parser.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("sleuth.engine").setLevel(logging.INFO)
    sys.stdout.reconfigure(line_buffering=True)
    try:
        asyncio.run(play(args.web))
    except SeedMismatch as e:
        sys.exit(str(e))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    # A thread blocked on stdin would stall interpreter exit.
    os._exit(0)


main()
