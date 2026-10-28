# Playtest: Sleuth's living town, 2026-10-28

One town played from a fresh generation through eleven game days, against a live Contex with real Jev and Haiku. The
checklist is the `## Playtest` section of `docs/superpowers/plans/2026-10-28-sleuth-living-town.md`. Every item but the
optional major case was shown in this one town. Fifteen fix commits landed on `feat/sleuth` along the way.

## Setup

- Contex: the owner's instance at `http://localhost:8001/mcp`, backed by `rumor-mill-db` on 55434. The first attempt
  stopped at startup because the disk was full, which had stopped Docker and the database. It resumed once the owner
  freed space.
- Game server on 8790, session `lt28b`, data in a scratch `live1/` directory. Keys came from `contex/.env` and were
  sourced in the launching shell, never printed.
- Settings were the plan's pacing knobs:

  ```
  SLEUTH_POPULATION=24 SLEUTH_DAY_SECONDS=240 SLEUTH_CASE_DAYS=2 SLEUTH_MAJOR_CASE_DAYS=3
  SLEUTH_SAVE_EVERY_SECONDS=5 SLEUTH_SERIOUS_AT=2 SLEUTH_MAJOR_AT=4 SLEUTH_MAJOR_EVERY_DAYS=0
  SLEUTH_ESCALATE_AFTER=1 SLEUTH_ORGANIZE_FEAR=0.25 SLEUTH_NEGLECT_AT=0.3 SLEUTH_TURN_CHANCE=1
  SLEUTH_REFORM_CHANCE=0.5 SLEUTH_EXPOSED_QUIET_DAYS=1 SLEUTH_CHATTER_CHANCE=1 SLEUTH_DAILY_SPEND_CAP=3
  ```

  From day 5, `SLEUTH_DISTRICT_CRIME_DECAY=0.05` and `SLEUTH_DISTRICT_FEAR_DECAY=0.04` were added (also pacing only),
  so a district's fall would show within a few game days.
- The server was restarted about ten times to pick up fixes. Each restart was a SIGINT, so the game saved on
  shutdown and restored on start. Standing, notebooks, watches, offenders and open cases all came back intact,
  which proves save and restore.
- Four podcasters:
  - **A**: the oracle's main player. Skipped the first case.
  - **B**: made the deliberate wrong episode, then played petty cases.
  - **C**: a third podcaster for the "reads cold" check, later serious cases.
  - **D**: the browser player. Played the first case by hand, then petty cases through the API.
- The oracle was a throwaway script in the scratchpad (not committed). It reads `sleuth_worlds/lt28b.state.json` for
  each open case's culprit, records, offenders and raw district numbers, and drives the HTTP API with a player's
  cookie. A podcaster's turn went like this:
  1. Ask the victim "Can you tell me what happened?" and "Who would have a reason to do this to you?".
  2. Ask up to four "nearby" residents whether they saw anything.
  3. Walk to the scene, search it and pull its records.
  4. On serious cases, ask the suspect where they were and the accomplice where the suspect was.
  5. Publish naming the culprit, citing the sound notebook entries that point at them.

  The script saved every `/api/state`, `/api/case` and `/api/villagers/*` response, plus four minutes of WebSocket
  frames for two players, for the leak scan.

## Cases

Twenty-six held episodes (14 petty, 12 serious), one wrong episode and two cases gone cold. Where the outcome lists record kinds, those are what the episode cited. Every held episode cited
only sound memories, clues or logs that pointed at the culprit.

