# Sleuth: A Living Town, Rising Stakes and Consequences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shared town feel alive and connected. Residents have quirks and a voice on the app. Crimes come from a small hidden set of offenders and escalate from petty to serious to major as a podcaster's standing grows. Exposure, arrests, newcomers and wrongful accusations all have consequences. Three districts track crime and fear, organize watches, push crime elsewhere and, when neglected, breed new offenders. Talk drifts as it's retold.

**Architecture:**
- `case.CRIMES` is a catalog of crime kinds with tiers.
- `offenders.Offenders` is the hidden culprit set. It lives on `Cases` and is saved with it, so the practice town gets an empty one for free.
- `districts.Districts` is a new engine component, saved separately, holding per-street crime, fear and watch state. `Cases` gets a reference to it.
- Town-side consequences of an episode move from `Player.publish` into `Cases.on_held` and `Cases.on_wrong`.
- `arrivals.move_in` replaces anyone who leaves.
- `Player` gains `standing` and a chosen `case_id`. Every action works on `Player.current()`.
- Code writes every fact and every announcement. Haiku writes resident flavor (quirks, app posts, drift), behind a single facts guard, `writer.invents_facts`.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio, ruff, one static `sleuth/static/index.html`, Contex (MCP), Jev (typesafe_sdk), Haiku.

**Spec:** `docs/superpowers/specs/2026-10-25-sleuth-design.md`, section "Addendum, 2026-10-28: a living town, rising stakes and consequences". Read the earlier addenda (2026-10-26 and 2026-10-27) for context. `sleuth/README.md` describes today's game. Whispers' groups and newcomers (`whispers/models.py` `Group`, `whispers/population.py`, `whispers/town_gen.py` `generate_newcomer`) are read-only references. Never import from `whispers`.

## Global Constraints

- **Branch:** `feat/sleuth` in `/Users/robmiller/Projects/contex-games`. No worktrees. Touch only `sleuth/`.
- **Ports:** never use 8765. Use `SLEUTH_WEB_PORT=8790` for manual and playtest runs.
- **Test command:** `PYTEST` = `set -o pipefail; /private/tmp/claude-501/-Users-robmiller-Projects-contex/dc5af79c-d8f0-4711-83c2-3ccea8efac2d/scratchpad/venv-web/bin/python -m pytest sleuth -q -p no:cacheprovider | tail -3`. For red/green steps, drop the `| tail -3` and add `-k <name>`. The baseline is 597 passed, 9 skipped.
- **`NODECHECK`:** `sed -n '/^<script>$/,/^<\/script>$/p' sleuth/static/index.html | sed '1d;$d' > "$TMPDIR/page.js" && node --check "$TMPDIR/page.js"`
- **`VERIFY`:** `PYTEST` (all pass), `ruff check .` from the repo root (clean), and `NODECHECK` (no output). Run all three before every commit.
- **Commits:** one per task, with the exact message given. Each must pass CI, and the game must still play after it. Every message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01YP7uhbQm8avkDcwdQ9b87E
  ```
- **Style:** concise docstrings, no inline imports, no meta comments, nothing clever. Use names that match the code around them ("resident", "town", "podcaster").
- **Never send hidden state to the browser:** who the offenders are, offender tiers, escalation or quiet state, raw district numbers, warmth, `sound`, accomplices, unlearned looks. The exceptions are only what this plan makes public: exposures, arrests, watches and district levels.
- **Copy:**
  - No religion anywhere. `sleuth/faith.py` `FAITH` and `test_copy.py` stay green. Every Haiku output that reaches the page or a mind (quirks, app posts, talk) is checked against `FAITH`, and against `GORE` once Task 18 adds it.
  - `test_copy.MEDIEVAL` still bans "village(r)s", "lamps" and "newcomer(s)". Say "moved in".
  - `test_copy.META` still bans tutorial talk.
  - Nothing involving children, no sexual violence, no gore. A death happens offstage and is never a joke.
- **Saves:** every task marked **(bumps STATE_VERSION)** raises `sleuth/persist.py` `STATE_VERSION` by one. An old save is set aside, which is fine.
- **Costs:**
  - An interview still costs at most one Jev call and one Haiku call.
  - New model calls are allowed only here:
    - app chatter: at most one Haiku call per part of the day;
    - each resident moving in: one Haiku call and one Jev call.
  - Watches and district reactions are code copy with no model calls.
- **Tutorial:** `sleuth/tutorial.py` and its tests stay unchanged in behavior. `test_tutorial.py` and the web tutorial tests pass untouched. The practice town's `Cases` has an empty `Offenders` and no `Districts`.
- **README:** each task updates the README lines its behavior changes, in the existing voice, and adds its config fields to the Settings table.

## Decisions (where the addendum leaves room)

1. **Facts guard.** `writer.invents_facts(line, allowed, firsts)` is the single guard for case facts. It flags:
   - a look or clothing word not in `allowed`;
   - a time not in `allowed`;
   - a resident not in `allowed` who is placed or sighted in the same sentence;
   - a gendered pronoun for an unknown someone.

   Bare names, places, animals, opinions, theories and tangents all pass. Testimony from records keeps its stricter checks (`conveys`, `first_hand`, `adds_looks`, `misdated`).
2. **Quirks.** `Villager.quirks` holds one or two phrases, generated with the town. Old seeds load with `[]`. Tutorial residents stay quirk-less.
3. **App chatter is page-only.**
   - A post is chosen by code: a random resident with quirks, and a kind out of lost pet, passive-aggressive note, gripe, and a theory (only while a case is open).
   - Haiku phrases it. It is posted with chance `chatter_chance` at each part-of-day tick while someone plays.
   - Posts are not delivered to minds.
4. **Catalog shape.** `case.Kind(tier, did, items, found, seen, news, title)` sits in `case.CRIMES`, keyed by the existing template names, so saves and the tutorial's `"steal"` keep working.
   - Petty adds salt, moustache, goose and gnome.
   - Serious (Task 11): rob, mug, car.
   - Major (Task 17): death.
5. **Offenders are hidden and own every crime.**
   - The set starts at `offenders` (5) random residents.
   - Only active, not-quiet offenders at a crime's tier can be its culprit.
   - Solvability still narrows among *all* residents, so the set never helps or hurts deduction.
   - An offender who escapes `escalate_after` (2) cases moves up a tier, but only to a tier the catalog has.
   - When a tier is wanted and nobody holds it, the lower-tier offender with the most escapes is promoted.
6. **Petty exposure.**
   - It is public. `Offenders.exposed[vid]` holds what they did, shown as a tag in the people list and given to Haiku when they're named.
   - The exposing podcaster drops to `reputation_exposed` (−0.6) with the culprit, below `guarded_at`, so they refuse. Other podcasters find the culprit cold through a writer note.
   - The culprit is quiet for `exposed_quiet_days` (2), then each morning reforms with `reform_chance` (0.3) or stays an offender who may reoffend.
   - The victim and their household gain `reputation_ally` (+0.3) toward the exposing podcaster. The victim posts thanks on the app.
7. **Arrests and moving in.**
   - Serious and major culprits are arrested when exposed and leave at once.
   - Witnesses are never drawn from culprits of other open cases, so an arrest never removes testimony.
   - Nobody moves away by choice.
   - Each departure (arrest or death) brings one new resident onto the same street, in a new household, with two ties, unique looks, a wardrobe and a routine. They become an offender with `newcomer_offender_chance` (0.3) while the set is below `max_offenders`.
   - Population never exceeds `population`.
8. **Wrongly accused.** Besides today's `reputation_accused`, their household and close ties (warmth ≥ 0.6) lose `reputation_accused_ties` (−0.3). `CaseFile.named[player] = vid` records who each podcaster named. Interviews tell Haiku about it, and the people list marks "you named them".
9. **Standing.**
   - `Player.standing` is an integer. A held episode adds 1, 2 or 3 points (petty, serious, major). A wrong one subtracts 1, with a floor of 0.
   - Tiers: serious at `serious_at` (3), major at `major_at` (6).
   - Standing is per run, saved with the run. The practice case never moves it.
10. **Several open cases: one shared case per tier at most.**
    - Petty is always wanted. Serious is wanted while an active podcaster has reached it. Major is wanted the same way, and at most once per `major_every_days`.
    - A podcaster is offered every open case at or below their tier.
    - `Player.case_id` picks the one they're working, defaulting to the highest tier offered. Every action (interview, pull, search, save photo, publish) uses it.
11. **Serious evidence.**
    - The culprit is never a regular at the scene, so they always lie about where they were. There are up to 3 witnesses.
    - A mugging's victim holds a one-trait memory.
    - With chance `accomplice_chance` (0.5), an accomplice (the culprit's closest tie, or another offender) gives an unsound "was with me" word. On a held episode the accomplice is exposed as having covered for the culprit, and is not arrested.
12. **Districts are the streets.**
    - Elm: cafe, bar, dog park. Oak: gym, school, library. Maple: hardware store, grocery, town hall.
    - Crime and fear are floats in [0, 1]. A crime raises both by 0.25, 0.45 or 0.7 by tier. An exposure lowers crime by 0.15 and fear by 0.1.
    - Each part of the day crime decays by `district_crime_decay` (0.02) and fear by `district_fear_decay` (0.015).
    - The browser sees only levels 0 to 3, trends since the last morning, and the watch's name and founder.
13. **Watches are the only groups.**
    - A watch forms when fear ≥ `organize_fear` (0.4) and the district has had at least one exposure since it was last organized. It is checked at once on exposure and on every tick.
    - It is one per district, with a code-chosen secular name ("Neighborhood Watch", "Porch-Light Pact", "Group Chat"). The founder is the district's latest victim still in town, else a random resident. Up to 5 members are picked by warmth to the founder, ignoring offender status, so membership proves nothing.
    - Forming is announced on the app and delivered to members' minds through Contex. There are no model calls.
    - A watch winds down once crime and fear both fall below `disband_below` (0.05).
    - Committees and book clubs: not built.
14. **The loop.**
    - Crimes staged at a place in an organized district are weighted by `organized_crime_weight` (0.25), which pushes crime to other districts.
    - Each morning, a neglected district (no watch, crime and fear both ≥ `neglect_at` (0.4)) turns one non-offender, never-exposed resident into a petty offender with chance `turn_chance` (0.5). This stops at `max_offenders` (6).
    - Below `min_offenders` (3), the set is refilled from unorganized districts only.
    - Residents' Jev and Haiku prompts carry their district's mood.
15. **Major case (a death).**
    - At most one is open at a time. The victim is removed at once and can't be questioned. A bystander or household mate holds the discovery.
    - The true phase is the one just finished. The public window spans it and the phase before. Records exist only for the true phase.
    - The victim must have at least 2 residents besides the culprit with negative warmth to or from them. These are kept in `CaseFile.motives` and answer "who had a reason".
    - A major case runs for `major_case_days` (6). The news reaches the victim's district and everyone tied to them.
16. **Drift.**
    - Retold lines (retell, speak, deny, confront and move-share) drop the facts guard, but never claim first-hand sight and never pass `FAITH` or `GORE`. Cover stories and warnings stay strict.
    - Hearsay rooted in a memory is sound only if `invents_facts(heard, root_memory_text, firsts)` is false, so drifted hearsay is unsound evidence. First-hand memories, records and clues never drift.
17. **Playtest oracle.** The playtest reads the truth from the saved state file (fixed `SLEUTH_SESSION`, short `SLEUTH_SAVE_EVERY_SECONDS`). No debug endpoint is added.

## Review Focus

1. **Fairness and solvability with offenders and tiers.**
   - `suspects` and `make_solvable` ignore the offender set.
   - Every opened case of every tier narrows to exactly one resident from intact records.
   - A serious culprit always lies about where they were.
   - An accomplice's word is unsound.
   - The judge's rules are unchanged.
   - A death's window never hides the true phase's logs.

   Tests: Task 5 `test_solvability_still_narrows_among_everyone_not_just_offenders`, Task 11 `test_serious_cases_stay_solvable_across_seeds`, Task 12 `test_citing_the_accomplice_s_word_sinks_the_episode`, Task 17 `test_a_major_case_stays_solvable_across_seeds`.
2. **No leak of offender identity or district internals.**
   - `/api/state`, `/api/case`, `/api/villagers/{vid}` and every feed event are identical whoever the offenders are.
   - District JSON carries only integer levels, trends and the watch's name and founder.

   Tests: Task 5 `test_state_is_the_same_whoever_the_offenders_are`, Task 16 `test_district_json_carries_levels_not_internals`.
3. **Cost bounds.**
   - Moving in costs exactly one Haiku and one Jev call.
   - A watch costs no model calls and at most `WATCH_SIZE` publishes.
   - Chatter costs at most one Haiku call per part of the day.
   - Major news reaches a bounded audience.

   Tests: Task 7 `test_moving_in_costs_one_haiku_and_one_jev_call`, Task 14 `test_forming_a_watch_makes_no_model_calls`, Task 4 `test_the_clock_posts_chatter_only_while_someone_plays`, Task 18 `test_major_news_reaches_the_district_and_the_victim_s_ties_only`.
4. **Save/restore and STATE_VERSION.**
   - Offenders, exposures, `named`, standing, `case_id`, districts, watches, `Crime.tier` and `Crime.window` all round-trip.
   - Residents who moved in survive a restart through the save.
   - Records held by departed residents still render.

   Tests: Task 5 `test_offenders_round_trip_with_the_cases`, Task 7 `test_notebook_entries_from_someone_who_left_still_show_their_name`, Task 9 `test_standing_round_trips_with_the_run`, Task 13 `test_districts_round_trip`, and each bumping task's own round-trip test.
5. **Tutorial unaffected.** The practice case opens, ticks, publishes and hands off as today. It never moves standing, offenders or districts. Tests: the existing `test_tutorial.py` and web tutorial tests unchanged, plus Task 9 `test_the_practice_case_never_moves_standing`.
6. **Copy checks.**
   - No religion in code, prompts or page.
   - No gore once deaths exist.
   - "moved in", never "newcomer".
   - Every Haiku output that reaches the page or a mind passes `FAITH` and `GORE`.

   Tests: Task 1 `test_a_quirk_of_faith_is_rejected`, Task 4 `test_a_post_that_adds_a_case_fact_or_faith_is_dropped`, Task 18 `test_no_gore_in_code_or_copy` and `test_a_line_with_gore_is_never_said`.

---

## Stage 1: Facts versus flavor, and quirks

### Task 1: Resident quirks (bumps STATE_VERSION)

**Files:** Modify `sleuth/models.py`, `sleuth/town_gen.py`, `sleuth/writer.py`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_town_gen.py`, `sleuth/tests/test_writer.py`.

