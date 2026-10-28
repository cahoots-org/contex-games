# Sleuth

A small-town deduction game on Contex. You are a true-crime podcaster: a petty crime happens, you gather evidence
from residents, footage and logs, and you publish an episode naming who did it. Code, not a model, judges the episode.
The design is in [docs/superpowers/specs/2026-10-25-sleuth-design.md](../docs/superpowers/specs/2026-10-25-sleuth-design.md).

## The town

The public places are the cafe, gym, school, bar, dog park, hardware store, grocery, town hall and library.
Households live on elm, oak or maple street, and each street is one place. Jev picks each resident's work place and
evening place once; the day runs work, work, leisure, then home on their street at night. Each resident has a fixed
height, hair and car, drawn by code from a fixed list, plus three outfits. The game picks one outfit for each resident
each day and records it for a few days; a culprit with an open case stays out of their crime outfit. Each resident
also has one or two quirks, a harmless obsession or habit that shows in what they say.

Residents still talk among themselves: what they hear is published into their minds in Contex, and a line that
matches one of their needs wakes them to react. What a witness saw or a victim found passes only from mind to mind:
the feed doesn't show it, so you learn it only by interviewing someone. What residents pass on can change in the retelling: they may
embellish it however their manner says, but never claim they saw it themselves. A culprit's cover story or warning
never adds to what it says.

## Playing

**A case.** The town always has a petty case open, and a case of each bigger tier while someone playing has the
standing for it: one open case per tier at most. At startup, on each part of the day, and the moment a case is solved
or goes cold, each tier missing its case gets a crime staged in the part of the day just finished, opened in the same
step. Its culprit is an offender of that tier; when nobody holds the tier, the offender below it who has got away with
the most moves up, as long as someone is left below. You're offered every open case at or below your standing as a tip, listed under the case title,
and you work one at a time: the highest by default, or the one you pick. The case title and each tip say its tier:
Petty, Serious or Major. Interviews, records, searches, photos and
episodes all go to the case you're working. Crimes come from the catalog in `sleuth/case.py`. Petty ones: a stolen
bike, a vandalized car, sabotaged county-fair jam, a dog let out, salted sugar jars at the cafe, a moustache drawn on a
portrait at town hall, a goose made off with from the dog park, a pinched garden gnome. Serious ones: a till or cash
box robbed at a shop or the bar, a mugging on the street, at the dog park or the bar, a stolen car. Major ones: a
death in town, offstage, opened at most once every `major_every_days` and only one at a time. The culprit comes
from another household than the victim's, and one or two clues are left at the crime place. A petty crime has up to
two witnesses, and its culprit is sometimes a regular at the scene. A serious one has up to three, its culprit is
never a regular there, so they always lie about where they were, and a mugging's victim remembers one thing about
the mugger. A death has up to two witnesses, who saw someone arguing; its victim is someone at least two residents
besides the culprit were on cold terms with, and anyone who knew the victim names them all when asked who had a
reason. Someone at the scene or at home with the victim found them, and the victim leaves town at once, so someone
moves in. Its news gives only a window, the part of the day before and the one it happened in, but every record is
from the one it happened in. Its news reaches everyone on the victim's street and everyone with a tie to them, and
the town talks about it soberly: residents are told someone has died and to say nothing of how, and any line with a
grisly word is never said or posted. With `accomplice_chance`, a serious culprit has an accomplice, their closest friend or another offender,
who is never a witness to it nor at the scene, and swears the culprit was with them. The game
checks that the evidence, with that part of the day's check-ins and receipts, narrows to the culprit alone, adding a
witness if that helps and drawing another crime if nothing can. A solvable case opens: its witnesses are told what
they saw, and the neighborhood app posts the news. A case shows at the top of the page and goes cold after
`case_days`, or `major_case_days` for a major one, when the town learns who did it: a petty culprit is exposed just as a right episode would expose them,
and any other is arrested, and any accomplice is exposed for covering for them.

