# NFL DFS Lineup Optimizer — Design Spec

**Date:** 2026-10-11
**Status:** Draft for review
**Project folder:** `~/Desktop/Nathan/Claude/NFL_DFS`
**Pattern reference:** `~/Desktop/Nathan/Claude/MLB_Pipeline` (README.md, USER_MANUAL.md) — this project deliberately mirrors its local-pipeline + GitHub + Streamlit Community Cloud setup.

---

## 1. Purpose and success criteria

A personal tool that, each week, gives Nathan **one recommended DraftKings NFL lineup** for the Sunday main slate plus a **short list of outlier swaps** for building his own variations — with as little weekly effort as possible.

**Success looks like:**
- Opening the app (laptop or phone) on Sunday shows a fresh, valid lineup for the chosen DraftKings contest type with no manual steps beforehand.
- Picking a **DraftKings contest type by its DraftKings name** (Head-to-Head, 50/50, Double Up, Multiplier, Single Entry / 3-Max tournament, Tournament, Large-Field Tournament) instantly shows the lineup built for that contest.
- Every player shows an estimated ownership % and a common/uncommon tier.
- Total weekly hands-on time ≈ 2 minutes (plus an optional 2-click results import on Monday).
- A downloadable CSV uploads straight into DraftKings.
- Over the season, a report card shows how projections and ownership estimates compared to reality.

**What Nathan said vs. assumptions:**
- Said: personal use; NFL; DraftKings; starting with 0 entries and experimenting in small Sunday contests; both cash and tournaments; contest-type selector using DraftKings' own contest names (2026-10-12); ownership common/uncommon labels; minimal upkeep; streamlined refresh; mirror MLB project's Streamlit + git workflow; Vegas-anchored projections (Approach A).
- Assumed (confirmed in design discussion): Sunday **main slate**, **Classic** format only; 1–3 lineups per week; entry is manual via CSV upload.

## 2. Scope

**In scope (v1):** DraftKings NFL Sunday main slate, Classic; the 7 DraftKings contest types in §8.1; one recommended lineup per contest type + outlier swaps; locks/excludes; DK upload CSV export; automated weekly pipeline on Nathan's Mac; hosted read-mostly copy on Streamlit Community Cloud; post-contest results import and report card; sidebar step-by-step import guide.

**Out of scope (v1):** Showdown / prime-time / other slates; 150-lineup multi-entry portfolio building; FanDuel or other sites; automated contest entry; any automated DraftKings login; NBA.

**Noted future enhancements:**
- **Option C:** blend Vegas-derived projections with Sleeper public projections as a sanity check.
- Paid salary feed (e.g. SportsDataIO) replacing the DK endpoint fetch — the salary loader is isolated so it can be swapped.
- Multi-lineup sets (5–20) once Nathan is entering more.

## 3. Hard constraints and non-negotiables

- **No DraftKings credentials anywhere in the project.** No login automation (DK Terms of Use prohibit it; account suspension risk). Results import is a user-initiated browser download.
- **No automated contest entry.** Output is a CSV the user uploads.
- **DK endpoint access is light-touch:** at most a handful of unauthenticated requests per scheduled run, from the user's home connection only (never from Streamlit Cloud). The CSV upload path must always work as a fallback.
- **Salary cap ($50,000) and roster rules are enforced inside the optimizer's constraints**, and re-validated before export. An invalid lineup must be impossible to export.
- **Secrets** follow the MLB pattern: `env.txt` locally (git-ignored, `env.txt.example` committed), Streamlit *Secrets* on Cloud, mirrored into `os.environ` at app import (`_load_cloud_secrets_into_env()`).
- **Fail loudly:** no step may silently produce empty or stale output. Every step records success/failure to a status file the app reads.

## 4. Architecture overview

