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

Room talk that grows from a case's news or a witness's memory is posted to the app and shows in the feed with an App tag.

## How it uses Contex

| Feature | Where |
|---|---|
| `contex_publish` | every line a villager hears (one publish per listener), whispers, group records |
| `contex_create_subscription` | one per need (each villager has 3 to 5) on the villager's mind project, at that need's threshold |
| `max_age_seconds` | noticing: a subscription only carries talk from the last `memory_days`, for a villager to react to |
| `since` | forgetting: a villager recalls only lines heard since your last `memory_moves` moves |
| `subscriptions/listen` | one stream per villager over all their subscriptions; a push is what wakes them |
| reading the subscription resource | the villager's memories each turn, and lease renewal for quiet villagers |
| `contex_query` | the check right after a whisper of whether it matched the target's needs; calibrating needs |
| semantic matching | a whisper wakes a villager only if it scores clearly above ordinary village talk for one of their needs, and a rumor still reaches people after it is retold in other words |
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

Run it from the repo root:

```bash
python -m sleuth
```

To play in a browser instead, add `--web` and open the address it prints,
`http://127.0.0.1:8765` unless `SLEUTH_WEB_PORT` says otherwise:

```bash
python -m sleuth --web
```

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

## How a whisper lands

The embedding model gives almost any two village sentences a similarity
between about 0.72 and 0.82, related or not, and each need sits at its own
level within that band. So each need gets a baseline: its mean similarity to
20 ordinary sentences (weather, chores, prices, a repainted parking lot) that concern no
one. A line matches a need when it scores at least `SLEUTH_MATCH_MARGIN`
(0.015) above that need's baseline. Each need's subscription uses that
threshold, so Contex pushes only real matches.

Right after you whisper, the game queries each of the target's needs for your
whisper, one query per need and no model call, which is how the feed can say
at once whether it landed. A whisper that lands joins the villager's next turn
even if the push is slow.

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
calibration and the check after each whisper, and with `SYSTEM_ONE_ENABLED`
off, since query reranking would call a model on every check. Both are off by
default.

## Commands

In the terminal:

```
<name>: <text>            whisper to a villager, e.g. Marta: the miller waters his flour
whisper <name>: <text>    the same
villagers                 everyone in town, with occupation and place
inspect <name>            personality, any grudge, and relationships
usage                     tokens used so far and their estimated cost
help                      these commands
quit
```

A name can be part of a full name if it is unambiguous. A whisper that
touches nothing the villager cares about does nothing, and the feed says at
once whether it caught their ear or they shrug it off. `inspect` shows enough
to guess what someone cares about, but not their needs.

A shrug is a hint. The villager brushes you off in their own voice, kindly or
curtly as their temperament goes, and alludes to something they care about, a
different concern each time until they run out and start over, so a miss tells
you where to aim next. If the line can't be
written, the whisper just says it was brushed off.

## Suspicion

Each villager keeps their own suspicion of the newcomer. It goes up when:

- you whisper to them: every whisper tells them it came from you;
- they hear a line that names the newcomer: only a faithful retelling of your
  whisper keeps your part in it, so talk that has drifted from it never does;
- someone warns them about you.

A villager who suspects you enough may warn someone else about you. The feed
shows that a warning happened ("Bert Cole warned Marta Hale about you."), but
not what was said. A villager who suspects you strongly turns you away: your
whisper doesn't reach them, and trying again makes them more suspicious.

Suspicion fades a little each day. The village's mood is a mean of everyone's
suspicion in which the mayor counts for more. You see it as one of four lines at the top of the
browser page:

| Label | What it says |
|---|---|
| quiet | Folk are not talking about you. |
| murmurs | There are murmurs. |
| watched | Folk are watching you. |
| hunted | The village is hunting for you. |

The village checks its mood four times a game day. If it is at the run-out
level for three checks in a row, the town meets at town hall and runs you
out of town, and you lose. The summary says what gave you away, such as "Marta
Hale heard it from you directly." The game is over: whispers are refused, and
you restart the program to play again.

## The browser page

The page has the feed, a whisper box, and the village in the sidebar.