| Case | When (day, part) | Tier | Crime | Culprit | Victim | Accomplice | Outcome |
|---|---|---|---|---|---|---|---|
| case-1 | 0 night | petty | sabotaged pumpkin, Maple St | Priya Raman | Fern Abernathy | | B wrong (named Eugene Mott, cited 1 memory); A held (3 memories, tracks) |
| case-4 | 0 night | petty | stole bike, Maple St | Yusuf Okonkwo | Dwight Oberholtzer | | A held (memory, thread, tracks) |
| case-1006 | 1 afternoon | petty | goose, dog park | Lionel Haddad | Bruno Caldera | | cold: Lionel exposed, escalated |
| case-1007 | 1 afternoon | serious | robbed till, cafe | Nell Ostrowski | Ginny Fothergill | Lydia Okonkwo-Park | A held (3 memories, tracks); arrest |
| case-1012 | 2 morning | serious | robbed cash box, cafe | Yusuf Okonkwo | Ginny Fothergill | Hal Brubaker | A held (3 memories, 2 clues); arrest |
| case-3026 | 3 morning | serious | robbed till, bar | Mirela Okonkwo-Brandt | Darlene Pruitt | | cold: arrested |
| case-4029 | 3 afternoon | petty | vandalized car, gym | Mavis Oakhurst | Lydia Okonkwo-Park | | C held (tracks, gym check-in, memory) |
| case-5032 | 4 morning | petty | goose, dog park | Ottilie Brandt | Trudy Ostrander | | D held (memory, thread) |
| case-6036 | 5 morning | serious | stole car, hardware store | Mavis Oakhurst | Cornelius Brandt | Lionel Haddad | A held; arrest |
| case-7041 | 5 evening | petty | moustache on portrait, library | Tomasz Kowalczyk | Eugene Mott | | C held |
| case-7042 | 5 night | serious | stole car, Elm St | Ruth Ellery Bannon | Gus Tilley | Ottilie Brandt | A held; arrest |
| case-7048 | 6 afternoon | serious | mugging, bar | Trudy Ostrander | Darlene Pruitt | | C held (5 entries); arrest |
| case-7050 | 6 afternoon | petty | moustache on portrait, library | Eugene Mott | Opal Greenway | | B held |
| case-8057 | 7 morning | serious | mugging, dog park | Tomasz Kowalczyk | Bruno Caldera | | A held; arrest |
| case-10060 | 7 afternoon | petty | stole tote bag, cafe | Fern Abernathy | Agnes Whitfield | | D held |
| case-10062 | 7 afternoon | serious | mugging, dog park | Opal Greenway | Bruno Caldera | | A held; arrest |
| case-10067 | 7 evening | petty | sabotaged jam, library | Darlene Pruitt | Eugene Mott | | B held |
| case-11072 | 8 morning | serious | stole car, hardware store | Fern Abernathy | Gus Tilley | Sebastian Quaid | A held; arrest |
| case-11078 | 8 afternoon | petty | stole tote bag, gym | Dolores Pruitt | Lydia Okonkwo-Park | | B held |
| case-11083 | 8 evening | petty | salted sugar jars, cafe | Winnifred Oakes | Walter Benning | | D held |
| case-11088 | 9 morning | serious | mugging, grocery | Eugene Mott | Frances Okonkwo-Reyes | | C held; arrest |
| case-11090 | 9 morning | petty | stole bike, school | Dolores Pruitt | Sebastian Quaid | | B held |
| case-11093 | 9 afternoon | serious | mugging, grocery | Darlene Pruitt | Marisol Reyes | Bruno Caldera | A held; arrest |
| case-11095 | 9 afternoon | petty | vandalized car, hardware store | Imelda Brackenridge | Cornelius Brandt | | D held |
| case-11099 | 9 night | serious | mugging, Oak St | Bartholomew Finch | Winnifred Oakes | Ginny Fothergill | C held; arrest |
| case-11101 | 9 night | petty | pinched gnome, Elm St | Ginny Fothergill | Agnes Whitfield | | B held |
| case-11104 | 10 morning | serious | stole car, grocery | Dolores Pruitt | Odette Brambleworth | Imelda Brackenridge | A held; arrest |
| case-11107 | 10 afternoon | petty | stole bike, gym | Walter Benning | Lydia Okonkwo-Park | | B held |

From case-8057 on, an unattended loop played every open case each part of the day, rotating the podcasters, with the
same questions and the same citing rule.

## Checklist

### 1. Several cases solved ✓

There were 26 held episodes, 14 petty and 12 serious. Each closed the case for every podcaster
(`case_closed`), and a new tip of that tier followed within the same step. For example, holding case-1 opened case-4
at once: "Someone stole Dwight Oberholtzer's bike on Maple Street last night."

### 2. A petty culprit exposed and treated differently ✓

Priya Raman was exposed by A on case-1.
- The people list tags her `exposed` with what she did: `known_for: "sabotaged Fern Abernathy's county-fair pumpkin"`
  ([b-people-districts.jpg](2026-10-28-living-town/b-people-districts.jpg)).
- A's interview with her was refused: `409 {"error": "Priya Raman won't talk to you."}`.
- C, a fresh podcaster, got a guarded answer: "I don't have anything to add about the county fair, and I'd rather
  not get into rumors about pumpkins." Much later A, whose regard had drifted back, got "I'd rather talk about Darlene
  Pruitt's mugging than a pumpkin, so ask me something about that."