**Offenders.** Only a few residents commit crimes: `offenders` of them, picked at random and topped back up whenever
the set falls below `min_offenders`. Nobody can see who they are, not the page, not the people list, not the other residents. They
don't make a case any easier or harder: the evidence still has to narrow to the culprit among everyone in town. An
offender who gets away with it `escalate_after` times moves up to a bigger kind of crime, once the catalog has one, unless they are the last offender at their tier.

**Moving in.** Nobody moves away by choice, but whenever someone leaves, on an arrest or a death, someone new moves in on
the same street, as long as the town is under `population`, one at a time and tried again each part of the day
until it works: a household of their own, a neighbor and one other tie,
a look nobody else has, three outfits and a routine. It costs one Haiku call (up to three when a reply is unusable)
and one Jev call, and the app says who moved in. They may or may not be an offender (`newcomer_offender_chance`, while there are fewer than
`max_offenders`). Witnesses are never drawn from another open case's culprits, so an arrest never takes testimony
with it, and notebook entries from someone who left still show their name.

**Districts.** Each street is a district with the public places nearest it: Elm Street has the cafe, bar and dog
park, Oak Street the gym, school and library, Maple Street the hardware store, grocery and town hall. Each district
keeps a crime level and a fear level between 0 and 1. A crime opened there raises both, by 0.25, 0.45 or 0.7 for a
petty, serious or major one; a held episode lowers crime by 0.15 and fear by 0.1. A case gone cold calms nothing.
Each part of the day crime fades by `district_crime_decay` and fear by `district_fear_decay`.

**Watches.** A district whose fear reaches `organize_fear` and that has seen at least one culprit exposed by a held
episode since it last organized starts a watch; a case gone cold never earns it one. It is the Elm Street
Neighborhood Watch, Porch-Light Pact or Group Chat, the name picked by code. It is checked the moment an episode holds and on every part of the day. The founder is the district's latest
victim if they live there, else a random resident, and up to five neighbors join, the ones the founder is warmest to,
whoever they are, so being in a watch proves nothing. The app announces it and the founder tells the members, with no
model calls. While a watch stands, a crime is `organized_crime_weight` times as likely at a place in its district, so
crime moves elsewhere. It winds down, said on the app, once the district's crime and fear both fall below
`disband_below`.

**How the districts connect.** Each morning a neglected district, one with no watch whose crime and fear are both at
least `neglect_at`, turns one of its residents who has never been exposed into a petty offender with `turn_chance`,
until the set reaches `max_offenders`. Whenever the set falls below `min_offenders`, it is refilled only from
districts without a watch. So a district left to itself breeds crime, while one that organizes pushes crime elsewhere
and breeds none. The app reacts at once, in code copy: a crime that raises a street's fear level leaves it "on edge after" the case,
and a held episode lets it breathe a little easier now the culprit's been found out. Residents feel their street: a district on edge or rattled, and whether a watch is on it, is in what
Jev and Haiku are told about them.

**Your first case.** Before the page, a new podcaster sees three short cards on what the game is and a button to
start; they come back on a reload only until the podcaster has asked anyone anything. The first case happens in a
practice town of its own (`sleuth/tutorial.py`), fixed in the code: six residents in three households, their looks,
ties and routines, and one staged case. Cal Hughes stole Ruth Okafor's tote bag at the library this morning. Tess
Moreno, who is usually at the library in the morning, saw someone tall and red-haired, which fits Cal and Gus. A thread
at the scene came from a green raincoat, which fits Cal and Ivy, so it takes the witness and the search together to
name Cal. The practice town's clock stands still, nobody there talks, hears or warns anyone, and regard there stays
apart from the real town's. Each question still costs at most one Jev call and one Haiku call.