The town is one tile per place (nine public places and three streets), each with how many villagers are there and
their faces. One tile is open at a time and lists everyone there: face, name,
trade, what you know about them, and the last line they brushed you off with.
The page remembers which tile you opened. The search box above the tiles finds
villagers by name, trade, or place: it highlights matching faces and opens the
place where the best match is. Escape clears it. The whisper box offers the
same matches as you type; arrow keys and Enter pick one.

Click a face, or press Enter on a name, to open the villager's card: occupation,
personality, grudge if they have one, relationships, and what you know. "Whisper to" fills the
whisper box with their name. Escape closes the card.

A face is generated from the villager's id and trade, so the same villager has
the same face every game. A badge on the face says what you know:

| Badge | Means |
|---|---|
| ✓ | took the bait: passed your whisper on |
| ↩ | answered you: you are talking with them |
| ○ | kept it quiet: heard you and told no one |
| – | brushed you off: your whisper missed what they care about |
| ! | wary of you: turned you away or warned others about you |
| … | listening: you whispered to them and nothing has come of it yet |

The open tile and the card say the same in words. Each whisper in the feed
shows where it stands, updated as it changes: checking, busy (with the seconds
until they hear you), heard, took the bait (and how many people they told),
kept it quiet, warned others, answered you, moved on, brushed you off (with
their line once it is written), or didn't carry (the game couldn't check it).

A villager whose interest you caught may answer you. The conversation shows
above the composer: your lines and theirs. While they are talking with you, the composer
says "Talking with" their name, and what you send them next is a reply. The
conversation ends when they move on, brush you off, turn you away, or the game
ends.

Room talk that grows from a case is posted to the neighborhood app and shows in
the feed. Listen at a place to hear the last few lines said there.

Arrow keys move through the feed's buttons. Reloading the page brings back the
last 500 feed events.

The server listens on 127.0.0.1 only. It answers only requests addressed to
`127.0.0.1` or `localhost` on its own port, and refuses whispers and WebSocket
connections from other origins.

## What it costs

The game keeps a running count of the tokens it sends to Haiku and Jev and
multiplies them by per-million-token prices. `usage` prints it in the
terminal, the browser page shows it in the strip above the feed, and both
print it on quit. The figures are estimates: the prices are list prices you can
change, and the providers' bills are the real numbers.

Where the tokens go:

- Setup: Haiku writes each new village, and each newcomer who arrives after someone leaves.
- Each time a villager wakes: one Jev request to decide what they do, plus a
  short Haiku call (at most 80 tokens out) when they speak, and a slightly
  longer one when they found a group.
- Each shrug: one short Haiku call (at most 80 tokens out) for the brush-off,
  and a second one if the first repeated the villager's concern word for word.
- An answer to you: the turn's Jev request plus one short Haiku line, at
  most `TALK_TURNS` per conversation.

On the 100-villager seed with the defaults, the haunting
whisper and the talk it started cost about $0.002 in five minutes; four
whispers and a three-reply conversation, under $0.004.

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
their last whisper, walk, question, listen, keystroke or closed tab.
A visitor who loads the page but never opens its feed never wakes the village,
and their run is dropped once it is that old, or sooner once more than
`SLEUTH_MAX_IDLE_RUNS` such runs pile up. A single open tab keeps the village
awake, so expect it to spend up to the cap every UTC day.

