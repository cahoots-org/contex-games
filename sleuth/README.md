# Sleuth

A small-town deduction game on the Whispers engine, being built from the design in
[docs/superpowers/specs/2026-10-25-sleuth-design.md](../docs/superpowers/specs/2026-10-25-sleuth-design.md).
It started as a copy of Whispers and still plays like it; this README describes the game as it stands.

## Places and routine

The public places are the cafe, gym, school, bar, dog park, hardware store, grocery, town hall and library. Households live on elm, oak or maple street, and each street is one place. Jev picks each resident's work place and evening place once; the day runs work, work, leisure, then home on their street at night. The choices are kept beside the seed and asked again if a resident's name or home changes.

## Cases

While someone is playing and no shared case is open, a petty crime is staged at the start of a part of the day, `crime_every_days` after the last shared case closed. The culprit is drawn from a household other than the victim's, someone the routine expects elsewhere, and is sent to the crime place and kept there for the rest of that part of the day.

At the next tick the case is checked. Its evidence must narrow to the culprit alone; a witness is added if that helps, and a case no evidence can solve is dropped without a word, the next crime waiting as if it had closed. A solvable case opens: its witnesses, residents the routine expected at the scene, are told what they saw, then the neighborhood app posts the news to the victim, their household and whoever is at the crime place, and the case shows at the top of the Hear panel. An open case goes cold after `case_days`.

Evidence is held by the game as records with ids like `r-12`, and the models never invent any of it:

| Kind | What it is |
|---|---|
| memory | a witness recalls a few of the culprit's traits, never a name, around the time of the crime |
| clip | a camera at the grocery, bar, town hall or elm street catches the culprit's height and coat at the exact minute |
| log | a gym check-in, bar tab, grocery receipt or library checkout puts a named resident somewhere that part of the day |
| statement | what a resident tells the podcaster in an interview |

## Interviews

Interview a resident where you both stand and the game, not the model, decides what they can give, adding anything new to your notebook under the case:

- a witness's memory record;
- where they say they were during the crime, a lie when they are the culprit;
- for a night crime, whether each housemate was home, which Jev decides the speaker covers for or not (the culprit gives no such word);
- the best line they heard that traces back to a witness's memory or the culprit's cover story, naming who told them.

Haiku phrases the answer from those facts alone, and a resident who knows nothing says so. Every interview tells the culprit, at most once a part of the day, that a podcaster is asking around. A resident whose regard for you has fallen below `guarded_at` won't talk to you; regard drifts back toward 0 by `reputation_decay` each part of the day.

Room talk that grows from a case's news or a witness's memory is posted to the app and shows in the feed with an App tag.

## How it uses Contex

| Feature | Where |
|---|---|
| `contex_publish` | every line a villager hears (one publish per listener), group records |
| `contex_create_subscription` | one per need (each villager has 3 to 5) on the villager's mind project, at that need's threshold |
| `max_age_seconds` | noticing: a subscription only carries talk from the last `memory_days`, for a villager to react to |
| `subscriptions/listen` | one stream per villager over all their subscriptions; a push is what wakes them |
| reading the subscription resource | the villager's memories each turn, and lease renewal for quiet villagers |
| `contex_query` | what a resident heard about the case, in an interview; calibrating needs |
| semantic matching | a line wakes a villager only if it scores clearly above ordinary village talk for one of their needs, and a rumor still reaches people after it is retold in other words |
| scale | 100 projects, about 400 subscriptions, and 100 listen streams at once |

A villager never hears their own words, so speaking never wakes the speaker.

## Setup

