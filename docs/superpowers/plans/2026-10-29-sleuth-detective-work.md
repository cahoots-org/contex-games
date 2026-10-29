# Sleuth Detective Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sleuth's cases detective work: subtler witnesses, cases with no witness, conflicting evidence with innocent liars, a judge that forgives one stray piece, and a short note on why an episode failed.

**Architecture:** Sightings become ranged and partial, compared through one `fits()` in `traits.py`. Case opening (`Cases._open`) stages true evidence, makes it solvable with traces and records before witnesses, then stages false evidence in a new `falsehoods.py` and checks that each false piece has a disproof on file. The judge (`episode.py`) and the wrong-episode note read `Record.sound` and the new `Record.disproof`.

**Tech Stack:** Python 3.12, pytest (`uv run --with-requirements requirements-dev.txt python -m pytest sleuth -q`), ruff, the page in `sleuth/static/index.html`.

**Spec:** `docs/superpowers/specs/2026-10-25-sleuth-design.md`, section "Addendum, 2026-10-29: detective work". Read it, and the earlier addenda for the facts-versus-flavor rule.

## Global Constraints

- Code owns every case fact. Haiku only phrases; Jev only judges. No new fact may come from a model reply.
- No religion anywhere; nothing involving children; no gore; deaths stay offstage.
- The API never reveals `sound`, `disproof`, a liar, a secret before it's exposed, an offender, or which evidence is true. `record_json` stays the only shape a record leaves the server in.
- The tutorial's case (`sleuth/tutorial.py`) stays a fixed checklist: one witness, no false evidence, as today.
- Every resident's fixed look stays unique (`assign_traits`, `assign_look`).
- Bump `STATE_VERSION` in `sleuth/persist.py` once, in the first task that changes saved shapes (Task 2); later tasks that add saved fields bump it again.
- Small CI-green commits, test first. Run the whole suite and `ruff check sleuth` before each commit, with `set -o pipefail` when piping.
- Copy is plain and in-world. Never meta wording ("this is a false clue").

## Review Focus

1. **A case that can't be made solvable or can't disprove a fake is never opened.** `_open` returns False and the next tick tries again; no half-staged case leaks into `files`. Test in Task 6.
2. **Ranged sightings never contradict a value they include.** "Not tall" beside "short" is consistent; "not tall" beside "tall" contradicts. Test in Task 8.
3. **Old saves.** A save from before a shape change is set aside, the town kept, as today. Test in Task 2.
4. **The wrong-episode note never names the culprit or quotes evidence the podcaster hasn't found** while a town case is open. Test in Task 9.
5. **An innocent liar's secret stays hidden until they're named.** Talk, posts and the people list carry nothing of it before. Test in Task 7.

---

### Task 1: Ranged sightings and one `fits()`

**Files:**
- Modify: `sleuth/traits.py`, `sleuth/case.py:391-407`
- Test: `sleuth/tests/test_traits.py`, `sleuth/tests/test_case.py`

**Interfaces:**
- Produces: `RANGES: dict[str, tuple[str, ...]]` in `traits.py`, each key a phrase a witness says, each value the trait values it covers; `fits(seen: dict[str, str], looks: dict[str, str]) -> bool`, true when every seen value equals the look's value or is a `RANGES` key covering it. `describe()` and `figure()` print a ranged value as its key.
- `RANGES` values to use: `{"not tall": ("short", "average height"), "not short": ("average height", "tall"), "darkish-haired": ("dark-haired", "red-haired"), "fair-haired": ("blond", "grey-haired"), "in a dark coat": ("black puffer", "denim jacket", "grey hoodie"), "in a bright coat": ("green raincoat", "plaid flannel"), "with a car": ("red pickup", "white sedan", "blue hatchback", "silver minivan")}`. A ranged value is stored under its category (`{"height": "not tall"}`), and `PHRASES` formatting skips the "in a"/"with a" prefix when the key already carries it.

- [ ] **Step 1: Failing tests**

```python
def test_a_ranged_sighting_fits_every_value_it_covers():
    assert fits({"height": "not tall"}, {"height": "short", "hair": "bald"})
    assert fits({"height": "not tall"}, {"height": "average height"})
    assert not fits({"height": "not tall"}, {"height": "tall"})
    assert fits({"hair": "bald"}, {"hair": "bald"}) and not fits({"hair": "bald"}, {"hair": "blond"})

def test_a_ranged_sighting_is_described_as_said():
    assert describe({"height": "not tall", "coat": "in a dark coat"}) == "not tall, in a dark coat"
```

