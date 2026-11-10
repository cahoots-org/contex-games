# Sleuth: A Show That Grows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a podcaster's progress visible and fun: listeners instead of points, an archive of their episodes, credit for good detective work, and milestones the town feels.

**Architecture:** `Player` (sleuth/player.py) swaps `standing` for `listeners` and `peak`, keeps an `episodes` archive, and works out milestones from `peak`. A new `sleuth/credit.py` decides what a held episode earns credit for. The page (`sleuth/static/index.html`) shows the show in the case rail and the archive in a dialog.

**Tech Stack:** Python 3.12, pytest (`uv run --with-requirements requirements-dev.txt python -m pytest sleuth -q`), ruff, one HTML page with inline JS.

**Spec:** `docs/superpowers/specs/2026-10-25-sleuth-design.md`, section "Addendum, 2026-11-01: a show that grows". It is binding.

## Global Constraints

- Code owns every case fact; Haiku only phrases; Jev only judges.
- The API never reveals `sound`, `disproof`, a liar, a secret, an offender, or which evidence is true. Reception lines name only pieces the author has in their notebook.
- Podcasters are anonymous: nothing public names or describes a podcaster.
- Progress never goes backwards: tiers and milestones follow `peak`, the most listeners ever had.
- `STATE_VERSION` in sleuth/persist.py goes 41 → 42 once, in Task 1; old saves are set aside, the town kept.
- The tutorial (practice case) earns no listeners and adds nothing to the archive, as it earns no standing today.
- Copy is plain and in-world, sentence case, no meta wording.
- Small CI-green commits, test first; whole suite and ruff before each commit.

## Review Focus

1. **A wrong episode after a milestone** costs listeners but keeps the tier, the milestone's effect and the next-milestone line based on `peak`. Test in Task 1.
2. **Crossing two milestones in one episode** (a major case with credit) fires each milestone once, in order. Test in Task 4.
3. **Another podcaster's view** never carries this podcaster's listeners, archive, reception or milestone line. Test in Tasks 2 and 4.
4. **A held episode citing a false piece it was forgiven for** earns no "caught" credit for that piece. Test in Task 3.
5. **A save from before the change** loads as a fresh podcaster in the kept town. Test in Task 1.

---

### Task 1: Listeners, tiers by peak, and the show in the rail

**Files:**
- Modify: `sleuth/player.py` (`standing` → `listeners`/`peak`, `tier`, `_rank`, `standing_json`, `to_state`/`restore`), `sleuth/config.py` (`serious_at = 500`, `major_at = 1500`), `sleuth/feed.py` (`on_standing`), `sleuth/persist.py` (42), `sleuth/web.py` (state key), `sleuth/static/index.html` (rail)
- Test: `sleuth/tests/test_player.py`, `sleuth/tests/test_persist.py`, `sleuth/tests/test_web.py`

**Interfaces:**
- Produces: `LISTENERS = {"petty": 100, "serious": 300, "major": 800}`, `WRONG_COST = 100`; `Player.listeners: int`, `Player.peak: int`; `Player.tier` from `peak`; `MILESTONES: tuple[tuple[int, str], ...]` in player.py, in order: `(250, "Record-keepers start sharing with you.")`, `(500, "Serious cases come to you.")`, `(1000, "People open up to you.")`, `(1500, "Major cases come to you.")`, `(2500, "The town knows your show.")`; `Player.show_json() -> dict` = `{"listeners": int, "tier": str, "label": str, "next": {"at": int, "text": str} | None}` (replaces `standing_json`); `Player._rank(held, crime, bonus=0)` adds `LISTENERS[tier] + bonus` when held, else subtracts `WRONG_COST` floored at 0; updates `peak`; emits `feed.on_show(show_json, line, player=)` (renamed from `on_standing`).
- Rail copy: a "Your show" heading, then "1,250 listeners" (thousands separator, "1 listener" singular), then "Next: 1,500 listeners. Major cases come to you." in muted text; nothing after 2500. Replaces the "New podcaster · 0 points" line.

- [ ] **Step 1: Failing tests**
  - `test_a_held_episode_brings_listeners_by_tier` (100 / 300 / 800).
  - `test_a_wrong_episode_costs_listeners_but_never_below_zero`.
  - `test_a_wrong_episode_never_takes_away_a_tier` — peak 600, listeners drop to 500 then 400: tier stays "serious", `next` is the 1000 milestone.
  - `test_the_show_names_the_next_milestone` — exact `next` dicts at 0, 300 and 2600 (None).
  - `test_listeners_and_peak_survive_a_save` and `test_a_save_from_before_listeners_is_set_aside` (version 41).
  - Page: the state payload carries `show`, and the rail renders "Your show".
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Rename uses of `standing`, `standing_json`, `on_standing` and the page's `standing` handling to the show names.
- [ ] **Step 4:** Whole suite green; ruff clean; `node --check` on the page's script.
- [ ] **Step 5: Commit** "Measure a podcaster's progress in listeners".

---

### Task 2: The archive of episodes

**Files:**
- Modify: `sleuth/player.py` (`episodes`, `publish`, `to_state`/`restore`), `sleuth/web.py` (state payload), `sleuth/static/index.html` (a "Your episodes" button in the case rail opening a dialog)
- Test: `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`