**Interfaces:**
- Produces:
  - `Villager.quirks: list[str] = field(default_factory=list)`.
  - `town_gen.REQUIRED` gains `"quirks"`. `_valid` requires 1 or more non-empty string quirks and no `FAITH` match. `_villager` keeps `quirks[:2]`.
  - `writer._quirks(villager) -> str` returns `f"Your quirks: {'; '.join(v.quirks)}. Let one show when it fits, even about a case. "`, or `""` when there are none. `Writer.say` and `Writer.reply` add it to their system prompts.
- `PROMPT` gains, after needs: `quirks: a JSON array of 1 or 2 short phrases, each a strong, harmless obsession or habit that shows whenever they talk, such as "convinced the dog-park goose is plotting something", "a would-be true-crime expert" or "blames the town council for everything"`.

- [ ] **Step 1: Write the failing tests**

```python
# test_town_gen.py
async def test_generated_residents_carry_one_or_two_quirks():
    # stub writer returns 10 valid residents, one with 3 quirks -> every villager has 1..2 quirks, that one keeps the first 2
async def test_a_reply_without_quirks_is_rejected():
    # an item lacking "quirks" (or quirks == []) is skipped
async def test_a_quirk_of_faith_is_rejected():
    # quirks ["sings in the church choir"] -> skipped
async def test_an_old_seed_without_quirks_still_loads(tmp_path):
    # a saved seed with traits and wardrobes but no "quirks" key -> loads, every v.quirks == []

# test_writer.py
async def test_say_and_reply_prompts_carry_the_residents_quirks():
    # villager.quirks = ["blames the council for everything"] -> that text in the system prompt of both say() and reply()
async def test_a_resident_without_quirks_gets_no_quirk_line():
    # "Your quirks" not in either system prompt
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k quirk`. Expected: FAIL on `quirks`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Update the README's **The town** section: each resident has one or two quirks that show in what they say.
- [ ] **Step 4: Run `VERIFY`.** Expected: all pass.
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Give every resident one or two quirks that show when they talk"`

### Task 2: Guard only case facts

**Files:** Modify `sleuth/writer.py`, `sleuth/effects.py`, `sleuth/player.py`, `sleuth/README.md`. Test `sleuth/tests/test_writer.py`, `sleuth/tests/test_effects.py`, `sleuth/tests/test_player.py`.