Optionally, start Contex with a 60-second reconcile sweep so quiet minds forget
sooner. The setting applies to the whole Contex server, and each sweep costs a
CPU burst: at a 30-second sweep with 100 villagers, the server used 4 to 5 CPU
cores for a few seconds each time. Without the override, forgetting is trimmed
whenever a villager takes a turn and every 300 seconds otherwise. From a
[Contex](https://github.com/cahoots-org/contex) checkout with this repo beside it:

```bash
docker compose -f docker-compose.yml -f ../contex-games/sleuth/compose.sweep.yaml up
```

Install the game's dependencies (Python 3.12) and set the two API keys, either
exported or in a `.env` file (the game reads the nearest one; exported values win):

```bash
pip install -r sleuth/requirements.txt
export ANTHROPIC_API_KEY=...
export TYPESAFE_API_KEY=...
```

Run it from the repo root and open the address it prints, `http://127.0.0.1:8765` unless `SLEUTH_WEB_PORT` says
otherwise:

```bash
python -m sleuth
```

The game is played in the browser only; `--web` is still accepted and changes nothing.

Each run asks Haiku for a new village in batches of 10, every villager with a
first name of their own, and saves it as `sleuth_worlds/<session>.json`;
the game prints the path. Set `SLEUTH_SEED_PATH` to that file to play the
same village again (the model can't reproduce a village from a seed, so the
file is the record). Most villagers are good-natured; about one in five is sour
and holds a grudge, and those are the village's skeptics, quick to doubt or mock
a rumor. If a saved village's size differs from `SLEUTH_POPULATION` the game
exits and says so. Each run starts with empty minds unless you set `SLEUTH_SESSION`.

On the machine this was tuned on, a 100-villager game took 5.5 seconds to
start from the seed file, and the game process used 125 MB of memory and
6 seconds of CPU over a 400-second session. The Contex server held 100 listen
connections and used 4 to 5 CPU cores for a few seconds at each 30-second
sweep; the override uses 60 seconds.

## How a line wakes a villager

The embedding model gives almost any two village sentences a similarity
between about 0.72 and 0.82, related or not, and each need sits at its own
level within that band. So each need gets a baseline: its mean similarity to
20 ordinary sentences (weather, chores, prices, a repainted parking lot) that concern no
one. A line matches a need when it scores at least `SLEUTH_MATCH_MARGIN`
(0.015) above that need's baseline. Each need's subscription uses that
threshold, so Contex pushes only real matches.

The first run computes the baselines and writes them to
`sleuth_baselines.json`, shared by every village; for 400 needs that took 5.4 seconds on
the machine this was tuned on. Later runs read the file. Baselines are kept by
need text and by the exact payload the calibration sentences were published
in, and are recomputed when either changes. They depend on Contex's embedding
model, so delete `sleuth_baselines.json` after changing it.

Contex embeds every field of what is published, including the data key, so
the game publishes only an utterance's id and its sentence. The key alone
still moves a score by up to about 0.02, so a whisper that sits right at the
margin can land under one id and miss under another.

The margin was tuned on the 100-villager seed with 20 whispers written from
villagers' cards before reading their needs, half aimed at a trade and grudge
and half unrelated, each published four times with random ids and places.
These figures and the retold-line figure below were measured while the place
was still part of the published text, and are due to be re-measured:

| Margin | Aimed whispers that land | Unrelated whispers that land |
|---|---|---|
| 0.0175 | 100% | 36% |
| 0.02 | 96% | 26% |
| 0.025 | 90% | 16% |
| 0.03 | 82% | 5% |

The default is 0.015, a little below the lowest measured margin: in play,
aimed whispers kept missing a fitting need by less than 0.005, which felt like
a hit that didn't count. Expect more unrelated whispers to land than at 0.0175.

A line someone retells ("Bert said: ...") matches a little more
easily than a whisper: at 0.02, 42% of the unrelated lines matched a need of
whoever heard them retold (measured with the place in the text). A lower margin makes the village talk more, and a
higher one makes more of your aimed whispers miss.

Run Contex with authentication off, since its rate limits would throttle
calibration and every question, and with `SYSTEM_ONE_ENABLED`
off, since query reranking would call a model on every check. Both are off by
default.

## Commands

Everything is done on the page:

- Walk: open a place's tile and press "Walk here".
- Look around: at your own place, press "Look around" to see the last few lines said there.
- Interview: open a villager's card where you stand and press "Interview"; the answer goes in the feed and on their
  card, and any new evidence in the notebook under the case.
- Inspect: click a face to see a villager's trade, looks, home, household, personality, grudge and relationships.

## The browser page

The page has the feed and the village in the sidebar.

The town is one tile per place (nine public places and three streets), each with how many villagers are there and
their faces. One tile is open at a time and lists everyone there: face, name,
trade, what you know about them, and the last thing they told you.
The page remembers which tile you opened. The search box above the tiles finds
villagers by name, trade, or place: it highlights matching faces and opens the
place where the best match is. Escape clears it.

Click a face, or press Enter on a name, to open the villager's card: occupation,
personality, grudge if they have one, relationships, and what you know. Escape closes the card.

A face is generated from the villager's id and trade, so the same villager has
the same face every game.

Room talk that grows from a case is posted to the neighborhood app and shows in
the feed. Look around a place to see the last few lines said there.

Arrow keys move through the feed's buttons. Reloading the page brings back the
last 500 feed events.

The server listens on 127.0.0.1 only. It answers only requests addressed to
`127.0.0.1` or `localhost` on its own port, and refuses writes and WebSocket
connections from other origins.

## What it costs

The game keeps a running count of the tokens it sends to Haiku and Jev and
multiplies them by per-million-token prices. The browser page shows it in the
menu, and the game prints it on quit. The figures are estimates: the prices are list prices you can
change, and the providers' bills are the real numbers.

Where the tokens go:

- Setup: Haiku writes each new village, and each newcomer who arrives after someone leaves.
- Each time a villager wakes: one Jev request to decide what they do, plus a
  short Haiku call (at most 80 tokens out) when they speak, and a slightly
  longer one when they found a group.
- Each interview: one short Haiku line, plus one Jev request per housemate for a night crime.

| Variable | Default (dollars per million tokens) |
|---|---|
| `SLEUTH_HAIKU_INPUT_PER_MTOK` | `0.1` |
| `SLEUTH_HAIKU_OUTPUT_PER_MTOK` | `0.5` |
| `SLEUTH_JEV_INPUT_PER_MTOK` | `0.04` |
| `SLEUTH_JEV_OUTPUT_PER_MTOK` | `0.0` |

## Hosting

`sleuth/Dockerfile` builds the web game from the repo root. On
Railway, create a service from this repo and set its Dockerfile path to
`sleuth/Dockerfile`, its health check to `/healthz` with a 600-second
timeout (the server starts only once the village is written), and its restart
policy to on-failure with at most 3 retries. Then set:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `TYPESAFE_API_KEY` | your TypeSafe key |
| `SLEUTH_CONTEX_URL` | the `contex` service's private URL with `/mcp`, such as `http://contex.railway.internal:8001/mcp` |
| `SLEUTH_DAILY_SPEND_CAP` | the most you will spend a day, in dollars (default `5`) |

The image listens on `0.0.0.0` and on the `PORT` Railway gives it.

The village thinks only while someone is playing: a player counts while one of
their tabs is open, and for `SLEUTH_IDLE_AFTER_SECONDS` (10 minutes) after
their last walk, interview, look around or closed tab.
A visitor who loads the page but never opens its feed never wakes the village,
and their run is dropped once it is that old, or sooner once more than
`SLEUTH_MAX_IDLE_RUNS` such runs pile up. A single open tab keeps the village
awake, so expect it to spend up to the cap every UTC day.

Once the day's estimated spend reaches `SLEUTH_DAILY_SPEND_CAP` the village
rests until midnight UTC: villagers stop thinking, the page says so, and
interviews are refused. Walking and looking around still
work. Calls already under way finish, so the day can go a little over the cap.

The cap counts spend in the running process only. A restart starts the count
again, and each start also pays Haiku to write a new village, so the worst case
is about the cap per UTC day for each start. With the restart policy above, Railway
restarts a crashed game at most 3 times, which bounds a crash loop.

To keep the village across restarts, mount a volume at `/data` and set
`SLEUTH_DATA_DIR=/data` and a fixed `SLEUTH_SESSION` (such as `village`).
The village, its places, and the need baselines then live on the
volume, and a start with the same session loads the saved village instead of
writing a new one. The image's entrypoint runs as root only to give the `sleuth`
user the volume, then drops to it. Set deployment overlap to 0, so two copies
never drive the same villagers, and draining to 30 seconds.

With a fixed `SLEUTH_SESSION`, the game itself is saved to
`sleuth_worlds/<session>.state.json` every `SLEUTH_SAVE_EVERY_SECONDS` and
once on SIGTERM or Ctrl-C, and a start with the same session restores it: every
run and the feed a reload replays. A save that is
unreadable, for another version or session, fails to restore, or has lost its
village file is renamed to `<name>.bad-<time>` and the game starts fresh.

To count players, search the logs for `analytics`. The game prints one line when a run first opens its feed
(`analytics visit`) and one when a run ends (`analytics end`, with its outcome). Each carries the player's anonymous
`owner` id, so distinct owners in `analytics visit` lines are the people who came.

## Settings

Every field of `Config` can be set with an environment variable.

| Variable | Default | Meaning |
|---|---|---|
| `SLEUTH_CONTEX_URL` (or `CONTEX_MCP_URL`) | `http://localhost:8001/mcp` | Contex MCP endpoint |
| `SLEUTH_SESSION` | random per run | prefix for this run's Contex projects; with a fixed value, the village saved under it is loaded again |
| `SLEUTH_DATA_DIR` | working directory | where villages and need baselines are kept; `/data` when hosted |
| `SLEUTH_SAVE_EVERY_SECONDS` | `60` | how often the running game is saved |
| `SLEUTH_POPULATION` | `50` | village size; newcomers arrive to keep it there |
| `SLEUTH_CRIME_EVERY_DAYS` | `1` | game days from one shared case's close to the next crime |
| `SLEUTH_CASE_DAYS` | `3` | game days before an open case goes cold |
| `SLEUTH_GUARDED_AT` | `-0.3` | below this regard a resident won't talk to you |
| `SLEUTH_REPUTATION_DECAY` | `0.02` | how far each resident's regard for you drifts back toward 0 each part of the day |
| `SLEUTH_DAY_SECONDS` | `120` | length of a game day |
| `SLEUTH_MEMORY_DAYS` | `2` | how many days a villager remembers what they heard |
| `SLEUTH_MATCH_MARGIN` | `0.015` | how far above a need's score against ordinary village talk a line must score to match that need |
| `SLEUTH_TOP_K` | `5` | memories kept per need |
| `SLEUTH_CALIBRATION_PATH` | `sleuth_baselines.json` | where need baselines are cached |
| `SLEUTH_FATIGUE_PER_HOP` | `0.004` | extra clearance over a need's threshold each retelling hop needs before it wakes a listener |
| `SLEUTH_OVERHEARD_MARGIN` | `0.01` | extra clearance a line said to the room needs over one told to the listener |
| `SLEUTH_COOLDOWN_SECONDS` | `30` | least time between a villager's turns |
| `SLEUTH_JUDGE_CONCURRENCY` | `10` | routine-planning calls in flight |
| `SLEUTH_TURN_CONCURRENCY` | `20` | villager turns in flight |
| `SLEUTH_RENEW_SECONDS` | `1200` | read quiet villagers' subscriptions this often so they don't expire |
| `SLEUTH_HAIKU_MODEL` | `claude-haiku-5-5` | model for speech and village generation |
| `SLEUTH_SEED_PATH` | empty: a new village | a saved village to play again |
| `SLEUTH_WEB_HOST` | `127.0.0.1` | address the game listens on; `0.0.0.0` serves anyone who can reach the machine |
| `SLEUTH_WEB_PORT` | `8765` | port the game listens on; `PORT` wins when set |
| `SLEUTH_IDLE_AFTER_SECONDS` | `600` | how long a player counts as playing after their last action or closed tab |
| `SLEUTH_MAX_IDLE_RUNS` | `200` | most runs kept that never played; past it the oldest are dropped |
| `SLEUTH_DAILY_SPEND_CAP` | `5.0` | estimated dollars per UTC day before the village rests until midnight; `0` for no cap |

`MATCH_MARGIN` matters most; see [How a line wakes a villager](#how-a-line-wakes-a-villager). Lower it and villagers react to more of what they hear; raise it and the village goes quiet.

Stories wear out. A line wakes a listener only if it clears one of their
needs by `FATIGUE_PER_HOP` for each time it was retold, plus
`OVERHEARD_MARGIN` when it was said to the room. Before these, one whisper
at the tavern on the 100-villager seed set its 15 villagers trading about a
hundred insults in a few minutes: a line said to the room cleared the needs
of 6 to 9 of them. With the defaults, replays of that whisper gave 1 to 4
retellings, each over within a minute, and the village stayed quiet. Raise
the fatigue for a quieter village; lower the overheard margin and room talk
runs on.

## Tests

```bash
pip install -r requirements-dev.txt
pytest sleuth
SLEUTH_CONTEX_URL=http://localhost:8001/mcp pytest sleuth
```

The second run adds the tests that need a live Contex.
