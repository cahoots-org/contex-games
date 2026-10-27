# Sleuth: Learned Looks, Daily Outfits and Photo Posts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identifying people becomes part of the investigation. Each resident owns three outfits and wears one a day. Evidence reports what was worn at the time. The page shows a resident's looks only once the player has learned them by talking, by a description, or from a saved photo. A few true photos a day are posted on the neighborhood app.

**Architecture:** `Town` records what everyone wore each day (`worn`), and `Town.looks(vid, day)` is the fixed traits plus that day's outfit. Every trait check in `case.py` and the judge reads looks on the crime's day. `Player.known` holds what the player has learned about each resident, with how and when. The web layer builds people rows and faces only from that, never from `Villager.traits`. Photos are code-held `Photo`s in an `Album` on the engine. Each is taken from a finished phase's whereabouts and posted as a public feed event.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio, ruff, one static `sleuth/static/index.html`.

**Spec:** `docs/superpowers/specs/2026-10-25-sleuth-design.md`, section "Addendum, 2026-10-27: knowing people, outfits and photos". Read the earlier addenda too. The README (`sleuth/README.md`) describes today's game.

## Global Constraints

- **Branch:** `feat/sleuth` in `/Users/robmiller/Projects/contex-games`. No worktrees. Touch only `sleuth/`.
- **Ports:** never use 8765 (the owner's running game). For a manual look, use `SLEUTH_WEB_PORT=8790`.
- **Tests:** `PYTEST` = `/private/tmp/claude-501/-Users-robmiller-Projects-contex/dc5af79c-d8f0-4711-83c2-3ccea8efac2d/scratchpad/venv-web/bin/python -m pytest sleuth -q -p no:cacheprovider`. Use `set -o pipefail` when piping. Add `-k <name>` for red/green steps. Before every commit, run the full `PYTEST`, `ruff check .` from the repo root, and `NODECHECK`.
- **`NODECHECK`** = `sed -n '/^<script>$/,/^<\/script>$/p' sleuth/static/index.html | sed '1d;$d' > "$TMPDIR/page.js" && node --check "$TMPDIR/page.js"`
- **Commits:** one per task, CI-green, with the exact message given. Every message ends with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01YP7uhbQm8avkDcwdQ9b87E
  ```
- **Style:** concise docstrings, no inline imports, no meta comments, nothing clever. Never send hidden state to the browser: culprit, warmth, `sound`, unlearned looks, or anyone's outfit outside evidence, learned looks and photos.
- **Saves:** bump `STATE_VERSION` in `sleuth/persist.py` in every task that changes a saved shape (Tasks 1, 3, 5). An old save is set aside, which is fine.
- **Code owns facts:** captions, descriptions and outfits are written by code. No new model calls. An interview still costs at most one Jev and one Haiku call.
- **README:** each task updates the README lines its behavior changes, in the existing voice.

## Decisions (where the addendum leaves room)

- **Outfit = the `coat` trait.** `TRAITS["coat"]` stays the outfit vocabulary. `Villager.traits` keeps only the fixed `height`, `hair` and `car`. `Villager.wardrobe` holds three distinct coats. The `looks` dict keeps the key `"coat"`, so `describe`, `figure`, `face`, the clip and the coat thread are unchanged.
- **Worn is recorded, per day.** `Town.worn[day][vid]` is filled once per day by `Town.dress`, with a random pick from the wardrobe, and it is saved. Days older than `ceil(case_days) + 2` are dropped, which still covers every open case's crime day. Records, learned looks and photos snapshot their own looks, so nothing reads old days.
- **Culprit's caution:** while their case is in setup or open, a culprit never wears their crime-day outfit on a later day. This is deterministic, with no Jev.
- **Learned looks:**
  - **Talking** shows height, hair and today's outfit (`IN_PERSON`).
  - **A description** gives height, hair and car (`BY_WORD`), which is what people know of someone they know. Only a resident with a tie to the person, or one sharing their household, can describe them.
  - **A saved photo** shows height, hair and the outfit worn that day.
  - **Clips stay anonymous** and teach no one's looks, since no clip names who is in it.
- **Descriptions are a new interview kind,** `what_do_they_look_like`. The answer is a `statement` record carrying `traits` and `who`, so `conveys` forces Haiku to keep the looks. Descriptions are true for now. Each is stored with its source (`Record.holder`, and `by` on the known entry), so untrustworthy describers can later set `sound=False` or change the looks.
- **Photos:** one per finished morning, afternoon or evening phase while someone is playing, so up to 3 a day, at a public place where 2 or more residents were logged. Each shows 2 or 3 of them, with a code caption like "Evening at the bar: Cal Hughes in a green raincoat, Ivy Hughes in a denim jacket." There are no photos at night. A setup or open case's culprit is never in a photo of the crime's own day and phase. The album keeps the newest 60.
- **A photo teaches looks when the player saves it.** It is public in the photo feed. Saving records known looks ("in a photo, day 2") and, while a case is open, adds a `photo` notebook entry for that case.
- **Faces:** a known resident's face is drawn from their newest known entry, which is the looks learned then. An unknown resident is a neutral grey silhouette.

## Review Focus

1. **Leak of unlearned looks or the culprit's outfit.** `/api/state`, `/api/case`, `/api/villagers/{vid}` and every feed event must carry no trait or outfit of anyone the player hasn't learned, apart from evidence records and photos. Tests: Task 3 `test_nothing_sent_shows_unlearned_looks`, and Task 5 `test_a_culprit_is_never_photographed_at_their_crime`.
2. **Solvability with outfits.** `suspects`, `make_solvable` and the judge read looks on the crime's day. A resident who wore the crime coat only on another day is not a suspect, and the accused is judged on what they wore that day, not today. Tests: Task 1 `test_suspects_match_what_each_wore_on_the_crime_day` and `test_an_episode_is_judged_on_what_the_accused_wore_that_day`.
3. **Save and restore mid-case.** `Town.worn`, `Player.known` and the album round-trip, and `STATE_VERSION` moves in each task that changes them. Tests: Task 1 `test_worn_round_trips_and_old_days_are_dropped`, Task 3 `test_known_round_trips_and_resets_on_leaving_the_first_case`, and Task 5 `test_the_album_keeps_the_newest_and_round_trips`.
4. **The first case stays teachable.** The practice town has wardrobes, with day-1 outfits equal to today's coats, so the witness and thread still narrow to Cal. A new checklist step asks the player to learn how people look. Tests: Task 2 `test_only_the_witness_and_the_clue_together_narrow_it_to_the_culprit` (updated), and Task 4 `test_the_first_case_asks_to_learn_how_people_look`.
5. **Restart on a new day before any tick.** The startup path dresses today, so a crime staged or a talk right after a restart has an outfit. Test: Task 1 `test_cases_dress_today_with_the_culprits_caution`.

---

### Task 1: Daily outfits, and evidence against what was worn

**Files:**
- Modify: `sleuth/models.py` (`Villager.wardrobe`), `sleuth/town.py`, `sleuth/cases.py`, `sleuth/case.py`, `sleuth/player.py` (`_seen`, `publish`), `sleuth/__main__.py`, `sleuth/persist.py` (`STATE_VERSION = 23`)
- Test: `sleuth/tests/test_town.py`, `sleuth/tests/test_case.py`, `sleuth/tests/test_cases.py`, `sleuth/tests/test_player.py`

**Interfaces:**
- Produces:
  - `Villager.wardrobe: list[str] = field(default_factory=list)`
  - `Town.worn: dict[int, dict[str, str]]` (day → vid → coat). In `to_state` it is `"worn": {str(day): {...}}`, and `restore` turns the keys back into ints.
  - `Town.dress(day: int, rng: Random, avoid: dict[str, str] | None = None, keep_days: int = 5) -> None`: a no-op if `day` is already dressed. Otherwise each resident with a wardrobe gets `rng.choice` of their wardrobe minus `avoid.get(vid)` (the whole wardrobe if that leaves nothing). Days `< day - keep_days` are dropped.
  - `Town.outfit(vid: str, day: int) -> str | None`
  - `Town.looks(vid: str, day: int) -> dict[str, str]`: `{**v.traits}` with `"coat"` overridden by `outfit(vid, day)` when one is recorded. Residents without a wardrobe keep any coat in their traits, so existing tests still pass.
  - `Cases.cautious(day: int) -> dict[str, str]`: the culprit's crime-day outfit, by culprit id, for every case not closed whose `crime.day < day` and that has a recorded outfit.
  - `Cases.dress(day: int) -> None` = `self.town.dress(day, self.rng, self.cautious(day), math.ceil(self.config.case_days) + 2)`

- [ ] **Step 1: Write the failing tests**

```python
# test_town.py
def test_dress_picks_one_outfit_from_each_wardrobe_once_a_day():
    town = Town(); v = Villager("v1", "A", "x", "y", "", [], {}, {"height": "tall"}, wardrobe=["grey hoodie", "denim jacket", "black puffer"])
    town.add(v)
    town.dress(3, Random(1)); first = town.outfit("v1", 3)
    town.dress(3, Random(2))
    assert first in v.wardrobe and town.outfit("v1", 3) == first
    assert town.looks("v1", 3) == {"height": "tall", "coat": first} and town.outfit("v1", 4) is None

def test_dress_avoids_the_given_outfit():
    # 30 dressed days with avoid={"v1": "grey hoodie"}: never "grey hoodie"

def test_worn_round_trips_and_old_days_are_dropped():
    # dress days 1..10 with keep_days=5 -> sorted(town.worn) == [5..10]; Town().restore(town.to_state()).worn == town.worn

# test_case.py (dress make_case's town: town.dress(1, Random(0)); give v5 a wardrobe)
def test_witness_and_clip_report_the_outfit_worn_on_the_crime_day():
    # v5 wore "green raincoat" on day 1 and "plaid flannel" on day 2; crime on day 1 at a camera place
    # clip.traits["coat"] == "green raincoat"; every memory's "coat" (if seen) == "green raincoat"

def test_suspects_match_what_each_wore_on_the_crime_day():
    # v3 and v5 share fixed traits; town.worn = {1: {"v5": "green raincoat", "v3": "grey hoodie"}, 2: {"v3": "green raincoat"}}
    # a clip with {"coat": "green raincoat"} on crime day 1 -> suspects(...) == {"v5"} plus anyone else matching; "v3" not in it

def test_make_solvable_narrows_on_the_crime_day_outfit():
    # residents differ only by day-1 coat -> the added memory includes "coat" with the day-1 value

# test_cases.py
def test_cases_dress_today_with_the_culprits_caution():
    # an open case, crime.day 1, culprit wore "green raincoat" on day 1; cases.dress(d) for d in 2..20
    # never "green raincoat" for the culprit; after cases.close(file, None) a later day may pick it (not asserted); cautious(1) == {}

# test_player.py
async def test_an_episode_is_judged_on_what_the_accused_wore_that_day():
    # crime day 1, clip coat = culprit's day-1 outfit; town.worn[2][culprit] differs; game day 2
    # publish(culprit, [clip id]) holds
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "dress or worn or crime_day or wore"`. Expected: they FAIL on `wardrobe`, `dress` and `looks` being undefined.

- [ ] **Step 3: Implement**
  - Add the `Town` methods and state above, and `Villager.wardrobe`.
  - In `case.py`, read looks on the crime's day everywhere it now reads `.traits`: `witness_memories`, `camera_clip`, `scene_clues`, `suspects` (`town.looks(v.id, crime.day)`), and `make_solvable` (the culprit, `best` and `narrowed`).
  - In `player.py`, `_seen` passes `self.town.looks(crime.culprit, crime.day)` to `recall_more`, and `publish` calls `holds(crime, culprit_id, self.town.looks(culprit_id, crime.day), ...)`.
  - `Cases.on_tick` calls `self.dress(day)` first. `__main__` calls `engine.cases.dress(game.day)` after the resume/fresh branch and before `engine.run()`.
  - Set `STATE_VERSION = 23`.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Record a daily outfit for everyone and judge evidence on what was worn"
```

---

### Task 2: Wardrobes for every resident, in the generated and the practice town

**Files:**
- Modify: `sleuth/traits.py`, `sleuth/town_gen.py`, `sleuth/tutorial.py`, `sleuth/README.md`
- Test: `sleuth/tests/test_traits.py`, `sleuth/tests/test_town_gen.py`, `sleuth/tests/test_tutorial.py`, plus `test_case.py` and `test_cases.py` helpers

**Interfaces:**
- Consumes: `Villager.wardrobe`, `Town.worn`, `Town.looks` (Task 1)
- Produces: `traits.FIXED = ("height", "hair", "car")` and `traits.WARDROBE = 3`. `assign_traits` deals only `FIXED` (evenly, with unique fixed looks while possible) and sets `v.wardrobe = rng.sample(TRAITS["coat"], WARDROBE)`. `tutorial.RESIDENTS`' coat column becomes a 3-tuple wardrobe. `Practice.__init__` sets `self.town.worn[1] = {vid: wardrobe[0]}`.

- [ ] **Step 1: Write the failing tests**

```python
# test_traits.py (replace the unique-combinations test)
def test_assign_traits_gives_fixed_looks_and_a_wardrobe_of_three():
    vs = ring(50); assign_traits(vs, random.Random(3))
    assert all(set(v.traits) == set(FIXED) for v in vs)
    assert len({tuple(sorted(v.traits.items())) for v in vs}) == 50
    assert all(len(set(v.wardrobe)) == 3 and set(v.wardrobe) <= set(TRAITS["coat"]) for v in vs)
# the balanced and >375 tests iterate FIXED instead of TRAITS

# test_town_gen.py
async def test_load_or_generate_rejects_a_village_without_wardrobes(tmp_path):
    # a seed whose villagers have traits but wardrobe == [] -> SeedMismatch match="before outfits"

# test_tutorial.py
def test_practice_residents_own_three_outfits_and_wear_the_first_on_day_one():
    p = practice()
    assert all(len(set(v.wardrobe)) == 3 and set(v.traits) == {"height", "hair", "car"} for v in p.town.villagers)
    assert all(p.town.outfit(v.id, 1) == v.wardrobe[0] for v in p.town.villagers)
    assert p.town.outfit("t5", 1) == p.town.outfit("t6", 1) == "green raincoat"
# update test_only_the_witness_and_the_clue_together_narrow_it_to_the_culprit and test_the_practice_town_keeps_the_town_s_rules
# to use p.town.looks(vid, 1) where they read .traits
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "wardrobe or outfits or practice"`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - Update `assign_traits` as above. `_look` reads `FIXED`.
  - `load_or_generate` raises `SeedMismatch(f"{path} is a town from before outfits; delete it")` when any villager has no wardrobe. Keep the existing "before Sleuth" check first.
  - Tutorial wardrobes, first item unchanged from today's coat:
    - Ruth `("denim jacket", "black puffer", "plaid flannel")`
    - Dev `("grey hoodie", "denim jacket", "green raincoat")`
    - Tess `("plaid flannel", "grey hoodie", "black puffer")`
    - Gus `("black puffer", "plaid flannel", "denim jacket")`
    - Cal `("green raincoat", "plaid flannel", "grey hoodie")`
    - Ivy `("green raincoat", "denim jacket", "black puffer")`
  - Test helpers that call `assign_traits` and then stage evidence (`make_case` in `test_case.py`, and the equivalents in `test_cases.py`) now call `town.dress(day, Random(0))` for the crime day.
  - README:
    - Under **The town**, residents have fixed height, hair and car, plus three outfits. The game picks one each day and records it, and a culprit with an open case stays out of their crime outfit.
    - In the evidence table, "coat" becomes "what they wore then".

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Give every resident three outfits, in new towns and the first-case town"
```

---

### Task 3: Looks are learned by talking, and never sent before

**Files:**
- Modify: `sleuth/traits.py` (`IN_PERSON`, `BY_WORD`), `sleuth/player.py`, `sleuth/feed.py`, `sleuth/web.py`, `sleuth/persist.py` (`STATE_VERSION = 24`), `sleuth/README.md`
- Test: `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`, `sleuth/tests/test_feed.py`

**Interfaces:**
- Consumes: `Town.looks` (Task 1)
- Produces:
  - `traits.IN_PERSON = ("height", "hair", "coat")` and `traits.BY_WORD = ("height", "hair", "car")`
  - `Player.known: dict[str, list[dict]]`: vid → entries, oldest first, at most `KNOWN_KEPT = 4`. Each entry is `{"looks": dict[str, str], "how": "talked" | "described" | "photo", "by": str | None, "day": int, "phase": str}`. It is saved in `_progress`/`_resume` (so a replay keeps the town's), and reset to `{}` in `replay()` and in `_graduate`'s fresh branch.
  - `Player.learn(vid: str, looks: dict[str, str], how: str, by: str | None = None, day: int | None = None, phase: str | None = None) -> None`: day and phase default to the game's. The entry is skipped when it equals the newest one on `looks`, `how`, `by` and `day`. Otherwise it is appended and trimmed, and `feed.on_known(self.person(vid), player=self.id)` is emitted.
  - `Player.person(vid: str) -> dict`: `{"id", "name", "occupation", "home", "looks": describe(newest["looks"]), "how": learned(newest, town), "face": face(newest["looks"])}` for a known resident, and `"looks": "", "how": "", "face": None` otherwise
  - `Player.known_json(vid: str) -> list[dict]`: `[{"looks": describe(e["looks"]), "how": learned(e, town), "face": face(e["looks"])}]`, oldest first
  - `player.learned(entry: dict, town: Town) -> str`: "you talked, day 3", "Bev described, day 3" (the describer's first name), or "in a photo, day 2"
  - `Feed.on_known(person: dict, *, player: str)` emits kind `"known"` with `villager=person`
  - `web.villagers(player: Player) -> list[dict]`: `player.person` for each resident, sorted by name. `/api/villagers/{vid}` drops `traits` and `traits_text` and adds `"known": player.known_json(vid)`.

- [ ] **Step 1: Write the failing tests**

```python
# test_web.py (replace test_state_lists_each_villagers_looks_and_face and the traits assertions in the inspect test)
def test_nothing_sent_shows_unlearned_looks(game):
    # give v1 and v2 full looks and a recorded outfit; open a case with v2 as culprit
    state = game.client.get("/api/state").json()
    rows = state["villagers"]
    assert all(r["looks"] == "" and r["how"] == "" and r["face"] is None for r in rows)
    assert set(rows[0]) == {"id", "name", "occupation", "home", "looks", "how", "face"}
    card = game.client.get("/api/villagers/v2").json()
    assert "traits" not in card and "traits_text" not in card and card["known"] == []
    sent = json.dumps([state, game.client.get("/api/case").json(), card])
    assert not any(c in sent for c in TRAITS["coat"])

def test_state_shows_learned_looks_and_how(game):
    # player.learn("v1", {"height": "tall", "hair": "bald", "coat": "denim jacket"}, "talked")
    # row["looks"] == "tall, bald, in a denim jacket" and row["how"] == "you talked, day 1"
    # row["face"] == {"hair": None, "coat": COLOURS["denim jacket"], "height": 2}

# test_player.py
async def test_talking_shows_how_they_look_today():
    # game day 2; town.worn[2]["v1"] = "plaid flannel"; interview v1
    # player.known["v1"][-1] == {"looks": {"height": ..., "hair": ..., "coat": "plaid flannel"}, "how": "talked", "by": None, "day": 2, "phase": game.phase}
    # a "known" event for the player carries person("v1"); talking again the same day adds no entry

async def test_a_refused_question_teaches_nothing():
    # regard below guarded_at, or past MESSAGES_PER_PART -> "v1" not in player.known

def test_known_round_trips_and_resets_on_leaving_the_first_case():
    # learn in the practice town; Player.restore(to_state()) keeps known; skip() -> known == {}
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "learned or unlearned or talking_shows or refused_question or known_round"`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - In `_interview`, after the guard and limit checks pass and the thread entry is appended, call `self.learn(vid, {c: v for c, v in self.town.looks(vid, day).items() if c in IN_PERSON}, "talked")`, where `day` is `self.game.day` (or 0 without a game).
  - Wire `web.py` to `villagers(player)` and `known_json`.
  - Set `STATE_VERSION = 24`.
  - README:
    - The people list shows name, job, street and household.
    - Looks show only once learned, each with how and when.
    - Talking to someone shows how they look today.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass. The page still works, because rows keep `looks` and `face` and a `null` face draws today's default.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Show a resident's looks only once the podcaster has learned them, starting with talking"
```

---

### Task 4: Residents describe people they know

**Files:**
- Modify: `sleuth/interview.py` (`KINDS`), `sleuth/player.py` (`_known`, `steps`), `sleuth/README.md`
- Test: `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py` (the step text and count tests)

**Interfaces:**
- Consumes: `Player.learn`, `BY_WORD` (Task 3), `Town.looks` (Task 1)
- Produces:
  - `KINDS["what_do_they_look_like"] = 'what someone else looks like, as in "What does Cal look like?"'`
  - `player.acquainted(speaker: Villager, about: Villager) -> bool`: `about.id in speaker.relationships`, or a shared non-empty household
  - In `_known`, kind `what_do_they_look_like` with `about`:
    - If acquainted, `looks = {c: v for c, v in town.looks(about.id, day).items() if c in BY_WORD}`.
    - Return `[self._statement(file, vid, f"{name} says {about.name} is {describe(looks)}.", True, who=about.id)]`, with `traits=looks` set on the record, and call `self.learn(about.id, looks, "described", by=vid)`.
    - Otherwise return `[], []`, which gives a shrug.
  - A new checklist step at index 2, before search:
    - `{"text": "Find out how people look", "why": "Witnesses see looks, not names. Talking to someone shows how they look today, and people can describe those they know.", "done": any(v not in (crime.victim, witness.id) for v in self.known), "action": "look"}`

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_resident_describes_someone_they_know():
    # route stub returns kind "what_do_they_look_like", who="t5", asked of t1 (Ruth, Cal's rival) in the practice town
    # the new statement record: text == "Ruth Okafor says Cal Hughes is tall, red-haired, with a red pickup.",
    #   traits == {"height": "tall", "hair": "red-haired", "car": "red pickup"}, who == "t5", holder == "t1", sound
    # player.known["t5"][-1]["how"] == "described" and ["by"] == "t1"; player.person("t5")["how"] == "Ruth described, day 1"

async def test_a_stranger_cannot_describe_them():
    # asked of t3 (Tess) about t6 (Ivy): no tie, other household -> no record, "t6" not in player.known

async def test_the_first_case_asks_to_learn_how_people_look():
    steps = player.steps()
    assert [s["text"] for s in steps][2] == "Find out how people look" and not steps[2]["done"]
    # talking to the victim and the witness leaves it undone; talking to Dev (t2) ticks it
```

Update the existing step tests (`test_player.py` around lines 826–1069 and `test_web.py`) for five steps.

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "describe or stranger or learn_how"`. Expected: FAIL.

- [ ] **Step 3: Implement** the kind, the `_known` branch and the step as above. README: under **Interview**, add "what someone looks like (only from someone who knows them)". In the first-case paragraph, list the new step.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Let residents describe people they know, and teach it in the first case"
```

---

### Task 5: Photo posts on the neighborhood app

**Files:**
- Create: `sleuth/photos.py`, `sleuth/tests/test_photos.py`
- Modify: `sleuth/engine.py`, `sleuth/cases.py` (`hidden`), `sleuth/feed.py`, `sleuth/player.py` (`save_photo`), `sleuth/tutorial.py` (`Practice.album`), `sleuth/web.py`, `sleuth/persist.py` (`"album"` component, `STATE_VERSION = 25`), `sleuth/README.md`
- Test: `sleuth/tests/test_photos.py`, `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`, `sleuth/tests/test_persist.py`

**Interfaces:**
- Consumes: `Town.looks`, `IN_PERSON`, `Player.learn`
- Produces:
  - In `photos.py`:
    - `PHOTO_PHASES = ("morning", "afternoon", "evening")`, `PEOPLE = (2, 3)`, `KEPT = 60`
    - `@dataclass Photo(id: str, place: str, day: int, phase: str, people: dict[str, dict[str, str]], caption: str)`: `people` maps vid → `IN_PERSON` looks on that day
    - `class Album`:
      - `__init__(self, rng: Random | None = None)`
      - `photos: list[Photo]`, newest last
      - `to_state()` / `restore(state)`
      - `get(photo_id) -> Photo | None`
      - `take(town, day, phase, whereabouts: dict[str, list[str]], ids: Ids, exclude: set[str] = frozenset()) -> Photo | None`: picks a public place with 2 or more logged residents not excluded, then 2–3 of them. The caption is `f"{phase.capitalize()} {at(place)}: " + ", ".join(f"{name} in a {coat}")` + "." and the id is `ids.next("r")`.
    - `photo_json(photo: Photo, town: Town) -> dict`: `{"id", "place", "day", "phase", "caption", "people": [{"id", "name", "looks": describe(l), "face": face(l)}]}`, with names from `town.name_of`
  - `Cases.hidden(day: int, phase: str) -> set[str]`: culprits of cases not closed whose crime is on that day and phase
  - `Engine(album: Album | None = None)` → `self.album`. `Engine._photograph(day: int, phase: str, finished: dict[str, list[str]]) -> None`:
    - When `players.any_playing()`, it takes a photo with `exclude=self.cases.hidden(day, phase)` (or an empty set without cases) and emits `feed.on_photo(photo_json(...))`.
    - `_clock_loop` records `(day, phase)` before `game.tick()` and calls it after the cases tick.
  - `Feed.on_photo(photo: dict)` is public, kind `"photo"`, with line `f"New photo: {caption}"`. `Feed.on_photo_saved(photo_id: str, records: list[dict], *, case_id: str | None, player: str)` is kind `"photo_saved"`.
  - `Player.save_photo(photo_id: str) -> str | None`:
    - Unknown photo: "That photo isn't on the app any more."
    - Otherwise it calls `learn(vid, looks, "photo", day=photo.day, phase=photo.phase)` for each person still in town.
    - With an open case, it sets `notebook[photo.id] = Record(photo.id, file.crime.id, "photo", photo.place, "", photo.caption, day=photo.day)`.
    - It emits `on_photo_saved`.
  - `Practice.album = Album()` (always empty).
  - `POST /api/photos/save` with `{"photo_id": "r-1"}` returns 400 `BAD_PHOTO = 'Send JSON like {"photo_id": "r-1"}.'` on a bad body. It is not gated by resting, since it costs nothing.

- [ ] **Step 1: Write the failing tests**

```python
# test_photos.py
def test_a_photo_shows_two_or_three_people_who_were_there_in_what_they_wore():
    # 4 residents logged at the bar in the evening of day 2 with recorded outfits
    p = Album(Random(1)).take(town, 2, "evening", whereabouts, Ids())
    assert p.place == "bar" and 2 <= len(p.people) <= 3 and set(p.people) <= set(at_bar)
    assert all(p.people[v] == {c: town.looks(v, 2)[c] for c in IN_PERSON} for v in p.people)
    assert p.caption.startswith("Evening at the bar: ") and all(town.get(v).name in p.caption for v in p.people)

def test_no_photo_at_night_or_with_fewer_than_two_people(): ...

def test_a_culprit_is_never_photographed_at_their_crime():
    # 50 takes with exclude=cases.hidden(day, phase) for an open case on that day and phase -> culprit never in people

def test_the_album_keeps_the_newest_and_round_trips():
    # 65 takes -> len == 60, oldest dropped; Album().restore(a.to_state()).photos == a.photos

# test_player.py
async def test_saving_a_photo_teaches_looks_and_adds_a_notebook_entry():
    # known[vid][-1] == {"looks": photo.people[vid], "how": "photo", "by": None, "day": photo.day, "phase": photo.phase}
    # person(vid)["how"] == "in a photo, day 2"; notebook[photo.id].kind == "photo" with the open case's id
    # save_photo("r-999") == "That photo isn't on the app any more."

# test_web.py
def test_save_photo_endpoint(game): ...  # 200 on a known photo, 400 BAD_PHOTO on {"photo_id": 3}
def test_photos_are_public_but_not_shown_in_the_practice_town(game): ...  # feed.sees(practising, photo event) is False

# test_persist.py
def test_components_include_the_album(): ...
```

- [ ] **Step 2: Run them to see them fail.** `PYTEST -k "photo or album"`. Expected: FAIL.

- [ ] **Step 3: Implement** as above. Set `STATE_VERSION = 25`. README: add a **Photos** paragraph covering up to three photos a day at public places while someone plays, that each is true, that saving one adds it to the notebook and shows who's in it, and that a case never needs one.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Post a few true photos a day on the neighborhood app, and let podcasters save them"
```

---

### Task 6: The page shows learned looks and silhouettes

**Files:**
- Modify: `sleuth/static/index.html`
- Test: `sleuth/tests/test_web.py` (string checks on the served page, as the existing page tests do)

**Interfaces:**
- Consumes:
  - rows `{id, name, occupation, home, looks, how, face}`
  - card `known: [{looks, how, face}]`
  - event `{"kind": "known", "villager": row}`
  - step `action: "look"`
- Produces:
  - `drawFace(v)` draws `silhouette(g)` when `!v.face`: the tint background, and a head and shoulders in one grey, with no hair or eyes.
  - The `faces` cache is keyed by `` `${v.id}:${JSON.stringify(v.face)}` ``.

- [ ] **Step 1: Write the failing test**

```python
def test_page_draws_learned_looks_and_a_silhouette(game):
    page = game.client.get("/").text
    for s in ('case "known":', "function silhouette(", "JSON.stringify(v.face)", 'look: "find"'):
        assert s in page
    assert "traits_text" not in page
```

- [ ] **Step 2: Run it to see it fail.** `PYTEST -k silhouette`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - **People row:** the small line shows `occupation, atPlace(home)`. When `v.looks` is set, a second small line shows `` `${v.looks} (${v.how})` ``.
  - **Search:** looks are searched only through `v.looks`. The placeholder becomes "Find by name, job, known looks, or nearby".
  - **`drawConvo`:**
    - `convo-meta` shows occupation and home, without traits.
    - `about-list` gets a "Looks" `dt`, with one `dd` per known entry: `` `${k.looks} (${k.how})` ``.
    - With none, the `dd` reads "Unknown. Talk to them, ask someone who knows them, or save a photo they're in."
  - **`render`:** `case "known": if (fresh) { replace the row in residents by id; drawPeople(); if (selected === e.villager.id) choose(selected, true); }`
  - **Steps:** `ACTION_BUTTON` gains `look: "find"`.
  - **Witness beat:** keep its line. The search turns up only known looks now.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass. Optionally run `SLEUTH_WEB_PORT=8790 python -m sleuth` with a local Contex. Faces should be silhouettes until you talk to someone.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Draw faces from learned looks and show unknown residents as silhouettes"
```

---

### Task 7: The page's photo feed

**Files:**
- Modify: `sleuth/static/index.html`
- Test: `sleuth/tests/test_web.py`

**Interfaces:**
- Consumes:
  - event `{"kind": "photo", "photo": {...}}` (from `photo_json`)
  - event `{"kind": "photo_saved", "photo_id", "records", "case_id"}`
  - `POST /api/photos/save`
- Produces:
  - In the left column after Town talk, `<section class="photos" id="photos-box" hidden><div class="book-head"><h2>Photos</h2><small>newest first</small></div><ol class="photo-feed" id="photos" aria-label="Photos, newest first"></ol></section>`, scrolling at `max-height: 22rem`.
  - `GROUPS` gains `"Photos"`, and `GROUP_OF.photo = "Photos"`.

- [ ] **Step 1: Write the failing test**

```python
def test_page_has_a_photo_feed(game):
    page = game.client.get("/").text
    for s in ('id="photos"', 'case "photo":', 'case "photo_saved":', "/api/photos/save", 'photo: "Photos"'):
        assert s in page
```

- [ ] **Step 2: Run it to see it fail.** `PYTEST -k photo_feed`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - **`case "photo"`:** prepend an `li` to `#photos`. It holds the people's big faces (`faceWith({id, face}, true)`), the caption, `` `${capital(atPlace(place))}, day ${day}, ${phase}` ``, and a Save button that posts `{photo_id}` and reports errors in a status line. The button reads "Saved" and is disabled once `notebook` or a `photo_saved` event has the id. Then unhide `#photos-box`.
  - **`case "photo_saved"`:** `note(e.records)`, then mark the button saved.
  - **`reset()`:** empty `#photos` and hide the box.
  - Hide `#photos-box` while citing, alongside `#talk`.

- [ ] **Step 4: Run the full checks.** Run `PYTEST`, `ruff check .` and `NODECHECK`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add sleuth && git commit -m "Add a scrollable photo feed to the page, with saving into the notebook"
```