**Interfaces:**
- Produces `writer.invents_facts(line: str, allowed: str, firsts: set[str]) -> bool`. It replaces `invents` and `INVENTED`, and `adds_nothing` builds on it. It returns True when the line has any of:
  - `LOOK_WORDS` (every value in `traits.TRAITS`, plus `haired|hood\w*|jacket|coat|tall|short|bald|blond\w*`) not in `allowed`;
  - a time not in `allowed`: `case.misdated(line, allowed)`, or a clock (`\b\d{1,2}(:\d\d)?\s?(am|pm)\b`) not in `allowed`;
  - a sentence naming a first name from `firsts` not in `allowed` together with `PLACED = r"\b(saw|seen|spotted|was (at|on|in|by|near|outside)|were (at|on|in)|hanging around|sneaking)\b"`;
  - a gendered pronoun while `UNKNOWN` matches. This keeps today's rule that a pronoun may refer back to a named resident.
- `CASE_TALK` becomes: `"This is about a case. Say what you think, feel and suspect, in character: opinions, theories, grudges and your quirks are welcome. Never add a fact about the case: no one seen or placed anywhere, no time, no look or clothing, no sighting. "`
- `effects.act.words` uses `invents_facts`.
- `Player._phrase` replaces its `strangers(...)` check with `invents_facts(line, allowed, firsts)`.
- `player.adds_nothing(line, names)` = `bool(line) and not (invents_facts(line, "", names) or WHEREABOUTS.search(_apostrophes(line)))`. It no longer bans digits, place words or bare names.

- [ ] **Step 1: Write the failing tests**

```python
# test_writer.py (replace test_invents_catches_people_genders_animals_and_looks_the_facts_lack)
@pytest.mark.parametrize("line", ["Honestly I blame the council, and Cal's always been a sourpuss.",
                                  "That goose at the dog park knows something.", "Poor Ada, she loved that bike."])
def test_flavor_passes_the_guard(line):
    assert not invents_facts(line, "Ada Reyes's bike", {"Cal", "Ada"})
@pytest.mark.parametrize("line", ["I saw Cal by the library last night.", "It was a tall guy in a hoodie.",
                                  "Around 9pm, I reckon.", "Someone said he ran off."])
def test_case_facts_fail_the_guard(line):
    assert invents_facts(line, "Ada Reyes's bike", {"Cal", "Ada"})
async def test_case_talk_welcomes_opinion_but_no_facts():
    # system prompt of say(on_case=True) contains "opinions, theories" and "Never add a fact about the case"

# test_player.py
async def test_a_reply_with_no_facts_may_grumble_about_a_place_or_a_neighbour():
    # writer line "The council should fix the library roof, and Gus agrees." with nothing known -> used as is
# keep test_a_reply_with_no_facts_that_adds_a_name_place_time_or_look_falls_back_to_a_shrug for its time/look/
# whereabouts params; move its bare-name and bare-place params to the new test as passing lines

# test_effects.py
async def test_case_talk_with_opinion_and_quirk_is_said():
    # writer returns "Typical. I blame the council." on a case-rooted retell -> delivered unchanged
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "guard or grumble or opinion or invents"`.
- [ ] **Step 3: Implement** the interfaces above. Update the tests that pinned the old word list: animals and bare names now pass. Update the README's interview paragraph: residents speak in character, and only invented case facts are swapped for the plain record.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Guard only case facts in what residents say, and let their character through"`

### Task 3: A petty crime catalog worth caring about

**Files:** Modify `sleuth/case.py`, `sleuth/player.py`, `sleuth/README.md`. Test `sleuth/tests/test_case.py`.

**Interfaces:**
- Produces:

```python
NEWS = "Someone {did} {victim}'s {item} {at} {when}."
TITLE = "{victim}'s {item}"

@dataclass(frozen=True)
class Kind:
    tier: str           # "petty" | "serious" | "major"
    did: str            # "stole"
    items: tuple[str, ...]
    found: str          # what the victim finds: "missing"
    seen: str           # what a witness saw the figure do
    news: str = NEWS    # filled with did, victim (full name), item, at, when (WHEN)
    title: str = TITLE

CRIMES: dict[str, Kind]
```

- `CRIMES` replaces `TEMPLATES`, `FOUND` and `WITNESS_ACTION`, keeping today's five entries with their wording. It adds:
  - `"salt"`: `Kind("petty", "salted", ("sugar jars",), "salted", "was fiddling with the jars")`, with `ITEM_PLACES["sugar jars"] = ("cafe", "grocery")`;
  - `"moustache"`: `Kind("petty", "drew a moustache on", ("portrait",), "defaced", "was scribbling on something")`, with places `("town hall", "library")`;
  - `"goose"`: `Kind("petty", "made off with", ("goose",), "missing", "was carrying something that honked")`, with places `("dog park", *STREETS)`;
  - `"gnome"`: `Kind("petty", "kidnapped", ("garden gnome",), "missing", "was carrying something small and pointy")`, with places `STREETS`.
- `Crime.text` is built from `kind.news`, and `stage_crime`, `discovery`, `found_it`, `_memory_text` and `camera_clip` read `CRIMES`. `Player.publish`'s `named` line uses `CRIMES[t].did`.
- Produces `crime_title(crime: Crime, town: Town) -> str`. `case_json` uses it instead of its inline f-string.
- Produces `catalog_tiers() -> tuple[str, ...]`: the tiers that have at least one kind, in `TIERS` order. `TIERS = ("petty", "serious", "major")` lives in `case.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_crime_kind_has_places_for_its_items():
    assert all(item in ITEM_PLACES for k in CRIMES.values() for item in k.items)
def test_the_catalog_is_all_petty_for_now():
    assert catalog_tiers() == ("petty",)
def test_the_goose_case_reads_well():
    # stage_crime with a town whose victim is at the dog park, rng until template == "goose"
    # crime.text == f"Someone made off with {victim.name}'s goose at the dog park {WHEN}."
def test_the_practice_crime_still_reads_as_today():
    # Crime(... "steal", "tote bag" ...) text and title unchanged
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "catalog or goose or crime_kind or practice_crime"`.
- [ ] **Step 3: Implement.** Update the README's crime examples.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Widen the petty crime catalog: salted sugar, a moustached portrait, the goose, a garden gnome"`

### Task 4: App posts with character

**Files:** Create `sleuth/chatter.py`. Modify `sleuth/writer.py`, `sleuth/engine.py`, `sleuth/feed.py`, `sleuth/config.py`, `sleuth/static/index.html` (only if a post with no case needs styling), `sleuth/README.md`. Test `sleuth/tests/test_chatter.py`, `sleuth/tests/test_engine.py`.

**Interfaces:**
- Produces:
  - `config.chatter_chance: float = 0.5`.
  - `chatter.POSTS = {"lost": "a lost-pet or lost-item post", "note": "a passive-aggressive note to the neighbours", "gripe": "a gripe about something in town, true to your quirks", "theory": "your own theory about the open case, as opinion, not fact"}`.
  - `async def chatter(writer: Writer, town: Town, rng: Random, ids: Ids, case_text: str | None) -> Utterance | None`. It picks a random resident with quirks and a kind (`"theory"` only when `case_text`), makes one `Writer.post` call, and returns `Utterance(ids.next("u"), vid, name, v.home, line, None, "posted")`. It returns None when nobody has quirks, the line is empty, or the line matches `FAITH` or `invents_facts(line, case_text or "", firsts)`.
  - `Writer.post(villager: Villager, kind: str, case_text: str | None) -> str`: one Haiku call of `SAY_MAX_TOKENS`, with a system prompt "You are {name}, a {occupation}… You are posting on your town's neighborhood app. Write {kind} in one or two short sentences, in your own voice. {quirks}". When `case_text` is set, the user prompt includes "The open case: {case_text}".
  - `Feed.on_post(utterance, case_id: str | None, player=None)`: `case_id` may now be None.
  - `Engine._chatter()`: called in `_clock_loop` after `_photograph`, only while `players.any_playing()` and `cases.rng.random() < config.chatter_chance`. The open case passed in is the newest open shared case's text said today, or None.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_post_is_one_haiku_call_in_the_residents_voice():
    # stub writer counts calls -> 1 call; the utterance's speaker is a resident with quirks; the quirk is in the system prompt
async def test_a_post_that_adds_a_case_fact_or_faith_is_dropped():
    # writer returns "I saw Cal at the library at 9pm." -> None; "Pray for our town" -> None
async def test_theories_only_while_a_case_is_open():
    # case_text None over 50 seeds -> the kind prompt never contains "theory"