- On the app, once the thanks fix below was in: "Thanks to that podcast, everyone knows who stole my bike!" (Dwight
  Oberholtzer), and "Maple Street breathes a little easier now Priya Raman's been found out."

### 3. A serious culprit arrested and replaced ✓

When Nell Ostrowski was arrested on case-1007, the app said "Nell Ostrowski was arrested and has left town." and she
dropped off the people list. Mavis Oakhurst moved in on Oak Street a few seconds later. Thirteen residents left over
the run, and someone moved in for each. The page shows a newcomer with a job and ties, for example Imelda Brackenridge:

```
"occupation": "Part-time hardware store clerk",
"relationships": [{"name": "Dolores Pruitt", "kind": "neighbor"}, {"name": "Winnifred Oakes", "kind": "rival"}],
"home": "oak street", "household": []
```

Newcomers live alone, so `household` lists nobody else. Only the oracle saw that Mavis Oakhurst and Ruth Ellery
Bannon joined the offenders; both later committed crimes. Nothing on the page shows it.

### 4. A district organizing ✓

- **The watch forms.** Maple Street formed a watch first: "Maple Street residents are starting a watch. Fern's
  making flyers." Then Elm Street, after case-1007 held: "Elm Street residents are starting a watch. Ginny's making
  flyers." The district panel names the watch and who started it.
- **Watches wind down.** Watches that calmed down were wound down on the app: "The Maple Street Porch-Light Pact has
  wound down. Maple Street feels safe again."
- **Elm Street's crime level falls.** It went from full to empty under its watch. From the oracle's district log:

  ```
  7 afternoon  elm c=1.00 f=1.00 w=Y | oak c=0.10 | maple c=0.00
  8 morning    elm c=0.60 f=0.72 w=Y | oak c=0.20 | maple c=0.00
  9 night      elm c=0.35 f=0.59 w=Y | oak c=0.00 | maple c=0.95
  10 evening   elm c=0.30 f=0.62 w=Y | oak c=0.45 | maple c=0.95
  ```

  Screenshots: before, Elm at 3 of 3 ([b-people-districts.jpg](2026-10-28-living-town/b-people-districts.jpg)); after,
  Elm at 0 of 3 with Maple at 3 of 3 ([districts-after.jpg](2026-10-28-living-town/districts-after.jpg)).
- **The tally of new crimes shifts.** Elm Street's watch formed at day 1.75. Until the two weighting fixes below,
  Elm took 8 of the next 13 crimes. After them (from day 8), Elm took 2 of 11, while Oak took 4 and Maple 5.
  Before those fixes the watch was not moving crime; see `6b340e6` and `724369c`.

### 5. Standing rising and tips escalating ✓

- **A's standing.** A moved from "New podcaster" to "Known in town" on case-4, with the line "Bigger tips are coming
  in now: serious cases." A reached "Town legend" on case-1007, with "The whole town is listening. The biggest cases
  come to you now." A ended on 20 points ([a-main.jpg](2026-10-28-living-town/a-main.jpg)).
- **Tips by player.** A's tips row listed case-1007 (Serious) and case-1006 (Petty). At the same moment, B and C saw
  only `[('case-1006', 'petty', "Bruno Caldera's goose")]`.

### 6. The wrongly accused remember ✓

- **The wrong episode.** B named Eugene Mott for the pumpkin, citing Opal Greenway's memory. B got "Your episode
  didn't hold up. The town now believes it, and people are warier of you."
- **Eugene's reaction.** He posted "Oh, I'm so sorry, ... it's me they're talking about, Eugene Mott, and I never
  touched Fern's pumpkin, I swear."
- **The people list.** Once A closed the case, B's people list tagged him "you named them" (`accused: true`).
- **Refused.** B's next interview with him was refused: "Eugene Mott won't talk to you."

### 7. Whimsy ✓

After the token-limit fix, posts end where they should and each one shows a quirk. For example:
- Ottilie Brandt: "My money's on the tote bag having simply gone for a walk, because nobody in this town has ever
  resisted a free tote, and I say that as someone who keeps a notebook of every odd license plate that crosses my
  radio."
- Hal Brubaker: "Well, I suppose the whole town will now be an expert on jam sabotage, thanks to the local paper
  turning one spoiled jar into a crime wave."