Once the day's estimated spend reaches `SLEUTH_DAILY_SPEND_CAP` the village
rests until midnight UTC: villagers stop thinking, the page says so, and
whispers and questions are refused. Walking and listening still
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
(`analytics visit`), one per whisper (`analytics whisper`), and one when a run ends (`analytics end`, with its
outcome). Each carries the player's anonymous `owner` id, so distinct owners in `analytics whisper`
lines are the people who played.

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
| `SLEUTH_DAY_SECONDS` | `120` | length of a game day |
| `SLEUTH_MEMORY_DAYS` | `2` | how many days a villager remembers what they heard |
| `SLEUTH_MATCH_MARGIN` | `0.015` | how far above a need's score against ordinary village talk a whisper must score to match that need |
| `SLEUTH_TOP_K` | `5` | memories kept per need |
| `SLEUTH_CALIBRATION_PATH` | `sleuth_baselines.json` | where need baselines are cached |
| `SLEUTH_FATIGUE_PER_HOP` | `0.004` | extra clearance over a need's threshold each retelling hop needs before it wakes a listener |
| `SLEUTH_OVERHEARD_MARGIN` | `0.01` | extra clearance a line said to the room needs over one told to the listener |
| `SLEUTH_SAID_FLOOR` | `0.8` | how similar a villager's earlier line must be to what you say to them for them to recall it |
| `SLEUTH_TALK_TURNS` | `3` | most times a villager answers you in one conversation |
| `SLEUTH_COOLDOWN_SECONDS` | `30` | least time between a villager's turns |
| `SLEUTH_CHECK_LOOKBACK_SECONDS` | `5` | how far before a whisper the check that it landed looks, to absorb clock skew with Contex |
| `SLEUTH_JUDGE_CONCURRENCY` | `10` | routine-planning calls in flight |
| `SLEUTH_TURN_CONCURRENCY` | `20` | villager turns in flight |
| `SLEUTH_RENEW_SECONDS` | `1200` | read quiet villagers' subscriptions this often so they don't expire |
| `SLEUTH_HAIKU_MODEL` | `claude-haiku-5-5` | model for speech and village generation |
| `SLEUTH_SEED_PATH` | empty: a new village | a saved village to play again |
| `SLEUTH_WEB_HOST` | `127.0.0.1` | address `--web` listens on; `0.0.0.0` serves anyone who can reach the machine |
| `SLEUTH_WEB_PORT` | `8765` | port for `--web`; `PORT` wins when set |
| `SLEUTH_IDLE_AFTER_SECONDS` | `600` | how long a player counts as playing after their last action or closed tab |
| `SLEUTH_MAX_IDLE_RUNS` | `200` | most runs kept that never played; past it the oldest are dropped |
| `SLEUTH_DAILY_SPEND_CAP` | `5.0` | estimated dollars per UTC day before the village rests until midnight; `0` for no cap |
| `SLEUTH_SUSPICION_WHISPER_BUMP` | `0.12` | suspicion a whisper adds to the villager you whisper to |
| `SLEUTH_SUSPICION_HEAR_MAX` | `0.25` | most suspicion one rumor about the newcomer can add |
| `SLEUTH_SUSPICION_DECAY_PER_DAY` | `0.05` | suspicion each villager loses per game day |
| `SLEUTH_WARN_THRESHOLD` | `0.3` | suspicion at which a villager may warn others |
| `SLEUTH_REFUSE_THRESHOLD` | `0.7` | suspicion at which a villager turns you away |
| `SLEUTH_RUN_OUT_LEVEL` | `0.08` | village mood at which the run-out checks start counting |
| `SLEUTH_RUN_OUT_CHECKS` | `3` | checks in a row at that level before you are run out |
| `SLEUTH_SUSPICION_CHECK_DAYS` | `0.25` | game days between mood checks |

`MATCH_MARGIN` matters most; see [How a whisper lands](#how-a-whisper-lands). Lower it and villagers react to more of what they hear; raise it and the village goes quiet.

Stories wear out. A line wakes a listener only if it clears one of their
needs by `FATIGUE_PER_HOP` for each time it was retold, plus
`OVERHEARD_MARGIN` when it was said to the room. Before these, one whisper
at the tavern on the 100-villager seed set its 15 villagers trading about a
hundred insults in a few minutes: a line said to the room cleared the needs
of 6 to 9 of them. With the defaults, replays of that whisper gave 1 to 4
retellings, each over within a minute, and the village stayed quiet. Raise
the fatigue for a quieter village; lower the overheard margin and room talk
runs on.

A conversation costs suspicion like whispering does. Three messages to one
villager left them at about 0.73, past the 0.7 at which they turn you away,
which is why `TALK_TURNS` is 3.

The mood is a mean over the whole village, so the same whispers count for more
in a small one. In a village of 100, a player who whispered to someone
every few seconds was run out on the fourth game day, while one who picked a
dozen villagers whose worries matched stayed at quiet or murmurs. In a village
of 30, eight well-aimed whispers reached watched.

## Tests

```bash
pip install -r requirements-dev.txt
pytest sleuth
SLEUTH_CONTEX_URL=http://localhost:8001/mcp pytest sleuth
```

The second run adds the tests that need a live Contex.