async def test_the_clock_posts_chatter_only_while_someone_plays():   # test_engine.py
    # chatter_chance=1.0: one tick with nobody playing -> no post event and 0 writer calls; with a player -> exactly 1 post
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "post or chatter or theories"`.
- [ ] **Step 3: Implement.** In the README's **How it uses Contex** and **What it costs**, note at most one Haiku call per part of the day for app posts.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Let residents post lost pets, notes, gripes and theories on the neighborhood app"`

---

## Stage 2: Offenders and consequences

### Task 5: The hidden offender set (bumps STATE_VERSION)

**Files:** Create `sleuth/offenders.py`. Modify `sleuth/case.py`, `sleuth/cases.py`, `sleuth/config.py`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_offenders.py`, `sleuth/tests/test_cases.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Produces:

```python
@dataclass
class Offender:
    tier: str = "petty"
    escaped: int = 0
    quiet_until: int = 0      # game day before which they commit nothing

class Offenders:
    def __init__(self, config: Config): ...
    active: dict[str, Offender]       # hidden
    exposed: dict[str, str]           # public: vid -> what the town knows they did ("stole Ada Reyes's bike")
    def to_state(self) -> dict: ...
    def restore(self, state: dict) -> None: ...
    def top_up(self, town: Town, rng: Random, candidates: list[str] | None = None) -> list[str]:
        """Fill active up to config.offenders from candidates (default: every resident) not active and never exposed;
        returns who joined."""
    def ready(self, day: int, tier: str) -> set[str]:
        """Active offenders at tier whose quiet_until <= day."""
    def escaped_with(self, vid: str) -> None:
        """Count a case gone cold; at config.escalate_after move up one tier within catalog_tiers(), reset escaped."""
    def promote(self, tier: str) -> str | None:
        """Move the offender one tier below with the most escapes up to tier."""
    def drop(self, vid: str) -> None: ...
```

- `config.offenders: int = 5`, `config.escalate_after: int = 2`.
- `Crime.tier: str = "petty"`, set from `CRIMES[template].tier`.
- `stage_crime(..., culprits: set[str] | None = None)` keeps only culprits in `culprits` when given.
- `Cases.offenders = Offenders(config)`. `to_state` returns `{"files": [...], "offenders": ...}`, and `restore` reads both.
- `Cases.ensure` calls `offenders.top_up(...)` and then stages with `culprits=offenders.ready(day, "petty")`. With no ready offender, it opens nothing that tick.
- A case going cold calls `offenders.escaped_with(culprit)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_only_offenders_commit_crimes():
    # 40 seeds through Cases.ensure on a 12-resident town -> every crime.culprit in cases.offenders.active
def test_the_set_is_topped_up_to_the_configured_size_from_non_offenders():
    # offenders=3, one exposed resident -> len(active) == 3, exposed vid not in active
def test_an_offender_who_gets_away_twice_moves_up_a_tier_only_when_the_catalog_has_one():
    # escaped_with twice -> tier stays "petty" (catalog petty only); monkeypatch catalog_tiers -> ("petty","serious") -> "serious"
def test_a_quiet_offender_is_not_ready():
    # quiet_until=5 -> not in ready(4, "petty"), in ready(5, "petty")
def test_solvability_still_narrows_among_everyone_not_just_offenders():
    # suspects() for a crime whose clip fits a non-offender too -> that non-offender is in the set
def test_offenders_round_trip_with_the_cases():
    # Cases.restore(cases.to_state()) keeps active (tier, escaped, quiet_until) and exposed
def test_state_is_the_same_whoever_the_offenders_are(game):   # test_web.py
    # same town and case; /api/state JSON with active={v1} equals with active={v2}
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "offender"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. The practice town's `Cases` gets an empty `Offenders` and never stages. In the README, add a short **Offenders** paragraph (only a few residents commit crimes, and nobody can see who) plus the settings.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Keep crime to a small hidden set of offenders who escalate when they get away with it"`

### Task 6: Petty exposure (bumps STATE_VERSION)

**Files:** Modify `sleuth/cases.py`, `sleuth/offenders.py`, `sleuth/player.py`, `sleuth/town.py` (`neighbours`), `sleuth/writer.py`, `sleuth/config.py`, `sleuth/static/index.html`, `sleuth/README.md`. Test `sleuth/tests/test_cases.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_offenders.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Produces:
  - Config: `reputation_exposed: float = -0.6`, `reputation_ally: float = 0.3`, `exposed_quiet_days: int = 2`, `reform_chance: float = 0.3`.
  - `Cases.on_held(engine, file: CaseFile, player_id: str) -> None` and `Cases.on_wrong(engine, file, player_id, accused: str) -> None`. Today's town-side consequences move here out of `Player.publish`: close, reputation and ensure.
  - `on_held` for a petty crime:
    - `offenders.exposed[culprit] = f"{kind.did} {victim}'s {item}"`, and the culprit's `quiet_until = day + exposed_quiet_days`;
    - the culprit's regard for the podcaster is nudged by `reputation_exposed`;
    - the victim and their household are nudged by `reputation_ally`;
    - the victim posts `THANKS = "Got my {item} back thanks to that podcast!"` as an app post with the victim as speaker (`feed.on_post`, `case_id` = the case).
  - `Offenders.new_day(day: int, rng: Random) -> list[str]`: each exposed active offender past `quiet_until` reforms (is dropped) with `reform_chance`. It returns who reformed and is called from `Cases.on_tick` on a morning.
  - `Player.person(vid)` adds `"known_for": offenders.exposed.get(vid, "")`. The page shows it as a tag on the row and the card.
  - `town.neighbours(town, villager, text, exposed: dict[str, str] = {})` appends `f", who everyone knows {what}"`.
  - `Writer.reply(..., notes: Sequence[str] = ())`: each note becomes a line in the user prompt. `Player._phrase` and `_shrug` pass `Player._notes(vid)`:
    - the exposing podcaster gets "This podcaster exposed you for {what}. You're cold with them.";
    - any podcaster gets "Everyone knows you {what}. You're touchy about it.".

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_held_petty_episode_exposes_the_culprit_who_stays_in_town():
    # publish held -> culprit in town, offenders.exposed[culprit] == "stole Ada's bike"-shaped text, culprit quiet
async def test_the_exposed_culprit_refuses_the_podcaster_who_exposed_them():
    # after held publish, interview(culprit) -> Refusal("... won't talk to you.")
async def test_the_victim_and_household_warm_to_the_podcaster():
    # victim and household regard == reputation_right + reputation_ally
async def test_the_victim_thanks_the_podcaster_on_the_app():
    # a "post" event with speaker == victim name and "thanks to that podcast" in its text
def test_an_exposed_offender_rests_then_reforms_or_may_reoffend():
    # reform_chance=1 -> new_day after quiet drops them; reform_chance=0 -> still active and ready
def test_everyone_sees_who_was_exposed_for_what_in_the_people_list(game):   # test_web.py
    # /api/state villagers row for the culprit has known_for; nobody else does
def test_residents_bring_up_an_exposure_when_the_person_is_named():
    # neighbours(..., exposed) entry ends with ", who everyone knows stole ..."
async def test_an_exposed_resident_is_touchy_with_other_podcasters():
    # second player's interview -> writer.reply notes contain "Everyone knows you"
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "exposed or exposure or thanks or warm_to or touchy"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Rewrite the README's right-episode bullet: the culprit is known around town, won't talk to you, and may reform or reoffend; the victim's household warms to you.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Expose petty culprits: known around town, cold to you, and free to reform or reoffend"`

### Task 7: Arrests, and someone moves in

**Files:** Create `sleuth/arrivals.py`. Modify `sleuth/town_gen.py`, `sleuth/traits.py`, `sleuth/cases.py`, `sleuth/case.py` (`record_json`, witnesses), `sleuth/config.py`, `sleuth/README.md`. Test `sleuth/tests/test_arrivals.py`, `sleuth/tests/test_cases.py`, `sleuth/tests/test_case.py`.

