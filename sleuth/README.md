# Sleuth

A small-town deduction game on Contex. You are a true-crime podcaster: a petty crime happens, you gather evidence
from residents, footage and logs, and you publish an episode naming who did it. Code, not a model, judges the episode.
The design is in [docs/superpowers/specs/2026-10-25-sleuth-design.md](../docs/superpowers/specs/2026-10-25-sleuth-design.md).

## The town

The public places are the cafe, gym, school, bar, dog park, hardware store, grocery, town hall and library.
Households live on elm, oak or maple street, and each street is one place. Jev picks each resident's work place and
evening place once; the day runs work, work, leisure, then home on their street at night. Each resident has a few
visible traits (height, hair, coat and so on) drawn by code from a fixed list.

Residents still talk among themselves: what they hear is published into their minds in Contex, and a line that
matches one of their needs wakes them to react. What a witness saw or a victim found passes only from mind to mind:
neither the feed nor a look around shows it, so you learn it only by interviewing someone.

## Playing

**A case.** While someone is playing and no shared case is open, a crime is staged, `crime_every_days` after the last
shared case closed. The culprit comes from another household than the victim's, and one or two clues are left at
the crime place. At the next part of the day the game checks that the evidence narrows to the culprit alone, adding a
witness if that helps and dropping the case quietly if nothing can. A solvable case opens: its witnesses are told what they saw, and the neighborhood app posts the news. The
case shows at the top of the Hear panel and goes cold after `case_days`.

**Your first case.** A new podcaster gets an easy private case of their own, opened at once at a place with a
camera: one witness, a clip showing the culprit's height, coat and hair, a clue or two at the scene, and no logs but a receipt's. Only
they see its news. Short hints walk them through interviewing, pulling records, searching the scene and publishing;
once it closes, by an episode or by going cold, they play the town's shared case like everyone else. No new private case is opened while the town is
resting.

**Evidence** is held by the game as records with ids like `r-12`; the models never invent any of it.

| Kind | What it is |
|---|---|
| memory | a witness recalls a few of the culprit's traits, never a name |
| clip | a camera at the grocery, bar, town hall or elm street catches the culprit's height and coat at the exact minute |
| log | a gym check-in, bar tab, grocery receipt or library checkout puts a named resident somewhere; a dropped receipt's time is matched by the grocery's log, which names who paid |
| clue | left at the crime place: a boot print, coat thread or tracks showing one of the culprit's traits, or a grocery receipt dropped by the culprit or someone who was there, showing only the store and the time |
| statement | what a resident tells you in an interview: where they or someone else were, what they heard, who'd have a reason |

Statements can be lies: the culprit gives a false alibi, and a housemate may cover for them.