A checklist in the case header walks the podcaster through it: ask the victim what happened, ask the witness what they
saw, ask the victim who they know that matches the sighting (only Cal), talk to Cal to see what he's wearing, search
the scene, and publish. Each step says why under it. The game ticks each step from what they have actually
done and lights the person or button the current step needs. The neighborhood app stays hidden and the notebook appears with its
first entry. Publishing, right or wrong (a wrong episode is told who it was), or Skip this case closes the
practice case and moves the podcaster into the real town: new people, a clean notebook and feed, and the town's open
case, which arrives as news under the verdict ("Meanwhile, on the neighborhood app: ..."). Nothing player-facing calls
any of this practice or a tutorial, and nothing from the practice town carries over. A podcaster mid-tutorial is
saved with the game and picks up where they left off.

**Evidence** is held by the game as records with ids like `r-12`; the models never invent any of it.

| Kind | What it is |
|---|---|
| memory | a witness recalls a few of the culprit's traits, never a name |
| clip | a camera at the grocery, bar, town hall or elm street catches the culprit's height and what they wore then, at the exact minute |
| log | a gym check-in, bar tab, grocery receipt or library checkout puts a named resident somewhere; a dropped receipt's time is matched by the grocery's log, which names who paid |
| clue | left at the crime place: a boot print, coat thread or tracks showing one of the culprit's traits, or a grocery receipt dropped by the culprit or someone who was there, showing only the store and the time |
| statement | what a resident tells you in an interview: where they or someone else were, what they heard, who'd have a reason, how someone they know looks; what they heard may have drifted in the retelling, and then it's no good as evidence |

Statements can be lies: a culprit expected elsewhere gives a false alibi, and a housemate may cover for them. About
a third of the time the culprit is a regular at the scene, whose word on where they were is true; traits, clues and
records catch them instead.

**Interview** any resident from wherever you are (it's a modern town: you call or message them) by asking a question
in your own words, like "Where were you last night?". Each resident keeps one conversation with you, which you can
reopen from their card. Jev reads the question
with the conversation so far and routes it to where the resident was, where someone else was, what they saw, who
they heard something from, who'd have a reason (a feud or grudge with the victim), what they think of someone,
or what someone looks like (only from someone who knows them).
The game answers from what that resident knows and adds anything new to your notebook; Haiku only phrases the
reply, in character: opinions, grudges, theories and quirks come through, but a reply that invents a case fact (a
sighting, a time, a look) is swapped for the plain record. A question the game can't answer, or one the resident knows nothing about, gets "I wouldn't know about that."
You can ask each resident 4 questions a part of the day, then they'd rather talk later. Every question tells the
culprit, at most once a part of the day, that a podcaster is asking around, and they may start covering their tracks. Once pressed, the culprit may also warn
someone they're close to that the podcaster is stirring up trouble, at most once a part of the day per case: that
resident thinks less of the podcaster who last asked around (`reputation_warned`), and the warning spreads like any
other line. You only hear that someone in town seems colder toward you.

**Finding witnesses.** People who are usually at the scene in the part of the day it happened may have seen
something. The people list tags them "usually nearby" and ranks them near the top; type "nearby" in its search to see
only them. The tag comes from each resident's routine (their work place by day, their evening place, their street at
night), not from where anyone actually was, so most of the people it marks are innocent regulars, but on a petty case
the culprit can be one of them too. It's a lead: ask them what they saw.

Walking still matters for the scene and the records: you search a place and pull its records only while you're there.

**Pull records** at a place to copy the case's footage and logs there into your notebook. A place's records are
kept by the residents who work there, or for a street by those who live on it; they're shared unless every keeper
regards you below `guarded_at`.

**Search** the crime place, once per case, to find the one or two clues left there when the crime was staged.
A receipt names no one: pull the grocery's records to see who paid at that time. The solvability check counts the
clues and that log, so a case may need a search and a pull to crack.

**Photos.** While someone is playing, a resident posts a photo to the neighborhood app at the end of each morning,
afternoon and evening, so up to three a day: two or three residents who were at the same public place then, the poster
among them, captioned with who else is in it and what they had on, like "Cal Hughes posted: Evening at the bar with
Ivy Hughes in a denim jacket!" Every photo is true, and a culprit is never in one of their crime's own part of the day. Saving a
photo shows how each person in it looked that day and, while a case is open, adds it to your notebook. A case never
needs one. The app keeps the newest 60.