**Interfaces:**
- Produces:
  - `config.newcomer_offender_chance: float = 0.3`, `config.max_offenders: int = 6`.
  - `town_gen.generate_resident(writer, taken: list[Villager], rng) -> Villager`: Sleuth's port of Whispers' `generate_newcomer`. It uses the same `PROMPT` with `n=1`, up to 3 tries for a unique first name, and the id `f"v{max_numeric_id + 1:03d}"` over `taken`. It raises `ValueError` when all tries fail.
  - `traits.assign_look(v: Villager, others: list[Villager], rng) -> None`: fixed traits that don't clash with any other fixed look if possible, plus a 3-outfit wardrobe.
  - `town_gen.settle(v, villagers, home: str, rng) -> None`: a new household id (`f"h{n+1:02d}"`), `home`, a `"neighbor"` tie to someone on the same street, and one drawn tie via `_link`.
  - `async def arrivals.move_in(engine, home: str) -> Villager | None`. It makes one Haiku call (`generate_resident`), then `assign_look` and `settle`, then `engine.baselines.load(needs)`, then one Jev call (`engine.routine.add`), then `engine.add_villager(v, routine.place(v.id, game.phase) or home)`.
    - The new resident becomes an offender with `newcomer_offender_chance` while active is below `max_offenders`.
    - It posts the app line `f"{name}, a {occupation}, moved in on {Street}."`.
    - It does nothing while `town.alive_count >= config.population`.
    - It returns None after logging any exception.
  - `Cases.arrest(engine, vid: str) -> asyncio.Task`:
    - `offenders.drop(vid)`;
    - the app post `f"{name} was arrested and has left town."`;
    - `await engine.remove_villager(vid)`;
    - returns `asyncio.create_task(move_in(engine, home))`.

    `on_held` calls it for tiers other than petty.
  - `case._bystanders`, `witness_memories`, `scene_clues` and `make_solvable` exclude culprits of other open cases. `Cases._open` passes `away |= {f.crime.culprit for open files}`.
  - `record_json` reads `town.name_of(r.holder)`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_held_serious_episode_arrests_the_culprit_who_leaves_town():
    # a CaseFile with Crime(tier="serious") -> on_held -> culprit not in town, in town.departed, "arrested" post
async def test_someone_moves_in_on_the_arrested_resident_s_street():
    # await the returned task -> a new villager with home == culprit's old home, a household of their own, 2 ties
async def test_moving_in_costs_one_haiku_and_one_jev_call():
    # counting stubs -> writer.calls == 1, jev.calls == 1
async def test_moving_in_never_grows_the_town_past_population():
    # alive_count == population -> move_in returns None, no calls
def test_no_open_case_s_witness_is_another_open_case_s_culprit():
    # culprit of open case A stands at case B's scene -> never a memory holder or receipt-dropper of B
def test_notebook_entries_from_someone_who_left_still_show_their_name():
    # record held by a removed resident -> record_json(...)["from"] == their name
def test_a_resident_who_moved_in_has_unique_looks_and_three_outfits():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "arrest or moves_in or moving_in or moved_in or who_left or witness_is_another"`.
- [ ] **Step 3: Implement.** In the README, cover arrests, moving in, and that a resident who moved in may or may not be an offender.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Arrest serious culprits, and have someone new move in when anyone leaves"`

### Task 8: The wrongly accused remember (bumps STATE_VERSION)

**Files:** Modify `sleuth/cases.py`, `sleuth/player.py`, `sleuth/config.py`, `sleuth/static/index.html`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_cases.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Produces:
  - `CaseFile.named: dict[str, str]` (player → vid). `publish` records it before judging.
  - `config.reputation_accused_ties: float = -0.3`. `on_wrong` also nudges the accused's household and every resident whose warmth to the accused is "close" (`warmth_words(...) == "close"`).
  - `Player._notes(vid)` adds "This podcaster publicly accused you of {did} {victim}'s {item}, and you didn't do it. You're hurt and short with them." for every closed or open case where `named[self.id] == vid != crime.culprit`.
  - `Player.person(vid)` adds `"accused": bool`, true when this player named them wrongly. The page tags the row "you named them".

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_wrong_episode_cools_the_accused_household_and_close_ties():
    # household and close tie == reputation_wrong + reputation_accused_ties; a cool tie == reputation_wrong only
async def test_the_wrongly_accused_bring_it_up_when_interviewed():
    # writer.reply notes include "publicly accused you"
def test_the_people_list_marks_who_you_accused(game):
    # only the wrongly named row has accused True, and only for that player
def test_named_round_trips_with_the_case():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "accused or named_round"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Update the README's wrong-episode bullet.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Make the wrongly accused, their household and close ties remember it"`

---

## Stage 3: Standing and tiers

### Task 9: Standing (bumps STATE_VERSION)

**Files:** Modify `sleuth/player.py`, `sleuth/config.py`, `sleuth/feed.py`, `sleuth/web.py`, `sleuth/static/index.html`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Produces:
  - `config.serious_at: int = 3`, `config.major_at: int = 6`.
  - `player.TIER_POINTS = {"petty": 1, "serious": 2, "major": 3}`.
  - `player.LABELS = {"petty": "New podcaster", "serious": "Known in town", "major": "Town legend"}`.
  - `Player.standing: int = 0` and `Player.tier -> str`. A held town episode adds `TIER_POINTS[crime.tier]`. A wrong one sets `max(0, standing - 1)`. Both go through `to_state`/`restore`.
  - `Feed.on_standing(standing: int, tier: str, label: str, line: str, *, player: str)` emits kind `"standing"`. Its line is `TIPS_UP[tier]` when the tier rose, else `""`, with `TIPS_UP = {"serious": "Bigger tips are coming in now: serious cases.", "major": "The whole town is listening. The biggest cases come to you now."}`.
  - `/api/state` gains `"standing": {"score": int, "tier": str, "label": str}`. The page header shows the label and score. A `"standing"` event updates them and says the line in the app.

- [ ] **Step 1: Write the failing tests**

```python
async def test_held_episodes_raise_standing_by_their_tier_and_wrong_ones_lower_it():
    # petty held -> 1; serious held -> 3; wrong -> 2; wrong x5 -> 0
def test_tier_follows_standing_thresholds():
    # standing 2 -> petty, 3 -> serious, 6 -> major
async def test_the_practice_case_never_moves_standing():
def test_standing_round_trips_with_the_run():
def test_state_shows_the_players_standing(game):
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k standing`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Add a README **Standing** paragraph and the settings.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Track each podcaster's standing from held and wrong episodes"`

### Task 10: Several open cases, offered by standing (bumps STATE_VERSION)

**Files:** Modify `sleuth/cases.py`, `sleuth/player.py`, `sleuth/web.py`, `sleuth/static/index.html`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_cases.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Consumes: `Player.tier` (Task 9), `catalog_tiers()` (Task 3), `Offenders.ready/promote` (Task 5).
- Produces:
  - `Cases.shared()` is removed.
  - `Cases.open_shared(tier: str | None = None) -> list[CaseFile]`.
  - `Cases.offered(tier: str) -> list[CaseFile]`: open shared cases with `TIERS.index(c.tier) <= TIERS.index(tier)`, highest tier first, then oldest.
  - `Cases.for_player(player_id: str, tier: str = "petty", chosen: str | None = None) -> CaseFile | None`: the private case first, else `chosen` if offered, else `offered(tier)[0]`.
  - `Cases.wanted(engine) -> list[str]`: `"petty"` plus the tier of every active player, kept to `catalog_tiers()`, in `TIERS` order. Task 17 adds the major cadence here.
  - `Cases.ensure(engine, now=None)` opens one case for each wanted tier with no open shared case. Culprits come from `offenders.ready(day, tier)`, or else `offenders.promote(tier)`.
  - `case_json` adds `"tier"`.
  - `Player.case_id: str | None` is saved. `Player.choose_case(case_id) -> str | None` refuses a case not offered with "That case isn't one of your tips.". `Player.current() -> CaseFile | None` replaces every `for_player(self.id)` call in `player.py`, and `_case()` uses it.
  - `Cases.brief(feed, player_id, today, tier)` tells the player about every offered case.
  - Web: `POST /api/case/choose` with `{"case_id": str}`, answered by `BAD_CHOOSE = 'Send JSON like {"case_id": "case-1"}.'`. `/api/state` and `/api/case` add `"cases": [case_json for offered]` and keep `"case"` as the current one.
  - Page: a "Tips" row of buttons under the case title, one per offered case, labelled with title and tier, marking the current one. Choosing posts and reloads the case. `case` events for tiers above the player's are ignored using `state.standing.tier`, and the notebook shows the current case's records.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_case_is_open_for_each_tier_someone_playing_has_reached():
    # monkeypatch a serious Kind into CRIMES; a serious-tier active player -> one petty and one serious case open
async def test_a_podcaster_is_offered_cases_at_or_below_their_tier():
async def test_actions_follow_the_chosen_case():
    # choose the petty case while a serious one is open -> interview/search/pull/publish use the petty case
async def test_choosing_a_case_not_offered_is_refused():
async def test_the_first_held_episode_closes_a_case_for_everyone_working_it():
    # other cases stay open; a new case of that tier opens
def test_state_lists_only_offered_cases(game):
def test_choose_case_endpoint(game):
    # 200 ok and /api/case case.id changes; bad JSON -> 400 BAD_CHOOSE
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "tier or offered or chosen or choose"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Run the tutorial tests on their own: they must pass unchanged. Rewrite the README's **A case** paragraph for several tips.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Open a case per tier and offer each podcaster the cases their standing fits"`