```
 Mac (LaunchAgents, home IP)                         GitHub                Streamlit Cloud
 ┌───────────────────────────────────────────┐      ┌────────┐            ┌──────────────┐
 │ run_pipeline.py --stage ...               │      │ repo   │  redeploy  │ app.py       │
 │  01 DK salaries ─┐                        │ push │        │ ─────────▶ │ (read-mostly)│
 │  02 nflverse ────┼▶ 04 team env ▶ 05 shares│ ───▶ │ data/  │            └──────────────┘
 │  03 Vegas odds ──┘   ▶ 06 simulate        │      │published│
 │                      ▶ 07 ownership       │      └────────┘
 │                      ▶ 08 lineups (all types)                          Local app.py
 │                      ▶ 09 publish (commit+push)                       (full: refresh,
 │  10 results import (Downloads watcher)    │                            imports, uploads)
 └───────────────────────────────────────────┘
```

- **Local Mac is the engine** (same as MLB): all fetching, modeling, simulation and lineup building.
- **Published subset** (`data/published/`) is committed and pushed; Streamlit Cloud redeploys from GitHub.
- **Everything else under `data/`** is git-ignored and rebuilt locally.

## 5. Weekly schedule (automated)

All times US Eastern. Jobs are macOS LaunchAgents in `~/Library/LaunchAgents/`, shell wrappers in `scripts/`.

| When | Stage | What runs |
|---|---|---|
| Tue 9:00 AM | `tuesday` | Fetch DK main-slate salaries (once); refresh nflverse data through last week |
| Thu 9:00 AM | `thursday` | Re-attempt DK salary fetch if Tuesday's failed → Vegas lines → projections → simulations → ownership → lineups for every contest type → publish |
| Sun 9:00 AM | `sunday` | Re-fetch lines + DK player statuses → remove Out/Doubtful → rebuild → publish |
| Sun 11:45 AM | `sunday` | Same, after inactives are announced (~90 min before 1 PM kickoffs) |
| On new file in `~/Downloads` | `results` | Import any new `contest-standings-*.zip` (launchd `WatchPaths`) |