**Publish** an episode: choose a resident and tick between 1 and 5 notebook entries. It holds up when it names the
culprit, every cited entry is true evidence from this case, and at least one points at the culprit: a memory, clip
or trace whose traits all fit them as they looked that day, or a log that puts them at the crime place or behind a receipt found there. Otherwise the evidence
doesn't back it. One episode per podcaster per case.

- A right episode closes the case for everyone, and every resident thinks better of you (`reputation_right`). Any
  other podcaster with evidence from that case is told another podcaster cracked it first. A petty culprit stays in
  town, but now everyone knows what they did: the people list tags them "exposed", and residents bring it up when
  they're named. They won't talk to you (`reputation_exposed`) and are touchy with every podcaster. They lie low for
  `exposed_quiet_days`, then each morning either reform (`reform_chance`) or stay free to reoffend. The victim's
  household warms to you (`reputation_ally`), and the victim thanks the podcast on the app.
  A culprit of anything worse than a petty crime is arrested instead and leaves town at once. Their accomplice, if
  they had one, is exposed for covering for them, stays in town and won't talk to you either. An episode that cites
  the accomplice's word doesn't hold up.
- A wrong one leaves the case open for others. The town hears the accusation anyway, everyone thinks less of you
  (`reputation_wrong`), and the accused most of all (`reputation_accused`). Their household and anyone close to them
  think less of you too (`reputation_accused_ties`). Once the case is closed, the accused remembers: they bring it
  up, hurt and short with you, and the people list tags them "you named them".

**Standing** is how far your podcast has come in this run, shown in the header. A held episode on the town's case
adds 1, 2 or 3 points for a petty, serious or major case; a wrong one takes 1 away, never below 0. The practice case
never moves it. At `serious_at` points you're "Known in town" and bigger tips start coming in; at `major_at` you're a
"Town legend".

**Reputation** is each resident's regard for you, in [-1, 1], drifting back toward 0 by `reputation_decay` each part
of the day. A resident below `guarded_at` won't talk to you or share the records they keep. A witness at or above
`trusted_at` recalls one more of the culprit's traits in an interview, a fuller memory that goes in your notebook as
a new entry.

Everything is done on one page, built around the case. On the left: the case with Publish (and, on a first case, its checklist),
which opens the form in place (choose a resident, tick notebook entries); the notebook grouped by kind (Seen, Clip,
Logs, Said, Found, Heard, Photos), newest first; where you are, with Search here and Pull records when they apply and the
places you can go; and at the foot, a small Districts map: each street with its crime and fear as three pips, an
arrow when either has risen or fallen since the morning, and any watch with who started it, never the numbers behind
them (hidden in the first case). In the header, the neighborhood app: a link that counts what's new and opens one feed, newest
first, as a panel on the right (a sheet from the bottom on a phone) of case news, what residents are saying, and their
photo posts, each with who posted it, the faces in it, its caption and Save. On the right:
everyone in town with their job and street, searchable by name, job or known looks, marked victim or witness once you
know and "usually nearby" when their routine puts them at the scene, and the conversation with
whoever you pick. Someone's looks show only once you've learned them, how and when first, and until then their face
is a grey silhouette; talking to someone shows how they look today: height, hair and the outfit they have on. On a phone the two columns stack.

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

Residents' own app posts (a lost pet, a note to the neighbours, a gripe, a theory about the open case) skip Contex:
they show on the page and never reach a mind. Each part of the day, while someone plays, one is posted with
`chatter_chance`, at most one Haiku call.

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
your share in the menu. Haiku writes each new town and each resident who moves in, phrases what residents say and each interview reply, and
writes at most one app post per part of the day. Jev decides
what a woken resident does, plans routines (once more for each resident who moves in), and routes each interview
question. A question costs at most one call to
each.