### Task 11: Serious crimes

**Files:** Modify `sleuth/case.py`, `sleuth/cases.py`, `sleuth/README.md`. Test `sleuth/tests/test_case.py`, `sleuth/tests/test_cases.py`.

**Interfaces:**
- Produces:
  - New `CRIMES` entries:
    - `"rob"`: `Kind("serious", "robbed", ("till", "cash box"), "emptied", "was hurrying out with a bag", news="Someone robbed {victim}'s {item} {at} {when}.")`, with places `("grocery", "hardware store", "cafe", "bar")`;
    - `"mug"`: `Kind("serious", "mugged", ("wallet", "phone"), "gone", "was grabbing at someone", news="Someone mugged {victim} {at} {when} and took their {item}.", title="The mugging of {victim}")`, with places `(*STREETS, "dog park", "bar")`;
    - `"car"`: `Kind("serious", "stole", ("car",), "gone", "was driving off in a car that wasn't theirs")`, which reuses `ITEM_PLACES["car"]`.
  - `case.EVIDENCE = {"petty": (2, 1/3), "serious": (3, 0.0), "major": (2, 0.0)}`: max witnesses and regular-culprit chance by tier. `witness_memories` and `stage_crime` read them.
  - `stage_crime(..., tier: str = "petty")` draws only kinds of that tier.
  - `case.victim_memory(crime, town, rng, ids) -> Record`: a mugging's victim holds a `"memory"` with one random trait of the culprit. `Cases._open` adds it for `template == "mug"` and tells the victim through `_remember`.
  - `catalog_tiers()` now returns `("petty", "serious")`, which lets escalation and serious tips work.

- [ ] **Step 1: Write the failing tests**

```python
def test_serious_crimes_are_committed_by_serious_offenders_only():
def test_a_serious_culprit_is_never_a_regular_at_the_scene():
    # 50 seeds -> routine.place(culprit, phase) != crime.place
def test_a_mugging_victim_remembers_one_trait_of_the_mugger():
def test_serious_cases_stay_solvable_across_seeds():
    # 30 seeds: every opened serious case's suspects(records) == {culprit}
async def test_a_promoted_offender_fills_an_empty_serious_tier():
async def test_a_held_serious_episode_ends_in_an_arrest():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "serious or mugging"`.
- [ ] **Step 3: Implement.** Update the README's crime list and evidence notes.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Add serious crimes: robbery, mugging and car theft, with more evidence"`

### Task 12: Accomplices (bumps STATE_VERSION)

**Files:** Modify `sleuth/cases.py`, `sleuth/alibi.py`, `sleuth/player.py` (`_known`), `sleuth/config.py`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_alibi.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_cases.py`.

**Interfaces:**
- Produces:
  - `config.accomplice_chance: float = 0.5`.
  - `CaseFile.accomplice: str | None = None`. For serious cases it is set with that chance: the culprit's warmest tie with warmth ≥ 0.6, else another active offender. It is never the victim or a witness of the same case, and it is kept out of that case's witnesses.
  - `alibi.accomplice_word(file, speaker, about) -> tuple[str, bool] | None`: `(f"{about.name} was with me {at(speaker's place)} {WHEN}.", False)` when `speaker.id == file.accomplice` and `about.id == file.crime.culprit`. `_known`'s `where_was` branch checks it before `household_word`.
  - On a held serious case, `on_held` also exposes the accomplice: `offenders.exposed[acc] = f"covered for {culprit name}"`, with the same coldness as a petty exposure and no arrest.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_accomplice_vouches_falsely_for_the_culprit():
async def test_citing_the_accomplice_s_word_sinks_the_episode():
async def test_a_held_episode_exposes_the_accomplice_too():
def test_an_accomplice_is_never_a_witness_of_the_same_case():
def test_accomplice_round_trips_with_the_case():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k accomplice`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Give some serious culprits an accomplice who vouches for them"`

---

## Stage 4: Districts and the loop

### Task 13: District state (bumps STATE_VERSION)

**Files:** Create `sleuth/districts.py`. Modify `sleuth/engine.py`, `sleuth/cases.py`, `sleuth/__main__.py`, `sleuth/persist.py` (`components` gains `"districts"`), `sleuth/config.py`, `sleuth/README.md`. Test `sleuth/tests/test_districts.py`, `sleuth/tests/test_persist.py`.

**Interfaces:**
- Produces:

```python
PLACE_DISTRICT = {"cafe": "elm street", "bar": "elm street", "dog park": "elm street",
                  "gym": "oak street", "school": "oak street", "library": "oak street",
                  "hardware store": "maple street", "grocery": "maple street", "town hall": "maple street",
                  **{s: s for s in STREETS}}
HIT = {"petty": 0.25, "serious": 0.45, "major": 0.7}
RELIEF = (0.15, 0.1)   # crime, fear lowered by an exposure

def district_of(place: str) -> str: ...

@dataclass
class District:
    crime: float = 0.0
    fear: float = 0.0
    exposures: int = 0          # exposures since it last organized
    was: list[float] = field(default_factory=lambda: [0.0, 0.0])   # crime, fear at the last morning
    watch: "Watch | None" = None   # Task 14

class Districts:
    def __init__(self, config: Config): self.by_street = {s: District() for s in STREETS}
    def to_state(self) -> dict: ...
    def restore(self, state: dict) -> None: ...
    def on_crime(self, crime: Crime) -> None: ...
    def on_exposed(self, crime: Crime) -> None: ...
    def tick(self, morning: bool) -> None: ...   # decay; on a morning, snapshot was
```

- Config: `district_crime_decay: float = 0.02`, `district_fear_decay: float = 0.015`. Values are clamped to [0, 1].
- `Engine(..., districts: Districts | None = None)` sets `self.districts`, and `cases.districts = districts`.
- `Cases._open` calls `districts.on_crime`, and `on_held` calls `districts.on_exposed`. `_clock_loop` calls `districts.tick(phase == "morning")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_place_and_resident_belongs_to_one_district():
    assert set(PLACE_DISTRICT) == set(PLACES) and set(PLACE_DISTRICT.values()) == set(STREETS)
def test_a_crime_raises_crime_and_fear_in_its_district():
def test_district_state_decays_each_part_of_the_day():
def test_an_exposure_lowers_crime_in_the_district():
def test_districts_round_trip():
def test_the_saved_game_includes_the_districts():   # test_persist.py
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k district`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`. Add a README **Districts** paragraph.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Track crime and fear in each district"`

### Task 14: Watches, and crime moving elsewhere (bumps STATE_VERSION)

**Files:** Modify `sleuth/districts.py`, `sleuth/cases.py`, `sleuth/case.py` (`stage_crime` weights), `sleuth/engine.py`, `sleuth/config.py`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_districts.py`, `sleuth/tests/test_case.py`, `sleuth/tests/test_copy.py`.

**Interfaces:**
- Produces:

```python
WATCH_NAMES = ("{street} Neighborhood Watch", "{street} Porch-Light Pact", "{street} Group Chat")
WATCH_SIZE = 6
FORMED = "{street} residents are starting a watch. {first}'s making flyers."
TOLD = "We're starting the {name}. Keep an eye out on {street}."
WOUND_DOWN = "The {name} has wound down. {street} feels safe again."

@dataclass
class Watch:
    name: str
    founder: str
    members: list[str]
    since: float

Districts.organize(street: str, town: Town, rng: Random, now: float, victim: str | None = None) -> Watch | None
    """Form a watch when fear >= organize_fear, exposures >= 1 and none stands; resets exposures."""
Districts.wind_down() -> list[str]          # streets whose watch ended: crime and fear both < disband_below
Districts.organized(place: str) -> bool
async def Cases.rally(engine, street: str, victim: str | None) -> None
    """organize; on a new watch, post FORMED on the app and deliver TOLD from the founder to the members."""
```

- Config: `organize_fear: float = 0.4`, `disband_below: float = 0.05`, `organized_crime_weight: float = 0.25`.
- The founder is `victim` if they're in town and live on the street, else a random resident of it. Members are the founder plus up to `WATCH_SIZE - 1` residents of the street, ordered by the founder's warmth, ignoring offender status.
- `on_held` calls `rally` at once, and `on_tick` calls it for every street and posts `WOUND_DOWN` for streets that wound down.
- In `stage_crime`, each pair's weight is multiplied by `organized_crime_weight` when `districts.organized(place)`. `stage_crime` gains a `weight: Callable[[str], float] | None` parameter that `Cases` passes.

- [ ] **Step 1: Write the failing tests**

```python
async def test_fear_and_an_exposure_organize_a_watch_announced_on_the_app():
async def test_watch_members_hear_of_it_through_their_minds():
    # engine.delivered has TOLD to <= WATCH_SIZE-1 member ids, founder speaking