- Dolores Pruitt: "Somebody got mugged at the grocery yesterday and now everyone's acting like the town's gone to the
  dogs, but I bet the new self-checkout kiosk has more to answer for than the thief does."
- Odette Brambleworth: "Honestly, my money's on whoever keeps leaving the cart corral gate open, because that's a
  well-known gateway to trouble, and my raccoon tally is up to eleven this week, so I wouldn't rule anything out."
- Agnes Whitfield: "... I've learned never to underestimate a cat with opinions."

Interview replies showed quirks too, like Lydia Okonkwo-Park noting "a red-winged blackbird on the fence post outside
the gym ... which I wrote down as usual." No post carried faith or gore. One invented detail got through after the
fixes; see open issues.

### 8. No leaks ✓

The oracle scanned 267 saved payloads: every `/api/state`, `/api/case` and `/api/villagers/*` the run fetched, plus
83 WebSocket frames for A and B. It found no `offender`, `escaped`, `quiet_until`, `motive`, `culprit`,
`accomplice`, `warmth`, `sound` or `exposures` key. No resident carried a `tier`; `tier` appears only on cases and
the player's own standing. District values were the 0 to 3 levels only (`"crime":0..3`), never the floats.

### 9. Tutorial unaffected ✓

A fresh browser cookie got the intro cards and played the six steps by hand:
1. Asked Ruth Okafor what happened.
2. Asked Tess Moreno what she saw.
3. Asked Ruth who is tall and red-haired, and she named Cal Hughes.
4. Talked to Cal.
5. Searched the library and found the green-raincoat thread.
6. Published Cal citing the sighting and the thread.

The page said "You got it. It was Cal Hughes." and handed over the town's open case, "Someone vandalized Lydia
Okonkwo-Park's car at the gym this afternoon." ([tutorial-verdict.jpg](2026-10-28-living-town/tutorial-verdict.jpg)).
The same player then held case-5032 as D.

### Major case ✗ (optional)

No major case opened. Lionel Haddad did reach the major tier: his goose case went cold, he escalated to serious, and
he was promoted to major. But a death needs a victim on cold terms with at least two residents besides the culprit.
In this 24-person town only Walter Benning (cold with Lionel and Ginny) and Lionel himself had two cold ties, so with
Lionel as the culprit no victim fit, and every draw returned nothing. Lionel later reformed. See open issues.

## Bugs found and fixed

Each fix was test-first, with its own commit, and passed the full suite, `ruff check .` and `node --check` before
committing.

| Commit | What the playtest showed | Fix |
|---|---|---|
| `ca3b334` | Known gap: a death in the evening whose window ran into the night got no household word, while one at night did, which gave away its true part of the day. | A household word covers any crime whose window includes the night. |
| `20525f1` | Fern's sabotaged pumpkin: "Got my county-fair pumpkin back thanks to that podcast!" | The thanks says what was done: "Thanks to that podcast, everyone knows who sabotaged my county-fair pumpkin!" |
| `34717d3` | Yusuf Okonkwo, exposed a minute earlier and lying low, was promoted to the serious tier, so no serious case could open until the next day. | Only an offender free to offend is promoted, and a tier counts as empty when none of its offenders is ready. |
| `47ed1b1` | "Mavis Oakhurst, a Night-shift pharmacy technician, moved in" (and "a Owner of ..." waiting to happen). | "Mavis Oakhurst moved in on Oak Street. Night-shift pharmacy technician." |
| `6b340e6` | Elm Street got two till robberies in a row under its watch. A crime's kind was drawn before the watch weighting, so a kind that only fits watched places always landed there. | Each kind is drawn by the mean weight of its possible victims' places. |
| `82562c2` | A second till robbery: Ginny said "the time I gave you earlier was wrong, it was 8:40am and not 1:56", and witnesses kept "correcting" sightings that were of another crime. The whole conversation across cases went to the models. | Each exchange records its case; only this case's exchanges go to Jev and Haiku. |
| `11922ad` | The last petty offender was exposed while the other two were serious, so the set stayed at the floor and no petty case could open. New players saw a quiet town. | The set is refilled when no petty offender is free to offend. |
| `86b6656` | A browser with a cached page and no cookie showed "Reload the page to rejoin the town" on its first visit. | The page is sent with `Cache-Control: no-cache`. |
| `4d5d61c` | After Yusuf's arrest, ten case draws in a row raised `KeyError: 'v016'`: the finished part of the day's whereabouts still had him. | Whereabouts keep only residents still in town. |
| `2f87846` | Chatter: "Has anyone seen Darlene Pruitt's cash box?" while the case was her till. | A post that names someone in the case and a crime item the case lacks is dropped. |
| `724369c` | By day, serious crime had almost nowhere outside Elm: a simulation of this town put Oak at 3-5%. Elm stayed at full crime under its watch. | The gym has a till, and the gym and grocery lots see muggings. |
| `65599cd` | 17 of 18 app posts ended mid-word ("... patients this year. Po"). Speech and posts are capped at 80 tokens. | A line cut off by the cap keeps only its whole sentences; one with none is dropped. |
| `022de40` | All three streets organized, the offenders fell to two, and the refill had no district to draw from. | With every district organized, the refill draws from the whole town. |
| `40842aa` | Bruno Caldera was mugged at the dog park in the morning and again that afternoon. | A resident whose case opened today or yesterday is not drawn as a victim. |