**Wake/power:** a one-time `sudo pmset repeat wakeorpoweron` setup wakes the Mac shortly before scheduled jobs; the Sunday 9:00 job holds the Mac awake (`caffeinate`) through the 11:45 run. The Mac must be plugged in. The one-time setup (and macOS's Downloads-folder permission for the Python binary used by launchd) is documented step-by-step in USER_MANUAL.md.

**Manual fallbacks (rare):** "Refresh" button in the local app; `DKSalaries.csv` upload if the salary fetch fails; results zip upload if the watcher misses a file.

## 6. Data sources

| Data | Source | Cost | Notes |
|---|---|---|---|
| Salaries, player IDs, positions, game info, injury status | DraftKings unofficial draft-group endpoints (lobby → main-slate draft group → draftables) | Free | Unofficial; shape verified at build time; CSV upload fallback |
| Salaries (fallback) | `DKSalaries.csv` from any DK contest page | Free | Official export |
| Play-by-play, weekly stats, rosters, snap counts | `nflverse` via `nflreadpy` | Free | Verify package status at build; `nfl_data_py` is the older alternative |
| Game totals, spreads | The Odds API (`ODDS_API_KEY`) | Free tier 500 req/mo | ~3 runs/week × few requests; well under quota |
| Actual ownership + contest results | DK contest standings export (user download) | Free | Imported via Downloads watcher |

## 7. Projection model (Approach A — Vegas-anchored)

### 7.1 Team environment (`04_build_team_environment.py`)
- Implied team total = `total/2 − spread/2` (spread from that team's perspective, negative = favored).
- Convert implied points → expected offensive TDs, passing yards, rushing yards, and pass/rush play split via league-wide relationships fit on recent nflverse seasons (e.g. regress team passing yards and TDs on implied total and spread, so favorites lean run late).

### 7.2 Player shares (`05_build_player_shares.py`)
- From the last 4–6 games (recency-weighted): target share, carry share, air-yards share, red-zone target/carry share, QB rush share, snap share.
- **Small-sample shrinkage** toward position/role priors, weighted by opportunities (the same credibility blend `(n·obs + k·prior)/(n + k)` used in MLB's pitcher fix).
- **Injury redistribution:** when a player is Out/Doubtful, his shares are reallocated to same-team, same-position-group players proportionally to their existing shares (rookie/depth players get a floor share).

### 7.3 Simulation (`06_simulate.py`)
- **10,000 simulations** of every main-slate game.
- Per simulation: draw a game-level scoring factor (shootout vs. slog) and team offensive factors; draw team TDs and yardage around the implied totals; allocate to players by drawing from each player's share distribution. This produces natural correlations (QB ↔ his receivers; both offenses in a shootout; DST ↔ opposing offense).
- Score each player with **DK Classic NFL scoring** (implemented once in `dk_rules.py`): full-PPR (+1/reception), 0.1 pt/rush-rec yard, 0.04 pt/pass yard, 6 pt rush/rec TD, 4 pt pass TD, −1 INT, −1 fumble lost, +2 two-point conversion, +3 bonuses for 300+ pass / 100+ rush / 100+ rec yards; DST tiers for points allowed plus sacks, takeaways, TDs, safeties, blocked kicks. Exact values verified against DK's published rules at build time.
- Outputs per player: **median, floor (p20), ceiling (p85), boom rate (P[score ≥ 3× salary/1000])**, plus the full simulation matrix for lineup evaluation.

### 7.4 Ownership estimate (`07_estimate_ownership.py`)
- Features: value (median pts per $1K), salary, position, implied team total, salary rank within position, recent big game flag, "cheap starter due to injury" flag.
- **Cold start:** historical DK ownership isn't freely available, so v1 starts with a hand-tuned heuristic formula (value-driven, normalized so each position's ownership sums to the realistic roster-slot total). Once **≥ 3 weeks** of imported results exist, it switches to a regression fit on Nathan's imported data, refit weekly.
- Tiers: 🔥 **Chalk** ≥ 25% · **Popular** 10–25% · **Moderate** 5–10% · 💎 **Contrarian** < 5%. All labeled "estimated" pre-lock.

## 8. Lineup construction (`08_build_lineups.py`, `optimizer.py`, `sim_eval.py`)

### 8.1 Optimizer
Integer linear program via **PuLP** (bundled CBC; `highspy` as fallback solver if CBC misbehaves on Python 3.14).

**Hard constraints:**
- Total salary ≤ **$50,000**; total salary ≥ configurable minimum (default **$49,000**).
- Roster: exactly 1 QB, 2 RB, 3 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 DST — 9 players, no duplicates.
- Only main-slate players; exclude Out/Doubtful; honor user locks/excludes.
- Tournament contest types only: QB + ≥1 same-team WR/TE (configurable to ≥2); ≥1 opposing-team skill player ("bring-back"); DST may not face any of the lineup's offensive players.

**Contest types** — the app's selector uses DraftKings' own contest-type names (exact lobby wording verified against Nathan's screenshots at build time). Each maps to an objective and a sim "success" test; all weights/thresholds live in `config.py`, tunable:

| DraftKings contest type | Group | Objective per player | Pick the candidate with the highest… |
|---|---|---|---|
| **Head-to-Head** | Cash | `0.5·floor + 0.5·median` | P(beat one random field lineup) |
| **50/50** | Cash | `0.5·floor + 0.5·median` | P(finish in top 50% of field) |
| **Double Up** | Cash | `0.5·floor + 0.5·median` | P(finish in top ~44% of field) |
| **Multiplier** (3x / 5x / 10x sub-choice) | Between | `0.5·median + 0.5·ceiling − 0.05·own%` | P(finish in top 1/3, 1/5 or 1/10) |
| **Single Entry / 3-Max Tournament** (small fields, ≤ ~1K) | Tournament | `ceiling − 0.05·own%` | P(finish in top 1%) |
| **Tournament** (~1K–20K entries) | Tournament | `ceiling − 0.15·own%` | P(finish in top 1%) |
| **Large-Field Tournament** (20K+, e.g. Millionaire Maker) | Tournament | `ceiling − 0.30·own%` | P(finish in top 1%) |

Stacking rules apply to the Tournament group (and optionally Multiplier, off by default).

### 8.2 Candidates → simulation pick
1. For each contest type, generate **~150 distinct candidates**: each solve perturbs projections with a random draw from the simulation matrix, plus a uniqueness constraint (each new lineup differs from all previous ones by ≥ 3 players).
2. Build a **simulated field** of ~2,000 opponent lineups by sampling players in proportion to estimated ownership under the same salary/roster rules.
3. Score every candidate and the field across all simulations (matrix multiply on the simulation matrix).
4. Pick per contest type using the "highest…" column in §8.1.
5. Store the pick, the runner-up candidates, and their sim stats.

### 8.3 Outlier swaps
For the chosen lineup in each contest type, list **5–8 single-player swaps** that keep the lineup valid and under the cap, ranked by that contest type's objective with emphasis on 💎/Moderate players with high boom rate. Each shows salary delta, remaining salary, ceiling/median delta, and ownership tier.

## 9. App (`app.py`) — single page + sidebar

**Header:** slate name + game count, "Updated N min ago" (color-coded like MLB), **DraftKings contest type** selector (the 7 names in §8.1, grouped Cash / Multiplier / Tournament; a 3x/5x/10x sub-choice appears for Multiplier), Refresh button (local only). A **red banner** appears only when a pipeline step failed, naming the step and the fix.

**Recommended lineup panel:** position, player, team, salary, median, floor, ceiling, ownership % + tier; total salary / $50,000; stack summary; one-sentence "why this lineup"; sim result in that contest's terms ("Wins the head-to-head in X% of sims" / "Cashes in X% of sims" / "Top-1% in X% of sims"); **Download DraftKings upload CSV**.

**Outliers panel:** swap rows with **Apply swap**; applying re-validates and re-scores against the simulation matrix in seconds. Session keeps the user's variations; one CSV exports all of them.

**Player pool (expander):** every player, sortable/filterable by position, tier, value; 🔒 lock / ✖ exclude, then **Rebuild with my locks**.

**My Lineup builder (added 2026-10-12):** a separate panel next to the recommended lineup.
- Nine empty slots (QB, RB, RB, WR, WR, WR, TE, FLEX, DST). Each slot picks from **every playable player on the slate** eligible for that slot, searchable, showing salary, median/floor/ceiling and ownership tier.
- **Start from:** blank, or a copy of any contest type's recommended lineup or alternates, then change any slot freely.
- Live totals: salary used / remaining against $50,000 (over-cap shown in red, and export disabled), projected median/floor/ceiling, and the selected contest type's simulated result for this lineup ("Cashes in X% of sims" / "Top-1% in X% of sims"), scored against the published simulations so it is comparable to the recommended lineup.
- Side-by-side comparison table: recommended lineup vs. My Lineup.
- Save several custom lineups in the session and download any or all of them in the DraftKings upload CSV (validated by `dk_rules` first; an invalid lineup can't be exported). Works on the hosted app too (not persisted between visits).

**Report card (expander):** last week's projections vs. actual points and estimated vs. actual ownership; season-to-date accuracy.

**Pre-lock warning:** if a lineup player's DK status changed to Out/Doubtful after the last refresh → "⚠ Re-run Refresh".

**Sidebar:**
- **📥 How to import last week's results** — numbered, one action per step, plain language, no assumed technical knowledge: where to go on DraftKings (desktop website), exactly what to click, what the downloaded file is named, where it lands (Downloads), that no moving/renaming is needed, how to confirm import succeeded ("✅ Week N results imported"), and the drag-and-drop fallback. **The DK click-path wording is finalized from Nathan's screenshots of each DK screen during the build** — Claude cannot log in to verify it.
- **Check for results** button; **Upload results** (fallback); **Upload DKSalaries.csv** (fallback).
- Odds API quota remaining; model accuracy stats.

**Hosted vs. local** (same rule as MLB): hosted app shows everything, allows contest-type switches, swaps, locks and CSV download (not persisted). Refresh, imports and uploads work only locally; hosted app shows a banner explaining this with an "Open local app" link.

## 10. Repository layout

```
NFL_DFS/
  app.py                      Streamlit app
  run_pipeline.py             --stage tuesday|thursday|sunday|results  [--refresh]
  config.py                   contest-type weights, thresholds, sim counts, tier cutoffs
  launch.sh                   run sunday-stage refresh → restart Streamlit → open browser
  src/
    01_fetch_dk_salaries.py   DK endpoint fetch (+ CSV loader)
    02_fetch_nfl_stats.py     nflverse pulls
    03_fetch_vegas.py         The Odds API
    04_build_team_environment.py
    05_build_player_shares.py
    06_simulate.py
    07_estimate_ownership.py
    08_build_lineups.py
    09_publish.py             commit + push data/published/
    10_import_results.py      contest-standings zip → actuals, ownership history
    dk_rules.py               roster rules, cap, scoring, DK CSV formats (single source of truth)
    optimizer.py              PuLP model
    sim_eval.py               candidate vs. field evaluation
    status.py                 per-step status + atomic writes
  scripts/                    LaunchAgent shell wrappers + plist templates
  tests/
  data/                       git-ignored except data/published/
    published/                player_pool.parquet, lineups.parquet, swaps.parquet,
                              sims.npy (float16, 5,000 sims for hosted re-scoring),
                              run_status.json, report_card.parquet
  env.txt.example
  requirements.txt
  README.md, USER_MANUAL.md, claude-context.txt, claude-prompts.txt
  .devcontainer/              same as MLB, for Codespaces
```

Python: system Python 3.14 at the full path (same convention as MLB). Key deps: pandas, numpy, pyarrow, requests, python-dotenv, pulp, nflreadpy, scikit-learn, streamlit, pytest.

**GitHub:** new repo under `natergater24` (visibility to match `mlb-first-inning-model`), deployed as a new Streamlit Community Cloud app with `ODDS_API_KEY` in Secrets.

## 11. Error handling

- Every pipeline step writes `{step, started, finished, ok, message}` to `run_status.json` and prints full stdout/stderr to `logs/pipeline.log` (MLB lesson: never swallow subprocess output).
- All published files written atomically (`.tmp` then `os.replace`).
- A failed upstream step stops downstream steps for that run; the **previous published lineups stay visible** with their timestamp and the red banner explains the failure.
- DK salary fetch failure → banner directs to `DKSalaries.csv` upload. Odds failure or quota exhausted → banner; projections fall back to last fetched lines if < 48h old, otherwise stop.
- Missing optional files degrade with a visible message, never a crash.
- `09_publish.py` git failures (offline/auth) are logged and shown but never block local use.

## 12. Testing and validation

- **pytest unit tests:** salary cap and roster validity (including impossible-to-exceed cap), DK scoring function against hand-computed stat lines, DK upload CSV format, implied-total math, shrinkage function, ownership normalization, injury redistribution.
- **Backtest:** 2024–2025 seasons from nflverse to measure projection accuracy (median error, calibration of floor/ceiling percentiles). Historical DK salaries via RotoGuru (`nfldfs`) will be checked for availability; if unavailable, the backtest covers projections only, not lineups.
- **Live dry run:** one full run on the current week's real slate, reviewed with Nathan before relying on it.
- **Weekly report card** is the ongoing validation.

## 13. Known limitations and risks

- DK's unofficial endpoints can change or block without notice → CSV fallback.
- Ownership is estimated pre-lock; v1 uses a heuristic until ~3 weeks of imported results exist.
- Free injury data is slower than paid news; the Sunday 11:45 run plus the pre-lock warning mitigate but don't eliminate this.
- Scheduled runs require the Mac to be plugged in and able to wake.
- DFS carries a rake (~10–15%) and stronger competition; the tool improves process, not guaranteed outcomes.
- Committing `sims.npy` weekly grows repo history (~3 MB/week); acceptable for a season, can be pruned.

## 14. Items to verify during build (not design decisions)

1. DK lobby/draft-group/draftables endpoint shapes and main-slate identification.
2. DK lobby contest-type names (for the selector) and the contest-standings export click-path (via Nathan's screenshots) and zip contents/format.
3. DK bulk-upload CSV template header format.
4. DK scoring values against DK's current published NFL rules.
5. `nflreadpy` availability on Python 3.14 (fallback `nfl_data_py`).
6. PuLP/CBC on Python 3.14 macOS (fallback `highspy`).
7. RotoGuru historical salary availability for backtest.