async def test_a_watch_never_forms_without_an_exposure():
async def test_forming_a_watch_makes_no_model_calls():
def test_crimes_move_away_from_organized_districts():
    # 300 seeded stage_crime draws: share of crimes in the organized street's places drops below half of unorganized
def test_a_watch_winds_down_once_crime_and_fear_fade():
def test_watch_names_are_secular():   # test_copy.py: no FAITH or MEDIEVAL in WATCH_NAMES/FORMED/TOLD/WOUND_DOWN
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "watch or organized"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Let fearful districts with an exposed culprit organize a watch that drives crime elsewhere"`

### Task 15: Neglect breeds offenders, and residents feel their district

**Files:** Modify `sleuth/districts.py`, `sleuth/offenders.py`, `sleuth/cases.py`, `sleuth/decide.py`, `sleuth/engine.py`, `sleuth/writer.py`, `sleuth/config.py`, `sleuth/README.md`. Test `sleuth/tests/test_districts.py`, `sleuth/tests/test_offenders.py`, `sleuth/tests/test_decide.py`, `sleuth/tests/test_writer.py`.

**Interfaces:**
- Produces:
  - Config: `neglect_at: float = 0.4`, `turn_chance: float = 0.5`, `min_offenders: int = 3`.
  - `Districts.neglected() -> list[str]`: streets with no watch whose crime and fear are both ≥ `neglect_at`.
  - `Districts.mood(street) -> str | None`: `"rattled"` when fear ≥ 0.6, `"on edge"` when ≥ 0.3, else None. With a watch, it appends `", but the {name} is on it"`.
  - `Offenders.turn(street_residents: list[str], rng) -> str | None`: one non-offender, never-exposed resident becomes petty, unless active is at `max_offenders`.
  - On a morning, `Cases.on_tick`:
    - calls `turn` with chance `turn_chance` for each neglected street;
    - then, if active is below `min_offenders`, calls `top_up(candidates=residents of unorganized streets)`.

    Task 5's tick-time top-up to `offenders` remains only for the initial fill (no offenders and none ever exposed).
  - `TurnView.mood: str | None`. `_state` adds `"neighborhood_mood": f"{Street} is {mood}"`. `Writer.say(..., mood="")` adds `f"Your street is {mood}. "` to the system prompt. The engine fills both from the villager's home.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_neglected_district_can_turn_a_resident_into_an_offender():
def test_organized_districts_never_produce_offenders():
    # 200 mornings with a watch and high crime/fear -> no resident of that street ever joins active
def test_the_floor_refills_from_unorganized_districts_only():
def test_turning_stops_at_max_offenders():
def test_residents_feel_their_district_s_mood():   # test_decide.py: state has neighborhood_mood
async def test_say_is_told_the_street_s_mood():     # test_writer.py
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "neglect or organized_districts or floor or mood or max_offenders"`.
- [ ] **Step 3: Implement.** Add a README paragraph on how the districts connect.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Turn residents of neglected districts into offenders, never in organized ones"`

### Task 16: The district map, and the town reacting at once

**Files:** Modify `sleuth/districts.py`, `sleuth/feed.py`, `sleuth/cases.py`, `sleuth/web.py`, `sleuth/static/index.html`, `sleuth/README.md`. Test `sleuth/tests/test_districts.py`, `sleuth/tests/test_web.py`, `sleuth/tests/test_cases.py`.

**Interfaces:**
- Produces:
  - `Districts.levels(town: Town) -> list[dict]`. Each entry is `{"street", "name", "crime": 0..3, "fear": 0..3, "crime_trend": -1|0|1, "fear_trend": -1|0|1, "watch": str|None, "founder": str|None}`, with levels `round(x * 3)` and trends from the sign of the change since `was` (dead zone 0.05).
  - `Feed.on_districts(levels: list[dict])` emits kind `"districts"`. `Cases` emits it after any crime, exposure, watch change and morning tick.
  - App reactions (code copy, `feed.on_post` from `APP`):
    - `ON_EDGE = "{street} is on edge after {title}."` when a crime raises the street's fear level;
    - `BREATHES = "{street} breathes a little easier now {name}'s been found out."` on a held exposure.
  - `/api/state` gains `"districts"` (`[]` while practising).
  - Page: a small "Districts" panel in the case column. It shows three rows (name, crime and fear as 0 to 3 pips, ↑/↓ trend, and the watch name and founder) and redraws on `"districts"` events. It is hidden while practising.

- [ ] **Step 1: Write the failing tests**

```python
def test_district_json_carries_levels_not_internals():
    # keys exactly as above; crime/fear/trends are ints; no floats anywhere in the JSON
async def test_a_first_held_case_changes_the_town_at_once():
    # within one publish call: culprit's known_for set, victim regard up, app has THANKS and BREATHES posts,
    # a "districts" event with that street's crime level lower or equal, and a watch if fear >= organize_fear
async def test_a_crime_that_rattles_a_street_is_noticed_on_the_app():
def test_state_carries_the_districts_but_not_while_practising(game):
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "district_json or at_once or rattles or carries_the_districts"`.
- [ ] **Step 3: Implement.** In the README's page description, add the districts panel.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Show the districts on a small map and let the app react to what happens in them"`

---

## Stage 5: Major cases

### Task 17: A death in town (bumps STATE_VERSION)

**Files:** Modify `sleuth/case.py`, `sleuth/cases.py`, `sleuth/player.py` (`who_had_reason`), `sleuth/config.py`, `sleuth/persist.py`, `sleuth/README.md`. Test `sleuth/tests/test_case.py`, `sleuth/tests/test_cases.py`, `sleuth/tests/test_player.py`.

**Interfaces:**
- Produces:
  - `CRIMES["death"] = Kind("major", "", ("",), "", "was arguing with someone", news="{victim} was found dead {at}. It happened {window}. Police are treating it as suspicious.", title="The death of {victim}")`, with places `PLACES`.
  - `case.WINDOW = "{span}"`, a marker like `WHEN`. Staging formats `kind.news` with `window=WINDOW`, the same way it passes `when=WHEN`.
  - `Crime.window: list[str] = field(default_factory=list)`: `[previous phase, phase]` for a death, where the previous phase may fall on the day before. `told()` replaces `WINDOW` with `f"sometime between {ago(...first)} and {ago(...second)}"`, said on today.
  - `CaseFile.motives: list[str]`: at least 2 residents besides the culprit with warmth < 0 to or from the victim. Staging skips victims without them.
  - Config: `major_case_days: float = 6.0`, `major_every_days: float = 3.0`.
  - `Cases.wanted` adds `"major"` only when an active player is major, no major case is open, and `now - last_major >= major_every_days`. `Cases.last_major: float` is saved in the cases state.
  - `catalog_tiers()` now returns all three tiers.
  - `Cases._open` for a death:
    - the discovery's holder is a bystander or a household mate (`"Around {clock}, {finder} found {victim} {at}."`, told to the finder);
    - after the evidence is staged, `await engine.remove_villager(victim)` and the `move_in` task (Task 7) run.
  - A case of tier `"major"` goes cold after `major_case_days`.
  - `_known` `who_had_reason`: for a death, any resident acquainted with the victim names every motive (`statement` records, sound).

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_major_case_opens_only_for_a_major_podcaster_and_not_too_often():
async def test_the_victim_leaves_town_and_someone_else_found_them():
def test_the_news_gives_a_window_not_a_time():
    # text contains "sometime between" and no clock
async def test_a_major_case_has_several_people_with_motives():
def test_a_major_case_stays_solvable_across_seeds():
async def test_a_major_case_runs_longer_before_going_cold():
async def test_a_held_major_episode_arrests_the_culprit_and_someone_moves_in():
def test_window_and_motives_round_trip():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "major or window or motives"`.
- [ ] **Step 3: Implement** the interfaces above and bump `STATE_VERSION`.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Add the occasional major case: a death in town with a time window and several motives"`

### Task 18: The whole town talking, soberly

**Files:** Modify `sleuth/faith.py`, `sleuth/cases.py`, `sleuth/writer.py`, `sleuth/effects.py`, `sleuth/chatter.py`, `sleuth/static/index.html`, `sleuth/README.md`. Test `sleuth/tests/test_copy.py`, `sleuth/tests/test_cases.py`, `sleuth/tests/test_effects.py`, `sleuth/tests/test_writer.py`.