Defaults were not changed.

## Spend

The game's own estimate for the UTC day, which is what the menu reads: **$0.064** in total. That is Haiku 183k in /
44k out and Jev 600k in / 138k out, including town generation and 13 newcomers. Per podcaster: A $0.0085, B $0.0028,
C $0.0032, D $0.0031. The rest was resident turns and chatter.

## Open issues

1. **Major cases rarely can open.** A death needs a victim with two cold ties besides the culprit, and ties are
   mostly warm (one draw in five is a rival). In a 24-person town only two residents qualified, one of them the only
   major offender. Separately, a second serious offender is needed before anyone is promoted to major, and active
   podcasters arrest serious culprits as fast as they appear. Options: guarantee a few rivalries in town generation,
   or pick the major culprit from offenders who can stage a death.
2. **Occupations don't match routines.** Darlene Pruitt is a hairdresser at a salon, but her routine put her at the
   bar, so a till robbed "at the bar" was "Darlene Pruitt's till", and she posted "I'm not even at a bar, I'm at the
   salon!" Priya Raman, a night-shift nurse, was a gym witness and replied "I wasn't at the gym yesterday afternoon.
   I was asleep ... The only thing I can tell you is that around 2:14pm someone bald was bent over something at the
   gym." A till's victim should work at the place, and the game should never contradict a resident's job.
3. **Offender churn.** With these knobs, 22 different residents committed crimes in 11 days in a town of 24,
   including two watch founders. Some of that is the pacing. The new "no petty offender free" refill (`11922ad`) tops
   the set up to `offenders` each time, which adds churn. Worth watching at the defaults.
4. **Chatter can still invent a method.** "Somebody took a bat to Ottilie's car on Oak Street last night" passed the
   fact check: a method is not a look, time, place or item.
5. **Retold speech embellishes freely.** Lines like "the back door was propped open with a bread crate" and "keys in
   the ignition" are allowed by design for hearsay. They read like facts on the app, though, and a podcaster can't
   tell them from testimony.
6. **A mugging victim's own memory reads oddly.** "I saw it myself. Around 9:01am, at the dog park, someone short,
   dark-haired was grabbing at someone." The victim is the "someone".
7. **Invented place names in replies.** Examples: "half the people on Main Street", "the Ferris Street bulletin
   board". They aren't case facts, but the town has three streets.

## Fixes after playtest 1

Each fix was test-first, with its own commit, and passed the full suite (843 passed, 9 skipped at the end), `ruff
check .` and `node --check` before committing. None needs a new save version. The fixes are not playtested yet.

| Commit | Open issue | Fix |
|---|---|---|
| `d01096a` | 1. Major cases rarely can open. | Town generation turns warm ties rival until one resident in five has two people on bad terms with them, and someone moving in is a rival while too few do. A death's motives count grudges either way as well as cold ties. With no major offender free, a serious one commits the major case and moves up, one promoted from petty first when none is free. A test runs five generated 24-person towns at the playtest's pacing with a major-tier podcaster: each opens a major case within two game days. |
| `f4c833b` | 2. Occupations don't match routines. | Town generation asks for jobs at the town's own places or from home, and draws again for one that names nowhere in town. A job that names its place sets the work place: a barista works at the cafe, a librarian at the library, and a night-shift or home-based job is home by day. Jev picks only the rest, and a saved routine that contradicts the job is asked again. A till is robbed only from someone who works where it is. |
| `70ccdb6` | 3. Offender churn. | Once crime has begun, the set is refilled only to `min_offenders`, plus one when no petty offender is free. At most `offender_share` (new, 0.25) of the town are or were offenders. Past it, the refill draws exposed residents who gave it up, and nobody new moves in as one or is turned. A standing watch's founder is never drawn. |
| `6a4c744` | 4. Chatter can still invent a method. 5. Retold speech embellishes freely. | A case line that names a tool, force or a way in that the facts lack ("took a bat to", "smashed", "keys in the ignition") now counts as an invented fact. The post is dropped, and an interview reply falls back to its plain record. Retold room talk still reaches the app embellished, but as hearsay: "Ada Reyes heard: ...". |
| `2c727bb` | 6. A mugging victim's own memory reads oddly. | "Around 9:01am, at the dog park, someone short, dark-haired grabbed at me and took my wallet." It stays that way when the victim recalls one more trait. |
| `b1d7074` | 7. Invented place names in replies. | A line, reply or post that names a street other than Elm, Oak or Maple Street comes back empty. It is never said, and an interview reply falls back to its plain record. |