**Interfaces:**
- Consumes: Task 1's `_rank`.
- Produces: `Player.episodes: list[dict]`, newest last, each `{"case": crime id, "title": crime_title, "named": accused name, "held": bool, "listeners": signed int change, "reception": list[str], "day": game day}`; `Player.episodes_json() -> list[dict]` newest first; state payload key `episodes`; the episode feed event for the author carries `listeners` and `reception`.
- `publish` on a town case appends one entry after `_rank` (reception is `[]` until Task 3). The practice case appends nothing.
- Dialog: titled "Your episodes"; each row: title, "You named {named}.", "Held up" or "Didn't hold up", "+300 listeners" / "−100 listeners", then reception lines. Empty: "No episodes yet. Publish one when you've cracked a case."

- [ ] **Step 1: Failing tests**
  - `test_each_published_episode_goes_in_the_archive` — held and wrong both recorded with the right signs.
  - `test_the_practice_case_adds_nothing_to_the_archive`.
  - `test_the_archive_survives_a_save`.
  - `test_only_the_author_sees_their_archive` — another player's state payload has their own (empty) archive.
- [ ] **Step 2–4:** Run, implement, whole suite + ruff + `node --check`.
- [ ] **Step 5: Commit** "Keep an archive of a podcaster's episodes".

---

### Task 3: Credit for good detective work

**Files:**
- Create: `sleuth/credit.py`
- Modify: `sleuth/player.py` (`publish` passes the bonus to `_rank` and the lines to the archive and event)
- Test: `sleuth/tests/test_credit.py` (new), `sleuth/tests/test_player.py`

**Interfaces:**
- Consumes: `Record` (`sound`, `disproof`, `kind`, `holder`, `who`), `CaseFile` (`records`, `liars`, `accomplice`, `crime`), `episode.label(r, town)` for naming a piece.
- Produces: `CREDIT_BONUS = 50`; `credits(file: CaseFile, cited: list[Record], notebook: dict[str, Record], town: Town) -> list[str]`, reception lines in this order, each kind at most once:
  - **caught:** a notebook record with `kind in ("memory", "clue")`, `not sound`, not cited, whose `disproof` is a cited record id → "Listeners loved how you caught {label}." (first such record).
  - **alibi:** a notebook `statement` with `not sound` and a `disproof` that is cited, from the accomplice → "Listeners loved how you broke {holder first name}'s alibi for {culprit first name}."
  - **liar:** a liar in `file.liars` whose unsound claim statement is in the notebook, and the podcaster also holds what exposes them (the exposing record, or a sound statement with `who == liar`) → "Listeners loved that you didn't fall for {liar first name}'s story."
  - **no witness:** the case's records hold no `memory` except a mugging victim's own → "Listeners loved that you cracked it without a single witness."
  - none → `["A solid episode."]`, bonus 0.
- The bonus is `CREDIT_BONUS` × the number of credit lines (not counting "A solid episode."). Only held town episodes earn credit.

- [ ] **Step 1: Failing tests** — one per kind with exact strings; `test_a_cited_false_piece_earns_no_credit_for_catching_it`; `test_each_kind_of_credit_counts_once`; `test_a_plain_held_episode_is_a_solid_episode`; `test_credit_adds_bonus_listeners` (petty + 2 kinds = 200).
- [ ] **Step 2–4:** Run, implement, whole suite + ruff.
- [ ] **Step 5: Commit** "Give credit for good detective work".

---

### Task 4: Milestones the town feels

**Files:**
- Modify: `sleuth/player.py` (`_rank` fires milestones; `pull`; `_seen`; `_notes`), `sleuth/feed.py` (`on_milestone`), `sleuth/static/index.html` (the milestone line in the conversation area)
- Test: `sleuth/tests/test_player.py`, `sleuth/tests/test_web.py`

**Interfaces:**
- Consumes: Task 1's `peak` and `MILESTONES`.
- Produces: `Player._milestones(before: int, after: int)`: for each milestone with `before < at <= after`, in order: `feed.on_milestone(at, text, player=self.id)` (the author's line: "{at:,} listeners. {text}") and a public app post `Utterance("", "app", APP, <the case place>, f"A local true-crime podcast just passed {at:,} listeners.", None, "posted")` via `feed.on_post(..., None)`.
- Effects, each read from `peak`:
  - `pull`: at `peak >= 250` the keepers' guarded check is skipped.
  - `_seen`: a witness recalls more when regard ≥ `trusted_at`, or when `peak >= 1000` and regard ≥ 0.
  - `_notes`: at `peak >= 2500`, add "You know this podcaster's true-crime show, and you're a little starstruck." (colours replies only).

- [ ] **Step 1: Failing tests**
  - `test_crossing_a_milestone_tells_the_podcaster_and_posts_without_naming_them` — the post text matches exactly and carries no player id or name.
  - `test_crossing_two_milestones_at_once_fires_both_in_order`.
  - `test_a_milestone_fires_once_even_after_falling_back_below_it`.
  - `test_record_keepers_share_from_250_listeners`.
  - `test_witnesses_open_up_from_1000_listeners_unless_they_dislike_you`.
  - `test_residents_know_the_show_from_2500_listeners`.
  - `test_another_podcaster_never_sees_the_milestone_line`.
- [ ] **Step 2–4:** Run, implement, whole suite + ruff + `node --check`.
- [ ] **Step 5: Commit** "Let the town feel a podcaster's milestones".