**Interfaces:**
- Produces:
  - `faith.GORE = re.compile(r"\b(blood\w*|gor(e|y)|stab\w*|corpses?|knife|knives|guns?|shot|shoot\w*|strangl\w*|poison\w*|weapons?|slaughter\w*|butcher\w*)\b", re.I)`. The module docstring becomes "Words the town never has: faith and gore."
  - `effects.words`, `chatter.chatter` and `Player._phrase` drop or plain-fall-back any Haiku line matching `GORE`.
  - `writer.SOMBER = "Someone has died. Be sober and kind about it, never joking, and say nothing of how. "`, added to `say`, `reply` and `post` prompts when the case is a death.
  - Death news is delivered to every resident whose home is the victim's street, plus everyone with a tie to the victim. The victim is excluded.
  - Page: a tier badge on the case header and tips ("Petty", "Serious", "Major").

- [ ] **Step 1: Write the failing tests**

```python
def test_no_gore_in_code_or_copy():   # test_copy.py, same file set as the faith test, faith.py excluded
async def test_a_line_with_gore_is_never_said():
async def test_major_news_reaches_the_district_and_the_victim_s_ties_only():
async def test_writer_is_told_to_be_sober_about_a_death():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "gore or sober or major_news"`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Let the whole town talk about a death, soberly and without gore"`

---

## Stage 6: Drifting hearsay

### Task 19: Talk drifts as it's retold

**Files:** Modify `sleuth/effects.py`, `sleuth/writer.py`, `sleuth/README.md`. Test `sleuth/tests/test_effects.py`, `sleuth/tests/test_writer.py`.

**Interfaces:**
- Produces:
  - `effects.FIRST_HAND = re.compile(r"\bI (?:saw|spotted|watched|noticed|caught)\b", re.I)`.
  - In `act.words`, retold lines (`DIRECT`, `SPEAK` and the move-share retell) are said unless they match `FIRST_HAND`, `FAITH` or `GORE`. Those are dropped. Cover stories and warnings keep `invents_facts` and `misdated` with the plain fallback.
  - `writer.RETELL_TALK = "Pass on what you heard, changed as your manner says; you may embellish. Never claim you saw it yourself. "` replaces `CASE_TALK`'s no-facts sentence for retold case lines. `say(..., retold=True)`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_retold_case_talk_may_embellish():
    # writer line "Heard it was a tall fella in a red coat, around nine!" on a retell -> delivered
async def test_retold_talk_never_claims_to_have_seen_it():
async def test_cover_stories_and_warnings_stay_strict():
async def test_retold_talk_with_faith_or_gore_is_dropped():
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "retold or stay_strict"`. Update `test_case_talk_that_invents_is_dropped` to cover only root lines.
- [ ] **Step 3: Implement.** Update the README's talk paragraph: what residents pass on can change in the retelling.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Let resident-to-resident talk drift and embellish as it's retold"`

### Task 20: Drifted hearsay is unreliable evidence

**Files:** Modify `sleuth/player.py` (`_hearsay`), `sleuth/static/index.html`, `sleuth/README.md`. Test `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`.

**Interfaces:**
- Produces:
  - `Player._hearsay` records memory-rooted hearsay with `sound = not invents_facts(heard.text, root_text, firsts)`. `root_text` is the root memory record's text (`file.records` whose `utterance == root`). If that record is gone, the hearsay is unsound. Cover-rooted hearsay stays unsound.
  - Page: the notebook's "Heard" group gets the subtitle "Retold. It may have changed along the way." Soundness is still never sent.

- [ ] **Step 1: Write the failing tests**

```python
async def test_faithful_hearsay_from_a_witness_is_sound():
async def test_hearsay_that_drifted_from_the_witness_is_unsound():
async def test_citing_drifted_hearsay_sinks_the_episode():
async def test_first_hand_testimony_stays_exact():
    # the witness's own memory record and reply facts are unchanged by drift
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "hearsay or first_hand_testimony"`.
- [ ] **Step 3: Implement.** Update the README's evidence table row for statements: hearsay may have drifted.
- [ ] **Step 4: Run `VERIFY`.**
- [ ] **Step 5: Commit** `git add sleuth && git commit -m "Treat hearsay that drifted from the witness as unsound evidence"`

---

## Playtest

Run this after Task 20, and after any stage worth a look, against a real generated town, a live Contex and real Jev and Haiku. Fix what it finds on the branch, with a commit per fix, and run it again until every item below is shown in one town.

**Setup:**
- Run Contex locally on 8001.
- Keys come from `.env`.
- Never use port 8765.
- Use a fresh session, so the town is generated:

```bash
SLEUTH_SESSION=lt1 SLEUTH_DATA_DIR=$SCRATCH/lt1 SLEUTH_WEB_PORT=8790 \
SLEUTH_POPULATION=24 SLEUTH_DAY_SECONDS=240 SLEUTH_CASE_DAYS=2 SLEUTH_MAJOR_CASE_DAYS=3 \
SLEUTH_SAVE_EVERY_SECONDS=5 SLEUTH_SERIOUS_AT=2 SLEUTH_MAJOR_AT=4 SLEUTH_MAJOR_EVERY_DAYS=0 \
SLEUTH_ESCALATE_AFTER=1 SLEUTH_ORGANIZE_FEAR=0.25 SLEUTH_NEGLECT_AT=0.3 SLEUTH_TURN_CHANCE=1 \
SLEUTH_REFORM_CHANCE=0.5 SLEUTH_EXPOSED_QUIET_DAYS=1 SLEUTH_CHATTER_CHANCE=1 SLEUTH_DAILY_SPEND_CAP=3 \
python -m sleuth
```

These are pacing knobs only:
- 24 residents is 8 per district.
- A part of the day lasts one minute.
- The tier thresholds are low.
- Watches form and neglect turns residents quickly.
- Every Config field is already a `SLEUTH_*` override.

**Oracle:** a small throwaway script in the scratchpad (not committed) reads `$SCRATCH/lt1/sleuth_worlds/lt1.state.json`. It finds each open case's culprit, tier, records, the offender set and the raw district numbers. It drives the HTTP API with one player's cookie:
1. `GET /` and `POST /api/skip`.
2. Choose a case.
3. Interview the "nearby" residents and the victim.
4. Pull and search at the scene.
5. Publish citing notebook records that `points_at` the culprit.

The oracle also takes one deliberately wrong episode. It logs each step with the feed events it caused. A second, browser player (the Playwright MCP at `http://127.0.0.1:8790`) plays at least one case by hand and screenshots the moments below.

**Must demonstrate, in one town and one session (a restart part-way is welcome to prove save and restore):**
1. **Several cases solved:** at least 4 held episodes across petty and serious tiers. Each closes its case for everyone, and a new tip of that tier appears.
2. **A petty culprit exposed and treated differently:**
   - they stay in the people list tagged with what they did;
   - an interview by the exposing podcaster is refused;
   - another podcaster's interview reads cold;
   - the victim's thanks and a district "breathes easier" post appear on the app.
3. **A serious culprit arrested and replaced:**
   - "was arrested and has left town" appears on the app;
   - they're gone from the people list;
   - within a minute, "moved in on {Street}" appears and the new resident shows a household, ties and a job;
   - the oracle shows whether they joined the offenders. The page must not show it.
4. **A district organizing:**
   - a watch forms, announced on the app ("{Street} residents are starting a watch…");
   - the district panel shows the watch;
   - over the next game days that street's crime level falls;
   - the oracle's tally of new crimes by street shifts to the other districts.
5. **Standing rising and tips escalating:**
   - the header label moves from "New podcaster" to "Known in town" (and "Town legend" if time allows) with the `TIPS_UP` line;
   - a serious tip appears in the Tips row only for the podcaster who reached it;
   - the second, newer player still sees petty tips only.
6. **The wrongly accused remember:** after the deliberate wrong episode, the accused's row says "you named them". Their reply, or their household's, is short with the podcaster, or they refuse.
7. **Whimsy:** at least 5 app posts with character (lost pet, note, gripe, theory), and replies that show a quirk. None has invented case facts, faith or gore.
8. **No leaks:** across the whole run, saved `/api/state`, `/api/case`, `/api/villagers/*` and WebSocket payloads never contain an offender flag, a tier for a resident, raw district floats, warmth or `sound`. The oracle greps them.
9. **Tutorial unaffected:** a fresh cookie gets the intro, plays the six-step first case to a held episode, and is handed into the town.

**Report:**
- the cases solved, with tier and culprit;
- screenshots of items 2 to 6 and of the district panel before and after;
- spend from the menu;
- every defect found, with its fix commit.