### Offender rate

The test was a simulation of 40 towns for 11 game days with the real `Cases`, `Offenders` and `Districts`. Each town
had two podcasters, one at the serious tier. Each open case was solved with a chance of 1 in 4 each part of the day,
and anyone who moved in was a stand-in with no model calls.

| Settings | When | Distinct offenders | Residents left who ever offended | Towns where a watch founder turned | Cases opened |
|---|---|---|---|---|---|
| Defaults (50 residents) | before | 17.9 | 20% (34% at worst) | 12 of 40 | 22.8 |
| Defaults (50 residents) | after | 16.8 | 18% (24% at worst) | 0 | 21.8 |
| Playtest pacing (24) | before | 22.6 | 56% (71% at worst) | 30 of 40 | 24.8 |
| Playtest pacing (24) | after | 16.2 | 24% (29% at worst) | 0 | 23.9 |

Each case still needs a culprit, and every serious culprit is arrested and leaves town. So the count of distinct
offenders mostly follows how many cases open. The cap bounds what a player sees: how much of the town they live
beside has offended.

## Playtest 2

A second town, generated fresh so the fixes after playtest 1 applied from the start, played from day 1 to day 12
against the same live Contex with real Jev and Haiku. Ten fix commits landed along the way.

### Setup

- Game server on 8790, session `lt28c`, data in a scratch `live2/` directory, the same pacing knobs as round 1
  (including the two district decay overrides from the start) and `SLEUTH_DAILY_SPEND_CAP=3`.
- Round 1's oracle and loop, unchanged except for the session. Podcaster A kept a WebSocket open throughout, as a
  player with a tab would; B also did, for the leak scan. The loop played every open petty and serious case each part
  of the day. It skipped major cases, so the first death was worked by hand.
- Five restarts to pick up fixes, each a SIGINT, each restoring the town intact.

### Log

- **Day 0 to 1.** The town was generated with 24 residents. A held case-1 (Lorna Vance, a jam, petty) and case-6
  (Fiona Marchetti, a portrait moustache, petty). A moved to "Known in town" and the serious tier.
- **Day 1.** The jobs spot-check found two residents whose job contradicted the game: Opal Vanterpool,
  "schoolteacher, works out of town", spent the day at the school, and Murray Kettering, "night attendant at the
  gym", spent the day at the gym. Fixed (`b40dddb`). On restart the saved routine was asked again and both were home
  by day.
- **Day 1 to 3.** No serious case opened from day 1 evening to day 3 morning. That was A being idle with no tab
  open, which is how a serious tier is meant to lapse. A's WebSocket was kept open from then on. The first serious
  case (Silas Ferreira mugging Fiona Marchetti at the bar) was held by A; "Silas Ferreira was arrested and has left
  town." was followed by "Imogen Parrish moved in on Elm Street. Children's librarian at the library."
- **Day 3 to 4.** The app showed a post cut at "on my 6 a.m." (`0666309`), a post saying "whoever cut up Gordon
  Pike's prize quilt" while the open case it was checked against was a mugging (`77e2db7`, `07560dc`).
- **Day 4 morning: the death.** With A at "Town legend", Gordon Pike, a petty offender moved up, killed Dolores
  Finch at the grocery. Her window was night to morning; the truth was morning.
- **Day 5 to 6.** A worked the death by hand (below) and held it. Four fixes came out of it: `ceb97bf`, `fc17379`,
  `a3678fb`, `37d1a7a`.