**Interview** any resident from wherever you are (it's a modern town: you call or message them) by asking a question
in your own words, like "Where were you last night?". Each resident keeps one conversation with you, which you can
reopen from their card. Jev reads the question
with the conversation so far and routes it to where the resident was, where someone else was, what they saw, who
they heard something from, who'd have a reason (a feud or grudge with the victim), or what they think of someone.
The game answers from what that resident knows and adds anything new to your notebook; Haiku only phrases the
reply. A question the game can't answer, or one the resident knows nothing about, gets "I wouldn't know about that."
You can ask each resident 4 questions a part of the day, then they'd rather talk later. Every question tells the
culprit, at most once a part of the day, that a podcaster is asking around, and they may start covering their tracks. Once pressed, the culprit may also warn
someone they're close to that the podcaster is stirring up trouble, at most once a part of the day per case: that
resident thinks less of the podcaster who last asked around (`reputation_warned`), and the warning spreads like any
other line. You only hear that someone in town seems colder toward you.

Walking still matters for the scene and the records: you search a place and pull its records only while you're there.

**Pull records** at a place to copy the case's footage and logs there into your notebook. A place's records are
kept by the residents who work there, or for a street by those who live on it; they're shared unless every keeper
regards you below `guarded_at`.

**Search** the crime place, once per case, to find the one or two clues left there when the crime was staged.
A receipt names no one: pull the grocery's records to see who paid at that time. The solvability check counts the
clues and that log, so a case may need a search and a pull to crack.

**Publish** an episode: choose a resident and tick between 1 and 5 notebook entries. It holds up when it names the
culprit, every cited entry is true evidence from this case, and at least one points at the culprit: a memory, clip
or trace whose traits all fit them, or a log that puts them at the crime place or behind a receipt found there. Otherwise the evidence
doesn't back it. One episode per podcaster per case.

- A right episode closes the case for everyone, and every resident thinks better of you (`reputation_right`). Any
  other podcaster with evidence from that case is told another podcaster cracked it first.
- A wrong one leaves the case open for others. The town hears the accusation anyway, everyone thinks less of you
  (`reputation_wrong`), and the accused most of all (`reputation_accused`).

**Reputation** is each resident's regard for you, in [-1, 1], drifting back toward 0 by `reputation_decay` each part
of the day. A resident below `guarded_at` won't talk to you or share the records they keep. A witness at or above
`trusted_at` recalls one more of the culprit's traits in an interview, a fuller memory that goes in your notebook as
a new entry.

Everything is done on the page: open a place's tile to walk there or look around, open a resident's card to talk with
them, and use the case panel to pull records, search the crime place and publish. Click a face to see a resident's trade, looks, home and
household.

## How it uses Contex

| Feature | Where |
|---|---|
| `contex_publish` | every line a resident hears (one publish per listener), witness memories, the app's news, episodes |
| `contex_create_subscription` | one per need on the resident's mind project, at that need's threshold |
| `max_age_seconds` | a subscription only carries talk from the last `memory_days` |
| `subscriptions/listen` | one stream per resident over all their subscriptions; a push wakes them |
| `contex_query` | what a resident heard about the case, in an interview; calibrating needs |

A line matches a need when it scores at least `match_margin` above that need's baseline, its mean similarity to
ordinary sentences that concern no one. Baselines are cached in `sleuth_baselines.json`; delete it after changing
Contex's embedding model. Run Contex with authentication and `SYSTEM_ONE_ENABLED` off (the defaults).

## Setup

Install the dependencies (Python 3.12) and set the two API keys, exported or in a `.env` file:

```bash
pip install -r sleuth/requirements.txt
export ANTHROPIC_API_KEY=...
export TYPESAFE_API_KEY=...
python -m sleuth
```

Open the address it prints, `http://127.0.0.1:8765` unless `SLEUTH_WEB_PORT` says otherwise. Each run asks Haiku for
a new town and saves it as `sleuth_worlds/<session>.json`; set `SLEUTH_SEED_PATH` to that file to play it again.

## What it costs

The game counts the tokens it sends to Haiku and Jev and multiplies them by list prices you can change; the page shows
your share in the menu. Haiku writes each new town, phrases what residents say and each interview reply. Jev decides
what a woken resident does, plans routines, and routes each interview question. A question costs at most one call to
each.

Once the day's estimated spend reaches `SLEUTH_DAILY_SPEND_CAP` the town rests until midnight UTC: residents stop
thinking, and interviews, pulls and episodes are refused. Walking and looking around still work.

## Hosting

`sleuth/Dockerfile` builds the game from the repo root. On Railway, set the Dockerfile path to `sleuth/Dockerfile`,
the health check to `/healthz` with a 600-second timeout, and the restart policy to on-failure with at most 3 retries.
Set `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`, `SLEUTH_CONTEX_URL` (the Contex service's private URL with `/mcp`) and
`SLEUTH_DAILY_SPEND_CAP`. The image listens on `0.0.0.0` and on `PORT`.

To keep the town across restarts, mount a volume at `/data` and set `SLEUTH_DATA_DIR=/data` and a fixed
`SLEUTH_SESSION`. The game is then saved every `SLEUTH_SAVE_EVERY_SECONDS` and on shutdown, and restored on start; a
save it can't use is renamed to `<name>.bad-<time>`. Set deployment overlap to 0.

The town thinks only while someone is playing: while one of their tabs is open, and for `SLEUTH_IDLE_AFTER_SECONDS`
after their last action. To count players, search the logs for `analytics visit`; each line carries the player's
anonymous `owner` id.

## Settings

Every field of `Config` can be set as `SLEUTH_<FIELD>`.

| Variable | Default | Meaning |
|---|---|---|
| `SLEUTH_CONTEX_URL` (or `CONTEX_MCP_URL`) | `http://localhost:8001/mcp` | Contex MCP endpoint |
| `SLEUTH_SESSION` | random per run | prefix for this run's Contex projects and saves |
| `SLEUTH_DATA_DIR` | working directory | where towns, saves and baselines are kept |
| `SLEUTH_POPULATION` | `50` | town size |
| `SLEUTH_DAY_SECONDS` | `180` | length of a game day |
| `SLEUTH_CRIME_EVERY_DAYS` | `1` | game days from one shared case's close to the next crime |
| `SLEUTH_CASE_DAYS` | `3` | game days before an open case goes cold |
| `SLEUTH_REPUTATION_RIGHT` | `0.3` | regard every resident gains for a right episode |
| `SLEUTH_REPUTATION_WRONG` | `-0.4` | regard every resident loses for a wrong episode |
| `SLEUTH_REPUTATION_ACCUSED` | `-0.4` | further regard the wrongly accused loses |
| `SLEUTH_REPUTATION_WARNED` | `-0.2` | regard a resident loses when the culprit warns them about you |
| `SLEUTH_REPUTATION_DECAY` | `0.02` | how far regard drifts back toward 0 each part of the day |
| `SLEUTH_GUARDED_AT` | `-0.3` | below this regard a resident won't talk to you or share records |
| `SLEUTH_TRUSTED_AT` | `0.2` | at or above this regard a witness recalls one more of the culprit's traits |
| `SLEUTH_LISTEN_SECONDS` | `20` | how long one look around lasts |
| `SLEUTH_MEMORY_DAYS` | `2` | how many days a resident keeps what they heard to react to |
| `SLEUTH_MATCH_MARGIN` | `0.015` | how far above a need's baseline a line must score to match it |
| `SLEUTH_COOLDOWN_SECONDS` | `30` | least time between a resident's turns |
| `SLEUTH_ROUTINE_CONCURRENCY` | `10` | routine questions Jev is asked at once |
| `SLEUTH_TURN_CONCURRENCY` | `20` | resident turns in flight |
| `SLEUTH_HAIKU_MODEL` | `claude-haiku-5-5` | model for speech and town generation |
| `SLEUTH_SEED_PATH` | empty: a new town | a saved town to play again |
| `SLEUTH_WEB_HOST` | `127.0.0.1` | address the game listens on |
| `SLEUTH_WEB_PORT` | `8765` | port the game listens on; `PORT` wins when set |
| `SLEUTH_IDLE_AFTER_SECONDS` | `600` | how long a player counts as playing after their last action |
| `SLEUTH_MAX_IDLE_RUNS` | `200` | most runs kept that never played |
| `SLEUTH_DAILY_SPEND_CAP` | `5.0` | estimated dollars per UTC day before the town rests; `0` for no cap |

## Tests

```bash
pip install -r requirements-dev.txt
pytest sleuth
SLEUTH_CONTEX_URL=http://localhost:8001/mcp pytest sleuth
```

The second run adds the tests that need a live Contex.