Once the day's estimated spend reaches `SLEUTH_DAILY_SPEND_CAP` the town rests until midnight UTC: residents stop
thinking, and interviews, pulls and episodes are refused. Walking still works.

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
| `SLEUTH_DAY_SECONDS` | `900` | length of a game day, in seconds (15 minutes) |
| `SLEUTH_CASE_DAYS` | `3` | game days before an open case goes cold |
| `SLEUTH_REPUTATION_RIGHT` | `0.3` | regard every resident gains for a right episode |
| `SLEUTH_REPUTATION_WRONG` | `-0.4` | regard every resident loses for a wrong episode |
| `SLEUTH_REPUTATION_ACCUSED` | `-0.4` | further regard the wrongly accused loses |
| `SLEUTH_REPUTATION_EXPOSED` | `-0.6` | regard an exposed culprit has for the podcaster who exposed them |
| `SLEUTH_REPUTATION_ALLY` | `0.3` | further regard the victim's household gains for a right episode |
| `SLEUTH_REPUTATION_ACCUSED_TIES` | `-0.3` | further regard the wrongly accused's household and close ties lose |
| `SLEUTH_REPUTATION_WARNED` | `-0.2` | regard a resident loses when the culprit warns them about you |
| `SLEUTH_REPUTATION_DECAY` | `0.02` | how far regard drifts back toward 0 each part of the day |
| `SLEUTH_GUARDED_AT` | `-0.3` | below this regard a resident won't talk to you or share records |
| `SLEUTH_TRUSTED_AT` | `0.2` | at or above this regard a witness recalls one more of the culprit's traits |
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
| `SLEUTH_CHATTER_CHANCE` | `0.5` | chance each part of the day, while someone plays, that a resident posts on the app |
| `SLEUTH_OFFENDERS` | `5` | how many hidden offenders commit the town's crimes |
| `SLEUTH_ESCALATE_AFTER` | `2` | cases an offender gets away with before moving up a tier |
| `SLEUTH_EXPOSED_QUIET_DAYS` | `2` | game days an exposed offender lies low |
| `SLEUTH_REFORM_CHANCE` | `0.3` | chance each morning after that an exposed offender reforms |
| `SLEUTH_NEWCOMER_OFFENDER_CHANCE` | `0.3` | chance someone who moves in is an offender |
| `SLEUTH_MAX_OFFENDERS` | `6` | most offenders that moving in can bring the set to |
| `SLEUTH_SERIOUS_AT` | `3` | standing at which a podcaster is offered serious cases |
| `SLEUTH_MAJOR_AT` | `6` | standing at which a podcaster is offered major cases |
| `SLEUTH_MAJOR_CASE_DAYS` | `6` | game days before an open major case goes cold |
| `SLEUTH_MAJOR_EVERY_DAYS` | `3` | fewest game days between one major case opening and the next |
| `SLEUTH_ACCOMPLICE_CHANCE` | `0.5` | chance a serious culprit has an accomplice who vouches for them |
| `SLEUTH_DISTRICT_CRIME_DECAY` | `0.02` | how far a district's crime fades each part of the day |
| `SLEUTH_DISTRICT_FEAR_DECAY` | `0.015` | how far a district's fear fades each part of the day |
| `SLEUTH_ORGANIZE_FEAR` | `0.4` | fear at which a district with an exposure starts a watch |
| `SLEUTH_DISBAND_BELOW` | `0.05` | crime and fear below which a watch winds down |
| `SLEUTH_ORGANIZED_CRIME_WEIGHT` | `0.25` | how much less likely a crime is in a district with a watch |
| `SLEUTH_NEGLECT_AT` | `0.4` | crime and fear at which a district without a watch is neglected |
| `SLEUTH_TURN_CHANCE` | `0.5` | chance each morning that a neglected district turns a resident into an offender |
| `SLEUTH_MIN_OFFENDERS` | `3` | fewest offenders before the set is refilled from districts without a watch |

## Tests

```bash
pip install -r requirements-dev.txt
pytest sleuth
SLEUTH_CONTEX_URL=http://localhost:8001/mcp pytest sleuth
```

The second run adds the tests that need a live Contex.
