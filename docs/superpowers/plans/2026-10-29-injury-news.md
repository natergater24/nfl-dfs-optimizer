# Injury Tags, News and Backup Plans — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every injury tag (with body part and the latest news blurb) on the NFL and NBA pages, keep unlikely-to-play players out of every app-made recommendation, discount questionable players, and attach a healthy 1:1 or two-player backup to any tagged player in a lineup.

**Architecture:** One shared module `nfldfs/injuries.py` (tags, news lean, Sleeper + ESPN fetching, matching, the "recommendable" rule). Each sport's engine uses it: the pool gains injury columns, simulations make questionable players sit in 15% of outcomes, every suggestion path filters on `recommendable`, and a per-sport `injury_backups(...)` finds replacements. Builds publish the injury columns and precomputed backups; the app shows chips, an "🩹 Injury watch" box, filters, and computes backups on the device for lineups Nathan changes.

**Tech Stack:** Python 3.14 via `./py` (hosted 3.12), pandas, numpy, requests, PuLP, Streamlit 1.58.

**Spec:** `docs/superpowers/specs/2026-10-29-injury-news-design.md`.

## Global Constraints

- `./py` only; app code 3.12-compatible; atomic writes; `-W error` green and the suite fast (~30 s); no network in tests (fixtures/fake sessions); never run real stages, publish, launchctl or pmset in tests.
- Tag source of truth: DraftKings `Status`. Normalized tags: `Q`, `GTD`, `P`, `D`, `OUT`, `IR` (NBA's `O` → `OUT`; blank → `""`).
- Classes: `P` and `""` → healthy; `Q`, `GTD` → questionable; `D`, `OUT`, `IR` → excluded.
- **Never** in any app-made suggestion (recommended lineups, alternates, swaps, backups, late-swap re-picks): excluded-class players, or questionable players whose lean is `"out"`.
- Questionable (not lean-out): `Q_PLAY_PROB = 0.85` — scores 0 in 15% of simulations (seeded, deterministic) and objective weight × 0.85. Displayed median/floor/ceiling stay the when-he-plays numbers.
- Lean reading (Q/GTD only; latest blurb ≤ 72 h old; case-insensitive). Only **game-level** statements decide; practice notes never make a player "out" (Nathan: players sometimes miss practice and still play):
  - game-out: "ruled out", "will not play", "won't play", "not expected to play", "unlikely to play", "will miss", "expected to miss", "out for", "listed as doubtful", "doubtful to play"
  - game-in: "expected to play", "will play", "on track to play", "cleared to play", "upgraded", "removed from the injury report", "probable", "no injury designation"
  - practice-only (neutral → "unclear" unless a game-level statement exists): "did not practice", "dnp", "limited", "full participant", "full practice", "rest day", "veteran rest", "maintenance"
  - Rules: any game-in beats practice notes; between game-level statements the later one in the text wins; "not"/"no longer"/"isn't" within 3 words before a phrase flips it (e.g. "isn't expected to play" → out, "no longer expected to miss" → in). Return "out" / "in" / "unclear".
- User locks / user-built lineups win whatever the tag or lean, shown with ⚠ for excluded-class or lean-out, plus a backup.
- Backups use healthy players only (tag `""` or `P`), same eligible slot, under the cap, not already in the lineup, sport rules kept (NBA ≥2 games); ranking and "before → after" use the contest metric (`nfldfs.sim_eval.contest_metric` against field scores), like today's swaps. Prefer the best 1:1; if none fits, the best two-player rework (the tagged player + one other spot); else the message "No healthy replacement fits under the cap."
- Sources: Sleeper `https://api.sleeper.app/v1/players/{nfl|nba}` (one call per sport per run); ESPN `https://site.web.api.espn.com/apis/common/v3/sports/{football/nfl|basketball/nba}/athletes/{espn_id}/overview` → `rotowire.{headline,story,published}`; fetch news only for tagged players + players in recommended lineups/alternates; 0.2 s between ESPN requests, 10 s timeout; any failure leaves the tag without news and never fails a build (add a `"; WARNING: injury news unavailable (<Exc>)"` note).
- Chips: `Q`/`GTD` yellow, `D` orange, `OUT`/`IR` red, `P` gray; lean shown as "📰 leans out" / "📰 leans in". News age like "2 h ago".
- Pages built before this feature (no injury columns / files) must still load, showing no tags.

## Review Focus

1. **Sleeper or ESPN is down or changes shape** → build succeeds, DraftKings tags still show, a WARNING note appears → Task 1 `test_sources_down_keep_tags`, Task 2 `test_nfl_build_survives_news_failure`.
2. **DK says Q but the blurb says "ruled out"** → that player is in no recommended lineup, alternate, swap or backup → Task 2 `test_lean_out_excluded_everywhere_nfl`, Task 3 `test_lean_out_excluded_everywhere_nba`.
3. **A questionable player in a recommended lineup and no healthy 1:1 fits the cap** → two-player rework, else the no-fit message → Task 2 `test_backup_falls_back_to_two_player`, `test_backup_none_message`.
4. **Name/team mismatches between DK and Sleeper** (Jr./accents; team codes like `JAX`/`JAC`, `LAR`/`LA`, `PHO`/`PHX`, `WAS`/`WSH`, `NOP`/`NO`, `GSW`/`GS`, `SAS`/`SA`, `NYK`/`NY`, `UTA`/`UTAH`) → still matched, or tag kept without extras → Task 1 `test_sleeper_match_aliases`.
5. **Old published data without injury columns** → both pages load with no chips → Task 4 `test_pages_load_without_injury_data`.

---

### Task 1: Shared injury core (`nfldfs/injuries.py`)

**Files:** Create `nfldfs/injuries.py`, `tests/test_injuries.py`, fixtures `tests/fixtures/sleeper_nfl_sample.json`, `sleeper_nba_sample.json` (≈30 trimmed real players each incl. injured ones), `espn_overview_sample.json` (real overview with `rotowire`); modify `nfldfs/config.py` (`Q_PLAY_PROB = 0.85`, `NEWS_MAX_AGE_H = 72`, `NEWS_DELAY_S = 0.2`).

**Interfaces — Produces:**
- `normalize_tag(status) -> str`; `tag_class(tag) -> "healthy" | "questionable" | "excluded"`.
- `lean(text: str | None, published: datetime | None, now: datetime) -> "out" | "in" | "unclear" | None` (None when no text or older than 72 h).
- `fetch_sleeper(sport: "nfl" | "nba", session=None) -> dict`; `attach_sleeper(pool, sleeper: dict, sport) -> pool` adding `body_part`, `injury_updated` (UTC ISO or ""), `espn_id` (str or "") by `nfldfs.teams.normalize_name(name)` + team (with the alias table in Review Focus 4; name-only fallback when unique).
- `fetch_news(espn_id, sport, session=None) -> dict | None` (`headline`, `story`, `published` as UTC ISO).
- `add_injury_columns(pool, sport, *, now, session=None, news_for: set[int] | None = None) -> (pool, warning: str)`: adds `inj_tag`, `inj_class`, `body_part`, `news_headline`, `news_story`, `news_published`, `lean`, `recommendable` (bool: healthy, or questionable with lean != "out"; excluded → False), `play_prob` (1.0, or `Q_PLAY_PROB` for recommendable questionable, 0 for not playable); fetches news for tagged players plus `news_for`; never raises on source errors.
- `recommendable(pool) -> np.ndarray[bool]` (falls back to `playable` when the column is absent).

- [ ] **Step 1: Tests** — `test_tags_and_classes` (incl. NBA `O`→`OUT`, `GTD` questionable, `P` healthy); `test_lean_rules` (each game-level phrase; "did not practice … but is expected to play Sunday" → "in"; "did not practice Wednesday" alone → "unclear"; "veteran rest day" → "unclear"; "isn't expected to play" → "out"; later game-level phrase wins; >72 h → None; real Lamar Jackson blurb → "in"); `test_sleeper_match_aliases`; `test_add_injury_columns` (fake sessions; Q + "ruled out" blurb → recommendable False; Q + unclear → play_prob 0.85; healthy → 1.0); `test_sources_down_keep_tags` (sessions raising → tags present, extras blank, warning text).
- [ ] **Step 2–4:** fail → implement → `./py -m pytest -q -W error` passes.
- [ ] **Step 5:** Commit `"Injury core: tags, news lean, Sleeper and ESPN sources"`.

### Task 2: NFL engine and pipeline

**Files:** Modify `nfldfs/simulate.py`, `nfldfs/lineups.py`, `nfldfs/build.py`, `run_pipeline.py` (NFL build step), `tests/test_lineups.py`, `tests/test_simulate.py`, `tests/test_build.py`, `tests/test_run_pipeline.py`.

**Interfaces — Consumes:** Task 1. **Produces:**
- `simulate(...)`: after drawing, players with `play_prob < 1` get 0 in a seeded `(1 − play_prob)` share of sims (same seed → same result; absent column → unchanged).
- Candidates, alternates, `find_swaps`, `best_lineup` (and `build_all`) use `recommendable` instead of `playable` for app-made choices; locks may still include anyone; objective × `play_prob` for questionable players.
- `injury_backups(pool, sims, field_scores, lineup_rows: list[int], contest) -> DataFrame[tagged_dk_id, kind ("1:1" | "two-player" | "none"), out_dk_ids, in_dk_ids, remaining_salary, metric_before, metric_after, message]` — one row per tagged player in the lineup, per the Global Constraints rule (NFL slot rules: same position or FLEX-eligible).
- Build: `add_injury_columns` after the pool is assembled (news for tagged + every recommended/alternate player — fetch after `build_all`, then publish), `player_pool.parquet` carries the injury columns, new `data/published/injury_backups.parquet` (`contest_key` + the columns above) for rank-0 lineups.

- [ ] **Step 1: Tests** — `test_questionable_sits_in_15pct_of_sims` (±1.5 pp over 10k sims; deterministic); `test_lean_out_excluded_everywhere_nfl` (lineups, alternates, swaps, backups); `test_doubtful_never_suggested`; `test_lock_wins_for_excluded`; `test_backup_one_to_one`; `test_backup_falls_back_to_two_player`; `test_backup_none_message`; `test_nfl_build_publishes_injury_files`; `test_nfl_build_survives_news_failure`.
- [ ] **Step 2–4:** fail → implement → full suite passes.
- [ ] **Step 5:** Commit `"NFL: injury-aware simulations, suggestions and backups"`.

### Task 3: NBA engine and pipeline

**Files:** Modify `nbadfs/dk.py` (statuses), `nbadfs/simulate.py`, `nbadfs/lineups.py`, `nbadfs/optimizer.py` (if it filters on `playable`), `nbadfs/build.py`, `run_pipeline.py` (NBA build), tests under `tests/nba/`.

**Interfaces — Consumes:** Task 1; mirrors Task 2. **Produces:** NBA `playable` = not excluded-class (D, OUT, IR now unplayable too); the same `play_prob` sims rule (must stay deterministic — the app regenerates NBA sims from the published pool, so `play_prob` and `inj_tag` are published pool columns); `recommendable` in every suggestion path (incl. `nbadfs.late_swap` once it exists — leave a note for phase 2); `injury_backups(...)` with NBA slot rules (same slot eligibility, ≥2 games); per-slate `injury_backups.parquet`; `sims_fingerprint` still matches.

- [ ] **Step 1: Tests** — `test_nba_status_classes` (D/OUT/IR unplayable, GTD questionable); `test_lean_out_excluded_everywhere_nba`; `test_nba_backup_respects_slots_and_two_games`; `test_resim_matches_with_play_prob` (written pool re-simulates to the build's sims); `test_nba_build_publishes_injury_files`.
- [ ] **Step 2–4:** fail → implement → full suite passes.
- [ ] **Step 5:** Commit `"NBA: injury-aware simulations, suggestions and backups"`.

### Task 4: App — chips, Injury watch, filters, on-device backups (both sports)

**Files:** Modify `nfldfs_app/ui.py` (chip helper), `nfldfs_app/view_recommended.py`, `view_builder.py`, `view_pool.py`, `nfldfs_app/data.py` (load `injury_backups.parquet` when present), `nbadfs_app/views.py`, `nbadfs_app/data.py`, `nfldfs_app/builder_component.py` (tag on player cards); tests `tests/test_injury_app.py`, `tests/nba/test_app.py`.

**Interfaces — Consumes:** Tasks 1–3. **Produces (UI):**
- `ui.injury_chip(tag, lean=None) -> str` (HTML span; "" when healthy-blank) used next to every player name in lineup tables, swaps, player lists, builder cards and lock/exclude labels.
- ⭐ Recommended: "🩹 Injury watch" expander (open when any tagged player is in the lineup): per tagged player — chip, body part, news headline + age (story on expand), and the backup line "If {name} sits: {in names} — ${remaining} left, {before:.0%} → {after:.0%}" with an **Apply** button (same mechanics as swaps); the published backup is used when the shown lineup is the published rank-0 lineup, otherwise computed on the device via the sport's `injury_backups`.
- 🛠 My Lineup and 🔁 Tweak & Rebuild: chips, ⚠ for excluded-class or lean-out players Nathan chose, the same backup lines computed on the device.
- Player lists: checkbox "🩹 Injured / questionable only" and a "News" column (headline + age).
- Recommended lineups (both sports): hovering a player's name shows a tooltip with his latest news (headline, age, story; tag + body part). Use pandas Styler `set_tooltips` if `st.dataframe` renders it (verify in the browser); otherwise render the lineup names with an HTML `title` attribute. Players without news show their tag only.

- [ ] **Step 1: Tests** — `test_injury_chip_colors`; `test_lineup_news_tooltip` (a player with news gets tooltip text containing his headline); `test_recommended_shows_injury_watch_and_apply` (NFL and NBA); `test_my_lineup_backup_for_user_pick` (D player Nathan added → ⚠ + backup); `test_pool_filter_injured_only`; `test_pages_load_without_injury_data`.
- [ ] **Step 2–4:** fail → implement → full suite passes.
- [ ] **Step 5: Browser check (controller):** NFL and NBA pages on real data — chips visible, Injury watch shows a real blurb and a working Apply, filters work, builder cards show tags.
- [ ] **Step 6:** Commit `"App: injury chips, Injury watch with backups, injured filter"`.

### Task 5: Docs and live check (controller)

- [ ] **Step 1:** USER_MANUAL section "🩹 Injuries" (chips, leans, what's never recommended, backups and Apply, when news updates); README line; claude-context dated section (sources, rules, published files, constants). Commit.
- [ ] **Step 2:** Merge, push, run a real NFL refresh and NBA stage on the Mac, check both phone pages (reboot if stale modules).
- [ ] **Step 3:** Next NFL Sunday 9:00/11:45 and an NBA evening: spot-check tags vs DraftKings and a few lean readings; note keyword misses.