- **Day 6 to 9.** Four newcomers in a row moved in as "Barista at the cafe", and three move-ins failed outright
  because Haiku kept offering taken first names, leaving three homes empty. Fixed (`91dfc8d`); the next move-ins
  were a bookkeeper, a hardware store cashier and a dog park attendant, and the homes filled. A second death
  (Lorenzo Pike killing Agnes Pruitt on Oak Street) opened on day 7 and B held it through the loop.
- **Day 9 to 10.** Victims retold the app's news of their own case about themselves (`78d07a5`).
- **Day 10 to 12.** A third death (Derek Lindqvist killing Lottie Abernathy-Pryce, window evening to night) opened
  and was still open when the run stopped.

### Cases

40 held episodes and none gone cold: 27 petty, 11 serious and 2 major. 13 serious and major culprits were arrested;
with the three deaths, 16 residents left and 16 moved in. No wrong episode was taken this round.

### Goals

**1. A major case, worked naturally, held ✓.** case-1038, "The death of Dolores Finch".
- News: "Dolores Finch was found dead at the grocery. It happened sometime between last night and this morning.
  Police are treating it as suspicious." No how, no gore.
- Questions A asked, in order: Derek Lindqvist (the finder) "I'm so sorry. I heard you were the one who found
  Dolores. Can you tell me what happened?" and "Did you see anyone else around the grocery that morning?"; Nadia
  Brandt "Were you at the grocery when Dolores died?"; Lorna Vance (her spouse) "Was there anyone who'd want to hurt
  her?" and "When did you last see her?"; Tamsin Overby (a rival) "How did you get along with Dolores Finch?";
  Priya Raman (a rival) and Gordon Pike "Where were you when Dolores died?"; then the scene's search and records.
- Replies stayed sober. Lorna: "I won't pretend I'm not hurting, and I'd rather not speculate about who might have
  wanted to harm Dolores. What I can tell you is that Tamsin Overby has never got on with Dolores, and Priya Raman
  has never got on with her either." Gordon, the culprit: "Well enough to say good morning to, and that's about the
  extent of it."
- Posts stayed sober and said nothing of how. Edith Monroe-Shaw: "I can't stop thinking about Dolores Finch, who
  always had a kind word for the cashiers and always remembered to ask after my sketchbook." Retold: "Oh, goodness,
  the app says Dolores Finch was found dead at the grocery, and police are calling it suspicious, so I'm worried
  sick for her family."
