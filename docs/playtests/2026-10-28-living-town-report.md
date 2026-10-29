# Sleuth: Living Town — Build and Playtest Report

**Date:** 2026-10-28
**Branch:** `feat/sleuth` (PR #1)
**Design:** "Addendum, 2026-10-28: a living town" in `docs/superpowers/specs/2026-10-25-sleuth-design.md`
**Plan:** `docs/superpowers/plans/2026-10-28-sleuth-living-town.md`
**Detailed log:** [`2026-10-28-living-town.md`](2026-10-28-living-town.md), with every case, the evidence for each ripple, every bug and its fix, and screenshots.

## Result

The whole design is built, and both live playtests met their goals. In the second playtest's town, played from day 1 to day 12 with real Jev and Haiku, several podcasters:
- **solved 40 cases** (27 petty, 11 serious, 2 deaths), with none going cold;
- **saw every ripple the design asks for**: exposure, arrests and newcomers, watches forming and moving crime, standing that raises the stakes, and the wrongly accused holding a grudge.

The first playtest's town solved 26 cases and showed every ripple, but no death ever opened. That was fixed, and the second town opened three.

## What was built

The design was built in 84 commits across six stages, each one test-first. Each stage was checked by an independent reviewer and got a fix round before the next started.

| Stage | What it added |
|---|---|
| 1. Facts versus flavor | Residents get one or two lasting quirks. One check, `invents_facts`, blocks invented case facts (identifications, sightings, places, times, looks, how the crime was done) and lets personality through. A petty crime catalog: salted sugar, the mayor's portrait, the goose, the gnome. Residents post on the neighborhood app. |
| 2. Offenders and consequences | A small hidden set of offenders, who escalate if they get away with things. Exposed petty culprits stay in town, publicly known and cold to the podcaster who exposed them, and later reform or reoffend. Serious culprits are arrested, and a newcomer moves in. The wrongly accused and their circle hold it against you. |
| 3. Standing and tiers | A standing for each podcaster, from new podcaster to town legend. Tips are matched to standing. Robbery, mugging and car theft, with lying culprits and accomplices whose false alibis sink any episode that cites them. |
| 4. Districts and the loop | Crime and fear tracked per street. Watches form when enough culprits have been exposed, and push crime elsewhere. Neglected streets breed new offenders. A small district map. |
| 5. Major cases | An occasional death as a town event. The time is given as a randomized window, several people have motives, the town talks soberly, and there is no gore. |
| 6. Drifting hearsay | Gossip between residents may drift and embellish. Hearsay that has drifted from the witness's account becomes unreliable evidence. |

### Rulings made during the build

- **Cold cases:** a case gone cold still reveals its culprit and treats them as exposed. It calms nothing and never earns a watch, so only solved cases calm a street, and an ignored town slowly gets worse. Simulations backed this choice: with this rule, a town with no podcasters breeds offenders in 46% of runs and forms no watches.
- **Major cases:** to make them reachable, towns are generated with enough rivalries. A serious offender, or failing that a petty one, can be promoted when a podcaster reaches the top tier.
- **Offenders:** at most a quarter of the town can ever have offended. Watch founders never turn.
- **Petty cases:** one is always open, so a new podcaster always has a case.

## How it was tested

1. **Unit tests:** 877 pass, with 9 skipped because they need a live Contex. Ruff and `node --check` pass. Every fix has a test that failed first.
2. **Reviews:** an independent reviewer checked each stage before the next began. Between them the reviews found 14 Important issues, all fixed, including:
   - a "you named them" tag that gave away the culprit;
   - a death's time window that gave away its true part of the day, in five separate places;
   - a cold-case reveal that named a hidden offender;
   - arrests that could remove a witness an open case still needed.
3. **Simulations of the district loop:** 400 runs of the real `Districts` class, plus 40 runs of 11 game days with the real case and offender classes. These set how cold cases behave and the cap on offenders.
4. **Live playtest 1:** town `lt28b`, 11 game days, four podcasters. It used real Jev and Haiku against a live Contex, driven by a scripted podcaster through the API, with browser checks for the page and the tutorial. 26 held cases. 14 fixes during play, then 6 more afterwards.
5. **Live playtest 2:** town `lt28c`, a fresh town, 12 game days. 40 held cases, including 2 deaths. 10 fixes during play, then 5 more afterwards, plus a sober closing line for solved deaths.

Leak scans recorded 267 page responses in the first playtest and 349 in the second, covering state, cases, people cards and live updates. None contained an offender, a resident's tier, raw district numbers, tie warmth or which evidence is true.

## The ripples observed

All of these are from the live towns, with evidence in the detailed log.

- **Exposure:** an exposed petty culprit, Priya Raman, stayed in the people list tagged with what she did. She refused the podcaster who exposed her and gave others guarded answers. Her victim posted thanks.
- **Arrests:** 13 in each town. Each one posted "was arrested and has left town", and someone moved in within seconds, with a job, a home and ties. Newcomers sometimes became offenders, and only the save file shows which.
- **Watches:** under its watch, Elm Street's crime level fell from 1.00 to 0.30. With watch weighting in place, Elm took 2 of 11 new crimes, against 8 of 13 before. In playtest 2, Maple Street's watch took its crime from 0.65 to zero, then wound down.
- **Standing:** one podcaster went from New podcaster to Known in town to Town legend, and serious tips reached only them. A newcomer playing at the same time saw petty tips only.
- **The wrongly accused:** a resident named by mistake, Eugene Mott, was tagged "you named them" and refused that podcaster.
- **Deaths:** Dolores Finch's death was worked with ordinary questions and the episode held, naming Gordon Pike. The news, posts, replies and verdict all kept the cozy rules.

## Spend

Both playtests cost well under a dollar in model calls, by the game's own estimate:

| Playtest | Spend | Model use |
|---|---|---|
| 1 | about $0.06 | town generation, newcomers, interviews and town talk |
| 2 | about $0.09 | Haiku 262k in / 59k out; Jev 817k in / 187k out |

## Still open

- **Watches everywhere.** From about day 5 of a busy town, every street has a watch, so the "a watch pushes crime elsewhere" ripple stops showing. One fix is to let watches wind down sooner without fresh exposures, or to cap how many can be active at once.
- **The day count in talk.** Residents occasionally mention the game's day count, as in "it's day six now".
- **"When did you last see her?"** has no question type yet.
- **Word-list limits.**
  - The checks for invented names and places miss a bare unknown first name ("Gary said…").
  - The method-word list can drop a harmless line ("smashed it").
  - Job-to-place matching is a keyword list.
- **Distinct offenders still track case volume.** Every serious culprit is arrested and replaced, so the cap limits how much of the current town has offended, not the total number of offenders over time.
- **Not yet replayed live:** the fixes made after playtest 2 (made-up people, an always-open petty case, relationship questions, window wording, repeated retellings, the line for solved deaths) are covered by tests but haven't been played in a live town.

## Recommended next steps

1. Play a few cases yourself on a freshly generated town. The tutorial, the first town case and the first exposure are the moments that most need to feel good.
2. Decide how watches should wind down, the one open design question.
3. Merge PR #1 when you're happy with it, then switch the hosted Sleuth service to `main`.