In `test_case.py`: `test_suspects_narrow_on_a_ranged_sighting` — a town where two residents are short and one tall; a memory `{"height": "not tall"}` leaves exactly the two short ones in `suspects()`.

- [ ] **Step 2:** Run; expect failures on the missing `fits`/`RANGES`.
- [ ] **Step 3:** Add `RANGES` and `fits`; use `fits` in `points_at`, `suspects` and `assign_look` in place of `items() <=`.
- [ ] **Step 4:** Whole suite green, ruff clean.
- [ ] **Step 5: Commit** "Let a sighting cover a range of looks".

---

### Task 2: Gender as a fixed trait

**Files:**
- Modify: `sleuth/traits.py`, `sleuth/town_gen.py`, `sleuth/arrivals.py`, `sleuth/persist.py`, `sleuth/tutorial.py` (its fixed residents get a gender)
- Test: `sleuth/tests/test_traits.py`, `sleuth/tests/test_town_gen.py`, `sleuth/tests/test_arrivals.py`, `sleuth/tests/test_persist.py`

**Interfaces:**
- `TRAITS["gender"] = ("man", "woman")`; `FIXED = ("gender", "height", "hair", "car")`; `IN_PERSON` gains `"gender"`; `BY_WORD` does not (people don't describe someone they know by gender). `PHRASES["gender"] = "{}"`, and `describe` puts it first: "a woman, tall, red-haired".
- Generation asks Haiku for `gender` ("man" or "woman", matching the name) on each resident, required in `REQUIRED`, validated against `TRAITS["gender"]`. `assign_traits` and `assign_look` keep a resident's gender and deal or pick only the other fixed categories; uniqueness is over the whole fixed look.
- `STATE_VERSION` 38 → 39.

- [ ] **Step 1: Failing tests**
  - `test_generated_residents_keep_their_gender` — `assign_traits` on residents with genders set leaves every gender unchanged and every fixed look unique.
  - `test_a_resident_without_a_valid_gender_is_rejected` — the generation validator rejects `"gender": "robot"` and a missing gender.
  - `test_someone_moving_in_keeps_the_gender_they_were_written_with` — `move_in` with Haiku returning `"gender": "woman"`.
  - `test_a_save_from_before_gender_is_set_aside` — a version-38 state loads as None, as other old saves do.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. The prompt line: "gender (\"man\" or \"woman\", matching the name)". Update `RESIDENT` fixtures in tests that build residents.
- [ ] **Step 4:** Whole suite green.
- [ ] **Step 5: Commit** "Give every resident a gender a witness can see".

---

### Task 3: Witnesses see less

**Files:**
- Modify: `sleuth/case.py` (`witness_memories`, `victim_memory`, `recall_more`, `make_solvable`, `_memory_text`), `sleuth/town.py`
- Test: `sleuth/tests/test_case.py`

**Interfaces:**
- `Town.sighting(vid: str, day: int) -> dict[str, str]`: `looks()` plus `"headed": <their home street>`. Everything that compares a sighting to a resident (`points_at`, `suspects`, `make_solvable`, `assign_look`'s avoid list) uses `sighting`; `looks()` stays as is for the page.
- `SEEN_AS = ("gender", "height", "hair", "coat", "car", "headed")`: what a witness can notice. `describe` prints `headed` as "headed toward Oak Street".
- `witness_sees(culprit: dict[str, str], rng: Random) -> dict[str, str]`: one category from `SEEN_AS`; with `RANGED_CHANCE = 0.4`, a `RANGES` key covering the value instead, when one exists. Replaces the two-trait draw; `WITNESS_TRAITS` goes.
- A car-only sighting reads "someone drove off in a red pickup" (`_memory_text` when the only seen category is `car`).
- `recall_more` adds one exact category the memory lacks, or sharpens a ranged value to the exact one.
- `make_solvable`'s witness fallback (until Task 4 replaces it) adds a witness who saw one category per needed narrowing, exact values.

- [ ] **Step 1: Failing tests**
  - `test_a_witness_sees_one_thing` — over 200 seeds, every memory from `witness_memories` has exactly one category, from `SEEN_AS`, and fits the culprit.
  - `test_some_witnesses_see_a_range` — over 200 seeds, at least one memory value is a `RANGES` key, and none contradicts the culprit.
  - `test_headed_toward_narrows_by_home_street` — a sighting `{"headed": "oak street"}` leaves only Oak Street residents in `suspects`.
  - `test_a_trusting_witness_sharpens_a_range` — `recall_more` on `{"height": "not tall"}` for a short culprit gives `{"height": "short"}`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Whole suite green; update tests that assumed two traits per witness.
- [ ] **Step 5: Commit** "Let a witness see one thing, sometimes only roughly".

---

### Task 4: Evidence before witnesses, and cases with none

**Files:**
- Modify: `sleuth/case.py` (`make_solvable`, `camera_clip`, new `passing_clip`), `sleuth/cases.py` (`_open`), `sleuth/config.py`
- Test: `sleuth/tests/test_case.py`, `sleuth/tests/test_cases.py`

**Interfaces:**
- `NO_WITNESS = {"petty": 0.3, "serious": 0.6, "major": 1.0}`: the chance a case stages no witness memories (a mugging's victim still remembers one thing). A death never has an ordinary witness.
- `passing_clip(crime: Crime, town: Town, ids: Ids, rng: Random) -> Record | None`: a camera at a `CAMERA_PLACES` place in the scene's district (`district_of`), other than the scene, catching the culprit's car `rng.randint(3, 12)` minutes after the crime: "7:42pm, Elm Street camera: a red pickup heading away from the library." Traits `{"car": value}`. None when the culprit's car is a bicycle or the district has no other camera.
- `make_solvable(crime, records, town, routine, rng, ids, away, allow_witness: bool) -> list[Record] | None` narrows with, in order: a scene trace of a category not yet seen (`TRACES` kinds), a `passing_clip`, a store receipt and its log, then, only when `allow_witness`, a witness who saw one category. Each step is added only if it narrows `suspects`. It considers only `sound` records. Returns `[]` when nothing is needed, None when it can't narrow to the culprit.
- `allow_witness` is False when the case drew no witness, and always for a death.

- [ ] **Step 1: Failing tests**
  - `test_a_case_without_witnesses_is_solved_from_traces_and_records` — with `NO_WITNESS` forced to 1.0, 50 seeded cases each open with no `memory` records from bystanders and `suspects()` of their sound records is exactly the culprit.
  - `test_traces_come_before_witnesses` — a case whose clues already narrow to three suspects gets a trace or clip from `make_solvable`, not a memory, when one narrows.
  - `test_a_passing_camera_sees_only_the_car` — `passing_clip` text names the car and the direction away from the scene and has no other category.
  - `test_a_death_has_no_ordinary_witness` — 30 staged deaths, no bystander memories.
  - `test_unsound_records_never_narrow_suspects` — a record with `sound=False` doesn't change `suspects()`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement; `_open` draws `no_witness = rng.random() < NO_WITNESS[tier]` before staging.
- [ ] **Step 4:** Whole suite green.
- [ ] **Step 5: Commit** "Solve a case from traces and records before witnesses".

---

### Task 5: People who know someone know their habits

**Files:**
- Modify: `sleuth/player.py` (`_known`, the `where_was` branch), `sleuth/interview.py` (the `where_was` description gains "or where they usually are")
- Test: `sleuth/tests/test_player.py`

**Interfaces:**
- When a resident is asked where someone they're `acquainted` with was, and has no word or meeting to give, they say where that person usually is in the asked part of the day, from `routine.place`: statement text `"{name} says {about} is usually {at(place)} in the {phase}."`, `sound=True`, `who=about.id`. A housemate asked about the crime's night keeps today's household word.
- Strangers say nothing, as today.

- [ ] **Step 1: Failing tests**
  - `test_a_friend_says_where_someone_usually_is` — routed `where_was` about a tie, evening, no meeting → one statement with the routine's evening place.
  - `test_a_stranger_knows_nothing_of_someone_s_habits` — same question about someone not acquainted → no records.
  - `test_a_housemate_still_gives_their_word_for_the_night` — the household word wins over the habit.
- [ ] **Step 2–4:** Run, implement, whole suite green.
- [ ] **Step 5: Commit** "Let people who know someone say where they usually are".

---

### Task 6: Staged false evidence

**Files:**
- Create: `sleuth/falsehoods.py`
- Modify: `sleuth/case.py` (`Record.disproof: str | None = None`), `sleuth/cases.py` (`_open`), `sleuth/persist.py` (bump)
- Test: `sleuth/tests/test_falsehoods.py` (new), `sleuth/tests/test_cases.py`

**Interfaces:**
- `FALSE_COUNT = {"petty": (0, 1), "serious": (1, 2), "major": (2, 3)}`, inclusive bounds; petty draws 1 with `PETTY_FALSE_CHANCE = 0.2`, else 0.
- `stage_false(crime: Crime, records: list[Record], town: Town, routine, rng: Random, ids: Ids, away: set[str], count: int) -> list[Record] | None`. Each false record has `sound=False` and `disproof` set to the id of a sound record in `records` (or in the returned list) that contradicts it. None when it can't stage `count` fakes with disproofs.
- Kinds, each picked when the case has what disproves it:
  - **mistake:** a bystander's memory of one category, with a wrong value, at a scene whose `camera_clip` or a sound trace shows the right one; disproof is that clip or trace. Clock and wording as a real memory.
  - **leftover:** a trace at the scene of a decoy's look, where the decoy's own log puts them at the scene earlier in the phase (`logs()` at a logging scene); disproof is that log, whose clock is at least 30 minutes before the crime.
- **Aimed or noise:** with `AIMED_CHANCE = 0.5`, a fake's wrong value fits a decoy, preferring someone in `motives(town, crime.victim)`; otherwise any wrong value.
- `_open` stages fakes after `make_solvable`, adds them, and checks the guarantee: `suspects()` of sound records is still exactly the culprit, and every false record's `disproof` is a record in the file that a podcaster can get (a clue, clip, log or memory). If not, `_open` returns False.
- Fake memories are told to their witness like real ones (`_remember`), so they say it in talk.
- **Cover stories:** an accomplice is kept only when the place they'll claim the culprit was at has a log or camera on file for the crime's phase that leaves the culprit out; otherwise the case has no accomplice. That record is the accomplice word's disproof (`accomplice_word` statements get `disproof` set when made).

- [ ] **Step 1: Failing tests**
  - `test_every_fake_has_a_disproof_on_file` — 100 serious cases: each `sound=False` record has a `disproof` id in `file.records` whose traits contradict it.
  - `test_fakes_never_change_who_the_true_evidence_points_to` — same cases: `suspects()` of sound records is `{culprit}`.
  - `test_a_leftover_was_left_before_the_crime` — its disproof log clock is at least 30 minutes before the crime.
  - `test_an_aimed_fake_fits_an_innocent_with_a_motive_when_there_is_one`.
  - `test_a_case_that_cannot_disprove_its_fakes_does_not_open` — `stage_false` returning None makes `_open` False and leaves `files` unchanged.
  - `test_the_tutorial_case_has_no_fakes`.
  - `test_an_accomplice_s_word_is_disproved_by_a_record_on_file`.
  - `test_record_json_never_says_whether_a_record_is_sound` — no `sound` or `disproof` key.
- [ ] **Step 2–4:** Run, implement, whole suite green.
- [ ] **Step 5: Commit** "Stage false evidence that something on file disproves".

---

### Task 7: Innocent liars and their secrets

**Files:**
- Create: `sleuth/secrets.py`
- Modify: `sleuth/cases.py` (`CaseFile.liars: dict[str, dict]`, `_open`, `on_wrong`), `sleuth/alibi.py` (`claim`), `sleuth/player.py` (`_known`: `where_was` about a liar from their exposer), `sleuth/persist.py` (bump)
- Test: `sleuth/tests/test_secrets.py` (new), `sleuth/tests/test_alibi.py`, `sleuth/tests/test_cases.py`

**Interfaces:**
- `SECRETS`: a catalog of kinds, each `(reason, exposer)`. Use these five:
  - `"somewhere"`: "at {place} when they'd said they were home", exposed by the place's log or camera, so the liar's true place must be a `LOG_PLACES` or `CAMERA_PLACES` place in `whereabouts`;
  - `"surprise"`: "planning a surprise for {tie}", exposed by a co-conspirator (another tie of the liar, with them in `whereabouts`) who says so when asked where the liar was;
  - `"job"`: "interviewing for a job at {place}", exposed by a coworker (same workplace) who says so;
  - `"hobby"`: "at a {hobby} class they'd rather no one knew about", held at the gym or the library and exposed by its log; hobbies `("line dancing", "pottery", "magic tricks", "competitive yo-yo")`;
  - `"covering"`: "covering for {friend}, who'd been up to something small", exposed by the friend, who admits it when asked where the liar was.
- `pick_liar(crime, file_whereabouts, town, routine, rng, barred) -> tuple[str, dict] | None`: a resident not the culprit, victim or a witness, with a secret whose exposer exists; the dict holds `kind`, `place` (true), `claimed` (a different place, their home when unsure), `exposer` (a vid or record id) and `text` (the full secret sentence).
- Chance: serious cases get a liar with `LIAR_CHANCE = 0.5`; a death always gets one among `file.motives`; petty never.
- `claim(file, vid, routine)` returns `([secret["claimed"]], False)` for a liar.
- Asked where the liar was, the exposer says it: a statement with `sound=True`, `who=liar`, text from the secret. A `somewhere` or `hobby` liar's place records are already in the file and disprove the claim.
- `on_wrong` naming a liar posts the secret on the app ("{name} wasn't home that night: {text}.") and they hold it against the podcaster as any wrongly accused resident does today.

- [ ] **Step 1: Failing tests**
  - `test_each_secret_kind_has_someone_or_something_to_expose_it` — for each kind, a town built to fit it gives a liar whose exposer is in town or on file.
  - `test_a_liar_claims_somewhere_they_were_not` — `claim()` returns the claimed place and False.
  - `test_the_exposer_gives_the_liar_away_when_asked` — routed `where_was` about the liar to the exposer → a sound statement with the secret.
  - `test_naming_a_liar_brings_out_their_secret` — `on_wrong` with the liar posts the secret and cools them toward the podcaster.
  - `test_a_secret_stays_hidden_until_named` — before `on_wrong`, no feed event, page payload or `known_json` contains the secret's text.
  - `test_a_death_has_a_liar_among_those_with_motives`.
- [ ] **Step 2–4:** Run, implement, whole suite green.
- [ ] **Step 5: Commit** "Give some cases an innocent liar with a secret".

---

### Task 8: An episode survives one stray piece

**Files:**
- Modify: `sleuth/episode.py`
- Test: `sleuth/tests/test_episode.py`

**Interfaces:**
- `contradicts(a: Record, b: Record) -> bool`: true when either's `disproof` is the other's id, or they share a category whose values can't both fit one look (exact values differ, or a range excludes the other's value; two overlapping ranges don't contradict).
- `holds(crime, culprit, looks, cited)`: names the culprit; at least one sound cited record `points_at` them; at most one cited record is unsound; that one contradicts no other cited record; all cited are from this case.

- [ ] **Step 1: Failing tests**
  - `test_one_stray_piece_that_clashes_with_nothing_still_holds`
  - `test_two_false_pieces_sink_it`
  - `test_a_false_piece_cited_beside_what_disproves_it_sinks_it` — green-raincoat memory with the black-puffer clip.
  - `test_overlapping_ranges_do_not_clash` — "not tall" with "short".
  - `test_a_false_piece_alone_never_holds` — the only pointing evidence is false.
- [ ] **Step 2–4:** Run, implement, whole suite green.
- [ ] **Step 5: Commit** "Let an episode survive one stray piece of evidence".

---

### Task 9: A short note on why an episode failed

**Files:**
- Modify: `sleuth/episode.py` (new `why_wrong`), `sleuth/player.py` (`publish`: verdict and the tutorial handoff), `sleuth/static/index.html` (show the note under the verdict)
- Test: `sleuth/tests/test_episode.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`

**Interfaces:**
- `why_wrong(crime, named: str, cited: list[Record], notebook: dict[str, Record], town: Town) -> str`, one sentence:
  - a cited false piece, its disproof in the notebook: "{label of the false piece}: {label of the disproof}." e.g. "Tess's green raincoat: the library camera shows a black puffer."
  - its disproof not in the notebook: "{label of the false piece}: a {source kind} says otherwise.", source kind one of "camera", "log", "witness", "trace", "account".
  - all cited sound but named the wrong person: "Your evidence was sound, but it doesn't point at {named}."
  - right person, nothing cited points at them: "Nothing you cited points at {named}."
  - Labels: memory "{first name}'s {value}"; clue "the {trace noun} {at place}"; clip "the {place} camera"; log "the {place}'s {log noun}"; statement "{first name}'s word".
- The note never names the culprit of an open town case. The tutorial's handoff keeps naming its culprit.
- `publish` passes the note as the verdict's second line for a wrong town episode, the podcaster's own feed only.

- [ ] **Step 1: Failing tests**
  - one test per bullet above, asserting the exact sentence;
  - `test_the_note_never_names_the_culprit_of_an_open_case` — over cases where the podcaster named the wrong person, the culprit's name is not in the note;
  - `test_only_the_author_sees_the_note` — other players' feeds carry no note.
- [ ] **Step 2–4:** Run, implement, whole suite green; check the page shows the note under "Your episode didn't hold up." on desktop and at 390px wide.
- [ ] **Step 5: Commit** "Tell a podcaster briefly why their episode failed".