- The window held everywhere it was said. Posts and alibis gave only the window ("between two nights ago and
  yesterday morning"; "I was on Maple Street, sometime between ..."). The morning showed only in the evidence:
  sightings at 7:25am, 7:58am and 8:01am, the camera at 7:41am and Gordon's receipts at 7:00am and 7:33am. That is
  the detective work, not a leak.
- A published Gordon Pike citing two sightings, the clip and his two receipts: "It holds up. Case closed." The app
  said "Gordon Pike was arrested and has left town." and "Maple Street breathes a little easier now Gordon Pike's
  been found out."
- Screenshots: the case before publishing ([p2-major-before.jpg](2026-10-28-living-town/p2-major-before.jpg)) and
  the app after ([p2-major-app.jpg](2026-10-28-living-town/p2-major-app.jpg)).

**2. Round-1 ripples ✓.**
- Several cases solved: 40 held, each followed by a new tip of its tier.
- Petty exposure: D exposed Ingrid Solberg on case-1007; D's interviews with her on the next case were refused
  ("Ingrid Solberg won't talk to you."). The people list tags the exposed with what they did. Thanks and relief
  posts followed every petty hold, for example "Thanks to that podcast, everyone knows who let out my dog!" and
  "Oak Street breathes a little easier now Ruben Castellanos's been found out."
- Arrest and newcomer: 13 arrests, each followed by a move-in (after `91dfc8d`).
- Watch and crime moving: watches formed on all three streets by day 5. Maple Street's crime fell from 0.65 on day 4
  to 0 by day 8 and its watch wound down ("The Maple Street Group Chat has wound down. Maple Street feels safe
  again."), while Elm and Oak climbed to full.
- Standing to tips: A went "New podcaster" (day 1 morning) to "Known in town" (day 1 evening) to "Town legend" (day
  4). On day 10 A's tips were a serious mugging and a petty bike; a new podcaster (E) saw only the petty bike.

**3. The fixes ✓, with gaps.**
- Jobs fit routines: 22 of 24 generated residents had a job at a named place they worked at, or a home job and were
  home by day. The two that didn't are fixed in `b40dddb`.
- Offender share: the set held at 3 to 5 throughout. Of 21 residents on day 9, 4 had been a culprit.
- No invented methods: after `77e2db7` and `07560dc`, none of the last 109 app events named a method. Before them,
  "whoever cut up Gordon Pike's prize quilt" got through as an unchecked post.
- Gossip shows as hearsay: every retold line showed as "{name} heard: ...". Hearsay still embellishes, by design,
  for example "slashed it right down the middle".
- No invented street names in any post.

**4. Un-fun or confusing to a player.** See open issues 1 to 6.

### Leaks

349 saved payloads (`/api/state`, `/api/case`, `/api/villagers/*` and WebSocket frames for A and B), 0 hits for
offender flags, a resident's tier, raw district floats, warmth or `sound`.

### Fixes

Each was test-first, with its own commit, and passed the full suite (856 passed, 9 skipped at the end), `ruff check
.` and `node --check` on the page's script before committing.

| Commit | What the playtest showed | Fix |
|---|---|---|
| `b40dddb` | "Schoolteacher, works out of town" at the school all day; "night attendant at the gym" at the gym all day. | Any job at night or out of town is home by day. |
| `0666309` | A cut-off post ended "... by the hedges on my 6 a.m." | A cut line never ends at "a.m.", "p.m.", "Mr.", "Mrs.", "Ms.", "Dr." or "St.". |
| `77e2db7` | "Whoever cut up Gordon Pike's prize quilt" passed: chatter was checked only against the first open case. | Chatter gets and is checked against every open shared case; somber if any is a death. |
| `07560dc` | Quilts "cut up" and "ripped to shreds with scissors". | "Cut up/open", "scissors" and "shredded" are methods. |
| `ceb97bf` | The finder said "Around 8:23am, me found Dolores Finch at the grocery." | "I found Dolores Finch". |
| `fc17379` | Every reply Haiku wrote for the finder was thrown away, so two questions got the same stiff record. "Found her" counted as gendering the unknown someone, and "black puffer jacket" as a new look. | A pronoun right after "found" is allowed, and "jacket" or "coat" when the facts name a coat. |
| `a3678fb` | The death's news read "sometime between two days ago, at night and yesterday morning". | "Sometime between the night before last and yesterday morning". |
| `37d1a7a` | Dolores was found dead at 8:23am and had a grocery receipt at 8:45am. | A death's victim is logged only before the death. |
| `91dfc8d` | Four newcomers in a row were baristas; three move-ins failed on taken first names and homes stood empty. | A newcomer's workplace and first initial are drawn. Eight live draws all succeeded. |
| `78d07a5` | "Jolene Pruitt heard: Oh, I'm so worried about Jolene ..." | A retold case line that names its teller is dropped. |

### Spend

The game's own estimate for the session: **$0.088**, Haiku 262k in / 59k out and Jev 817k in / 187k out, including
generation and 16 newcomers. Per podcaster: A $0.0080, B $0.0076, C $0.0020, D $0.0085.

### Open issues

1. **Invented people and places in hearsay.** "That Halvorsen boy who always buys energy drinks", "the Hollis kid from
   the bakery". Neither exists, and the town has no bakery; a player could go looking. The street-name check doesn't
   cover names or places.
2. **Hearsay choruses.** One stolen thermos drew six near-identical "I'm so worried, love, poor thing" retellings in
   a row. Readable once, noise by the third.
3. **A natural question gets a shrug.** "How did you get along with Dolores Finch?" to her rival got "Can't help you
   there."; "When did you last see her?" to her spouse got "No idea, I'm afraid." Relationship questions have no
   intent, so the people with the most to say about a death say nothing.
4. **Older windows still read clumsily.** Two or more days on, the death's news says "sometime between three days
   ago, at night and two days ago, in the morning".
5. **Once every street has a watch, the panel says little.** From day 5 all three streets were organized, so the
   watch weighting was even and the "watch moves crime" ripple stopped being visible.
6. **A new podcaster can arrive to no tip.** On day 9 night no petty case was open for part of a day while every
   petty offender was lying low; the refill only opens one on the next tick.
7. **Residents mention the game's day count.** "The app says last night, and it's day six now". Once.
8. **"Breathes a little easier" after an arrest for a death** is the same line as for a stolen gnome. It reads a
   little light for a killing.
