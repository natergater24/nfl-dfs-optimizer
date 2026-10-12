# NFL DFS App + Automation (Plan 2 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Plan 1 engine into the weekly product Nathan uses: matchup ratings, results import + report card + learned ownership, a Streamlit app (Recommended / interactive My Lineup builder / Player pool + locks), automatic weekly runs on his Mac, publishing to GitHub, and a hosted copy on Streamlit Community Cloud he can open on his phone.

**Architecture:** The Mac stays the engine (mirrors `MLB_Pipeline`): LaunchAgents run `run_pipeline.py` stages; each build writes `data/published/` (+ `data/history/`), and a new `publish` step commits and pushes only those paths so Streamlit Cloud redeploys. The app (`app.py` + small `nfldfs_app/` modules) reads only published files; local-only actions (Refresh, results import, uploads) shell out to `run_pipeline.py` and are disabled on the hosted copy. The My Lineup builder is a Streamlit components v2 custom component (inline HTML/CSS/JS) proven in the approved prototype.

**Tech Stack:** Python 3.14 (system install via `./py`), Streamlit ≥ 1.58 (components v2, `st.testing.v1.AppTest`), pandas 3, numpy 2, PuLP 4 + HiGHS, nflreadpy, macOS launchd + pmset, git + GitHub + Streamlit Community Cloud.

**Spec:** `docs/superpowers/specs/2026-10-11-nfl-dfs-optimizer-design.md` (§5 schedule, §9 app — revised 2026-10-12 from the approved prototype, §10 layout, §11 errors). Plan 1 (`docs/superpowers/plans/2026-10-12-nfl-dfs-engine.md`) is done and merged; its modules are the base this plan extends.

## Global Constraints

- Python: always `./py` (system Python 3.14). Never bare `python3`. App/hosted code must also run on Streamlit Cloud's Python (3.12+): no 3.13+-only syntax or stdlib APIs.
- Salary cap **$50,000**; roster `QB, RB, RB, WR, WR, WR, TE, FLEX, DST`; an invalid lineup must be impossible to export (`dk_rules.validate_lineup` gates every CSV).
- **No DraftKings credentials anywhere.** No login automation, no contest entry. Results come from a file Nathan downloads himself.
- **Privacy:** DraftKings standings files contain other users' usernames. They stay local (`data/raw/standings/`, git-ignored). Only per-player aggregates (actual ownership %, actual points) go into `data/history/` and get published. No `EntryName` value may ever reach `data/published/` or `data/history/`.
- Secrets: `env.txt` (git-ignored) only; never printed, logged or committed. The hosted app needs no secrets.
- Display: salaries as full dollars (`$7,500`, never `$7.5K`); ownership tiers 🔥 Chalk ≥25% / Popular 10–25% / Moderate 5–10% / 💎 Contrarian <5%; every player shows a matchup tag colored on a red → green gradient (labels Very tough / Tough / Neutral / Good / Great).
- Simulated percentages are labeled model-relative ("for comparing lineups, not real-world odds").
- Loud failures: every pipeline step records ok/failed + plain-language message; publishing failures never block local use but are recorded as `WARNING:` messages.
- Atomic writes for every file the app reads (`nfldfs.status.atomic_*`).
- Local app port **8502** (the MLB app uses 8501). Project path: `/Users/nathantessler/Desktop/Nathan/Claude/NFL_DFS` (no spaces).
- Anything that changes Nathan's machine or accounts outside this repo — installing LaunchAgents, `sudo pmset`, creating the GitHub repo, the first push, Streamlit Cloud setup, writing to `~/Desktop` — is a **Nathan-approval step**: the controller asks Nathan in chat and waits for a yes (or Nathan does it himself following the plan's exact clicks).
- Commit messages end with a `Co-Authored-By:` trailer naming the model that wrote the commit.

## Review Focus

1. **A results file imported late** (e.g. Nathan downloads Monday's standings but the import only runs after the next slate is built) must still match the slate it belongs to → Task 3 `test_latest_snapshot_uses_file_date` and Task 5 `test_step_results_matches_by_download_date`.
2. **Opening the app before any build exists** (fresh clone, hosted app before first publish) must show a friendly "no lineups yet" message, not a stack trace → Task 6 `test_app_without_published_files`.
3. **The hosted copy** (no `caffeinate`) must not offer Refresh / Check for results / uploads as working buttons → Task 10 `test_sidebar_actions_disabled_when_hosted` and Task 6 smoke test.
4. **A custom lineup containing a player later ruled OUT** (Sunday refresh after Nathan built it) must warn and block export → Task 8 `test_lineup_status_flags_out_player`.
5. **Publishing offline / without a remote / with a rejected push** must never fail the run or the app and must say what happened → Task 5 `test_publish_*`.

---

## File Structure

```
NFL_DFS/
  app.py                         Streamlit entry point (Task 6)
  launch.sh                      start the local app on :8502 and open Chrome (Task 11)
  run_pipeline.py                + stages sunday_late/refresh/results, publish, vegas reuse/fallback (Task 5)
  requirements.txt               + streamlit>=1.58 (Task 6)
  .devcontainer/devcontainer.json  (Task 12)
  USER_MANUAL.md                 (Task 13)
  nfldfs/
    matchups.py                  defense-vs-position ratings, colors, labels (Task 1)
    lineups.py                   swaps spread across positions; build_all returns field; best_lineup() (Task 2)
    results.py                   standings import, history, report card (Task 3)
    ownership.py                 + ownership_features, fit_ownership_model, model-aware estimate (Task 4)
    publish.py                   commit + push published paths (Task 5)
    build.py                     + matchups, ownership model, field, write_published() (Tasks 1, 2, 4, 5)
    dk_rules.py                  + upload_csv_text() (Task 6)
    config.py                    + new constants/paths (Tasks 2, 5)
  nfldfs_app/
    __init__.py
    data.py                      load published files, hosted detection, freshness (Task 6)
    ui.py                        formatting, Key text, styled tables, report card widget (Tasks 6, 7)
    actions.py                   run pipeline stages from the app, save uploads (Task 6)
    view_recommended.py          ⭐ Recommended tab (Task 7)
    builder_component.py         My Lineup custom component (HTML/CSS/JS) (Task 8)
    view_builder.py              🛠 My Lineup tab glue (Task 8)
    view_pool.py                 📋 Player pool + locks/rebuild (Task 9)
    view_sidebar.py              sidebar: status, import guide, local actions (Task 10)
  scripts/
    run_stage.sh                 LaunchAgent wrapper (Task 11)
    install_schedule.sh / uninstall_schedule.sh  (Task 11)
    make_desktop_launcher.sh     (Task 11)
    launchagents/*.plist.template  tuesday, thursday, sunday, sunday_late, results (Task 11)
  data/
    published/                   committed: lineups, pool, swaps, sims.npy, field.npy, meta, status, report card
    history/results.parquet      committed: per-player actual ownership/points (no usernames)
    processed/slates/            local: archived slate snapshots for results matching
    raw/standings/               local: imported DraftKings standings zips (contain usernames)
```

---

### Task 1: Matchup ratings in the engine

**Files:**
- Create: `nfldfs/matchups.py`, `tests/test_matchups.py`
- Modify: `nfldfs/build.py` (`build_slate` gains `schedule_rows=None`), `run_pipeline.py` (`step_stats` writes `schedule_rows.parquet`; `step_stats_if_missing` requires it; `step_build` passes it), `tests/test_run_pipeline.py` (fixtures that fake the stats files must also create `schedule_rows.parquet`), `tests/test_build.py`

**Interfaces:**
- Consumes: `player_weeks` (columns incl. `season, week, team, position, dk_pts`), `nfl_stats.normalize_schedules()` output (`season, week, team, opp, ...`), pool columns `opp, position, implied_total, opp_implied`.
- Produces: `matchups.MATCHUP_COLUMNS = ["mu_ratio", "mu_label", "mu_color", "mu_text"]`; `defense_vs_position(player_weeks, schedule_rows, n_games=6) -> DataFrame[defense, position, allowed, ratio, rank]`; `matchup_color(ratio) -> "#rrggbb"`; `matchup_label(ratio) -> str`; `attach_matchups(pool, dvp) -> pool + MATCHUP_COLUMNS` (RangeIndex, same row order). `build_slate(..., schedule_rows=None)` returns a pool with `MATCHUP_COLUMNS` (neutral when `schedule_rows` is None). New processed file `data/processed/schedule_rows.parquet`.

- [ ] **Step 1: Write the failing tests** — `tests/test_matchups.py`:

```python
import pandas as pd
import pytest

from nfldfs import matchups


def _weeks():
    """Two offenses: AAA always faces soft defense XXX (30 WR pts), BBB faces tough YYY (10 WR pts)."""
    rows, sched = [], []
    for wk in range(1, 7):
        for off, dfn, pts in (("AAA", "XXX", 30.0), ("BBB", "YYY", 10.0)):
            rows.append(dict(season=2026, week=wk, team=off, position="WR", dk_pts=pts))
            sched += [dict(season=2026, week=wk, team=off, opp=dfn), dict(season=2026, week=wk, team=dfn, opp=off)]
    return pd.DataFrame(rows), pd.DataFrame(sched)


def test_defense_vs_position_ratio_and_rank():
    pw, s = _weeks()
    d = matchups.defense_vs_position(pw, s).set_index("defense")
    assert d.loc["XXX", "allowed"] == 30 and d.loc["YYY", "allowed"] == 10
    assert d.loc["XXX", "ratio"] == pytest.approx(1.5) and d.loc["YYY", "ratio"] == pytest.approx(0.5)
    assert d.loc["XXX", "rank"] == 1 and d.loc["YYY", "rank"] == 2


def test_only_last_n_games_count():
    pw, s = _weeks()
    pw.loc[(pw.team == "AAA") & (pw.week == 1), "dk_pts"] = 1000.0
    d = matchups.defense_vs_position(pw, s, n_games=5).set_index("defense")
    assert d.loc["XXX", "allowed"] == 30


def test_color_gradient_and_labels():
    red, green = matchups.matchup_color(0.5), matchups.matchup_color(1.5)
    assert len(red) == 7 and red.startswith("#")
    assert int(red[1:3], 16) > int(red[3:5], 16)          # red channel dominates
    assert int(green[3:5], 16) > int(green[1:3], 16)      # green channel dominates
    assert [matchups.matchup_label(x) for x in (1.2, 1.05, 1.0, 0.9, 0.7)] == \
        ["Great", "Good", "Neutral", "Tough", "Very tough"]


def test_attach_matchups_offense_dst_and_missing():
    pw, s = _weeks()
    d = matchups.defense_vs_position(pw, s)
    pool = pd.DataFrame([
        dict(name="W1", position="WR", team="AAA", opp="XXX", implied_total=24.0, opp_implied=20.0),
        dict(name="W2", position="WR", team="BBB", opp="YYY", implied_total=20.0, opp_implied=24.0),
        dict(name="T1", position="TE", team="BBB", opp="YYY", implied_total=20.0, opp_implied=24.0),
        dict(name="D1", position="DST", team="XXX", opp="AAA", implied_total=20.0, opp_implied=24.0),
        dict(name="D2", position="DST", team="YYY", opp="BBB", implied_total=24.0, opp_implied=18.0)])
    out = matchups.attach_matchups(pool, d)
    assert list(out["name"]) == ["W1", "W2", "T1", "D1", "D2"]               # row order preserved
    out = out.set_index("name")
    assert out.loc["W1", "mu_label"] == "Great" and out.loc["W2", "mu_label"] == "Very tough"
    assert "1st-easiest of 2" in out.loc["W1", "mu_text"]
    assert out.loc["T1", "mu_ratio"] == 1.0 and out.loc["T1", "mu_label"] == "Neutral"
    assert "not enough games" in out.loc["T1", "mu_text"]
    offense_avg = (24 + 20 + 20) / 3
    assert out.loc["D2", "mu_ratio"] == pytest.approx(offense_avg / 18, rel=1e-3)
    assert out.loc["D2", "mu_ratio"] > out.loc["D1", "mu_ratio"]
    assert "Vegas total is 18.0" in out.loc["D2", "mu_text"]


def test_attach_matchups_with_no_ratings_is_neutral():
    empty = pd.DataFrame(columns=["defense", "position", "allowed", "ratio", "rank"])
    pool = pd.DataFrame([dict(name="W1", position="WR", team="AAA", opp="XXX", implied_total=24.0, opp_implied=20.0)])
    out = matchups.attach_matchups(pool, empty)
    assert out.loc[0, "mu_label"] == "Neutral" and out.loc[0, "mu_ratio"] == 1.0
```

Append to `tests/test_build.py`:

```python
def test_build_slate_adds_matchup_columns():
    pool_base, pw, tw, games = _inputs()
    res = build.build_slate(pool_base, pw, tw, MODEL, games, n_sims=200, seed=1, n_candidates=2, field_size=100)
    from nfldfs.matchups import MATCHUP_COLUMNS
    assert set(MATCHUP_COLUMNS) <= set(res["pool"].columns)
    assert (res["pool"].mu_label == "Neutral").all()       # no schedule_rows given → neutral
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_matchups.py tests/test_build.py -v`
Expected: ImportError for `nfldfs.matchups`; the new build test fails on missing columns.

- [ ] **Step 3: Implement `nfldfs/matchups.py`**

```python
"""Matchup ratings: DraftKings points each defense allowed to each position (display-only in v1)."""
from __future__ import annotations

import colorsys

import numpy as np
import pandas as pd

N_GAMES = 6
RATIO_LO, RATIO_HI = 0.70, 1.30          # ratios beyond these get the full red / green
LABEL_CUTOFFS = ((1.12, "Great"), (1.03, "Good"), (0.97, "Neutral"), (0.88, "Tough"))
WORST_LABEL = "Very tough"
MATCHUP_COLUMNS = ["mu_ratio", "mu_label", "mu_color", "mu_text"]


def defense_vs_position(player_weeks: pd.DataFrame, schedule_rows: pd.DataFrame,
                        n_games: int = N_GAMES) -> pd.DataFrame:
    sched = schedule_rows[["season", "week", "team", "opp"]].drop_duplicates()
    pw = player_weeks.merge(sched, on=["season", "week", "team"], how="inner")
    g = pw.groupby(["opp", "season", "week", "position"], as_index=False)["dk_pts"].sum()
    g = g.sort_values(["season", "week"], kind="stable")
    g["age"] = g.groupby(["opp", "position"]).cumcount(ascending=False)
    g = g[g.age < n_games].groupby(["opp", "position"], as_index=False)["dk_pts"].mean()
    g["ratio"] = g["dk_pts"] / g.groupby("position")["dk_pts"].transform("mean")
    g["rank"] = g.groupby("position")["dk_pts"].rank(ascending=False, method="min").astype(int)
    g = g.rename(columns={"opp": "defense", "dk_pts": "allowed"})
    return g[["defense", "position", "allowed", "ratio", "rank"]]


def matchup_color(ratio: float) -> str:
    """Red (tough) → amber → green (soft)."""
    t = float(np.clip((ratio - RATIO_LO) / (RATIO_HI - RATIO_LO), 0.0, 1.0))
    r, g, b = colorsys.hls_to_rgb(t * 130 / 360, 0.38, 0.62)
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def matchup_label(ratio: float) -> str:
    for cutoff, label in LABEL_CUTOFFS:
        if ratio >= cutoff:
            return label
    return WORST_LABEL


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def attach_matchups(pool: pd.DataFrame, dvp: pd.DataFrame) -> pd.DataFrame:
    p = pool.drop(columns=[c for c in MATCHUP_COLUMNS if c in pool.columns]).reset_index(drop=True)
    m = p[["opp", "position"]].merge(dvp, left_on=["opp", "position"], right_on=["defense", "position"],
                                      how="left")
    ratio = m["ratio"].to_numpy(dtype=float)
    rank = m["rank"].to_numpy(dtype=float)
    allowed = m["allowed"].to_numpy(dtype=float)
    n_def = int(dvp["defense"].nunique()) or 32
    dst = (p["position"] == "DST").to_numpy()
    if dst.any():
        base = p.loc[~dst, "implied_total"] if (~dst).any() else p.loc[dst, "opp_implied"]
        ratio[dst] = float(base.mean()) / p.loc[dst, "opp_implied"].to_numpy(dtype=float)
    ratio = np.where(np.isnan(ratio), 1.0, ratio)
    texts = []
    for i, r in enumerate(p.itertuples(index=False)):
        if dst[i]:
            texts.append(f"vs {r.opp}: opponent's Vegas total is {r.opp_implied:.1f} pts")
        elif np.isnan(allowed[i]):
            texts.append(f"vs {r.opp}: not enough games to rate this matchup")
        else:
            texts.append(f"vs {r.opp}: allows {allowed[i]:.1f} DK pts/game to {r.position}s — "
                         f"{_ordinal(int(rank[i]))}-easiest of {n_def}")
    p["mu_ratio"] = ratio.round(3)
    p["mu_label"] = [matchup_label(x) for x in ratio]
    p["mu_color"] = [matchup_color(x) for x in ratio]
    p["mu_text"] = texts
    return p
```

- [ ] **Step 4: Wire matchups into the build and the stats step**

In `nfldfs/build.py`: add `from . import matchups` to the imports, add the keyword parameter `schedule_rows=None` to `build_slate`, and directly after the two ownership lines (`pool["own_pct"] = ...` / `pool["tier"] = ...`) insert:

```python
    dvp = (matchups.defense_vs_position(player_weeks, schedule_rows) if schedule_rows is not None
           else pd.DataFrame(columns=["defense", "position", "allowed", "ratio", "rank"]))
    pool = matchups.attach_matchups(pool, dvp)
```

In `run_pipeline.py`:
- `step_stats`: after `pw`/`tw` are built, compute `sched_rows = nfl_stats.normalize_schedules(sched)`, use it for `build_training_frame(tw, sched_rows)`, and write `atomic_write_parquet(sched_rows, config.PROCESSED / "schedule_rows.parquet")`.
- `step_stats_if_missing`: add `"schedule_rows.parquet"` to the `needed` list.
- `step_build`: read `schedule_rows.parquet` when it exists (`None` otherwise) and pass `schedule_rows=...` to `build.build_slate`.
- Update any test in `tests/test_run_pipeline.py` that fakes the stats files so it also creates `schedule_rows.parquet`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_matchups.py tests/test_build.py tests/test_run_pipeline.py -v && ./py -m pytest -q -W error`
Expected: all pass, no warnings.

- [ ] **Step 6: Live check (offline, no API quota)** — the real slate's inputs are on disk:

```bash
./py -c "
import pandas as pd, nfldfs.nfl_stats as n, nflreadpy as nfl
sched = n.normalize_schedules(nfl.load_schedules([2025, 2026]).to_pandas())
from nfldfs.status import atomic_write_parquet; from nfldfs import config
atomic_write_parquet(sched, config.PROCESSED / 'schedule_rows.parquet'); print(len(sched))
" && ./py run_pipeline.py --stage build && ./py -c "
import pandas as pd; p = pd.read_parquet('data/published/player_pool.parquet')
print(p[p.playable].sort_values('salary', ascending=False).groupby('position').head(2)[['name','position','opp','mu_label','mu_text']].to_string())"
```
Expected: build exits 0; labels vary across players (not all Neutral); texts read like "vs LV: allows 19.7 DK pts/game to QBs — 8th-easiest of 32".

- [ ] **Step 7: Commit**

```bash
git add nfldfs/matchups.py nfldfs/build.py run_pipeline.py tests/test_matchups.py tests/test_build.py tests/test_run_pipeline.py
git commit -m "Add defense-vs-position matchup ratings to the build" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: Swaps across positions, published field, `best_lineup()`

**Files:**
- Modify: `nfldfs/config.py`, `nfldfs/lineups.py`, `nfldfs/build.py`, `run_pipeline.py` (`step_build` saves `field.npy`), `tests/test_lineups.py`, `tests/test_build.py`

**Interfaces:**
- Produces: `config.MAX_SWAPS_PER_POSITION = 2`, `config.REBUILD_CANDIDATES = 30`; `lineups.build_all(...) -> (lineups_df, swaps_df, field: np.ndarray[int] (field_size, 9))` (**now 3 values**); `build_slate()` result gains `"field"`; `lineups.best_lineup(pool, sims, field, contest, *, locks=(), excludes=(), n_candidates=REBUILD_CANDIDATES, seed=SEED, min_salary=MIN_SALARY_DEFAULT) -> tuple[list[int] (row positions), float]` (raises `optimizer.InfeasibleError` if no lineup fits); new published file `data/published/field.npy` (int16).

- [ ] **Step 1: Write the failing tests** — in `tests/test_lineups.py` change every `lus, swaps = lineups.build_all(...)` to `lus, swaps, field = lineups.build_all(...)` and append:

```python
def test_build_all_returns_field(projected):
    p, sims = projected
    _, _, field = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert field.shape == (150, 9)


def test_swaps_spread_across_positions(projected):
    p, sims = projected
    _, swaps, _ = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert swaps.groupby(["contest_key", "position"]).size().max() <= config.MAX_SWAPS_PER_POSITION


def test_best_lineup_respects_locks_and_excludes(projected):
    from nfldfs.sim_eval import sample_field
    p, sims = projected
    field = sample_field(p, 100, np.random.default_rng(0))
    lock = int(p.loc[p["name"] == "CCC TE3", "dk_id"].iloc[0])
    excl = int(p.loc[p["name"] == "AAA WR1", "dk_id"].iloc[0])
    rows, metric = lineups.best_lineup(p, sims, field, config.CONTEST_TYPES["tournament"],
                                       locks=[lock], excludes=[excl], n_candidates=4)
    lu = p.loc[rows]
    assert dk_rules.validate_lineup(lu) == [] and 0.0 <= metric <= 1.0
    assert lock in lu.dk_id.tolist() and excl not in lu.dk_id.tolist()
```

In `tests/test_build.py` `test_build_slate_end_to_end`, add `assert res["field"].shape == (150, 9)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_lineups.py tests/test_build.py -v`
Expected: FAIL (unpacking 2 values into 3; `best_lineup`/config constants missing).

- [ ] **Step 3: Implement**

`nfldfs/config.py` — add next to `N_SWAPS`:

```python
MAX_SWAPS_PER_POSITION = 2         # outlier list is spread across positions
REBUILD_CANDIDATES = 30            # candidates per "Rebuild with my locks" in the app
```

`nfldfs/lineups.py`:
- import `MAX_SWAPS_PER_POSITION, REBUILD_CANDIDATES` from `.config`.
- end of `find_swaps`, replace the final two statements with:

```python
    df = pd.DataFrame(rows).sort_values("metric_delta", ascending=False, kind="stable")
    df = df.drop_duplicates("in_dk_id").groupby("position", sort=False).head(MAX_SWAPS_PER_POSITION)
    return df.head(n).reset_index(drop=True)[SWAP_COLUMNS]
```

- `build_all`: return type `tuple[pd.DataFrame, pd.DataFrame, np.ndarray]`; final statement returns `(..., pd.concat(swap_frames, ignore_index=True), field)`.
- add:

```python
def best_lineup(pool: pd.DataFrame, sims: np.ndarray, field: np.ndarray, contest: dict, *, locks=(),
                excludes=(), n_candidates: int = REBUILD_CANDIDATES, seed: int = SEED,
                min_salary: int = MIN_SALARY_DEFAULT) -> tuple[list[int], float]:
    """Best lineup for one contest type under the user's locks/excludes (used by the app)."""
    rng = np.random.default_rng(seed)
    cands = generate_candidates(pool, sims, contest, n_candidates, rng, min_salary=min_salary,
                                locks=locks, excludes=excludes)
    metric = contest_metric(lineup_scores(sims, cands), lineup_scores(sims, field), contest["metric"])
    i = int(np.argmax(metric))
    return cands[i], float(metric[i])
```

`nfldfs/build.py`: `lus, swaps, field = lineups.build_all(...)`; add `"field": field` to the returned dict.

`run_pipeline.py` `step_build`: after saving `sims.npy`, add `atomic_save_npy(res["field"].astype(np.int16), out / "field.npy")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_lineups.py tests/test_build.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nfldfs/config.py nfldfs/lineups.py nfldfs/build.py run_pipeline.py tests/test_lineups.py tests/test_build.py
git commit -m "Spread outlier swaps across positions; publish the simulated field; add best_lineup()" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Results import, history and report card (module)

**Files:**
- Create: `nfldfs/results.py`, `tests/test_results.py`

**Interfaces:**
- Consumes: `teams.normalize_name`, `status.atomic_write_parquet`; slate snapshots written by Task 5 as `data/processed/slates/{YYYY-MM-DD}_{draft_group_id|upload}.parquet` (the built pool: `dk_id, name, position, team, salary, median, floor, ceiling, own_pct, implied_total, opp_implied, playable, ...`).
- Produces: `STANDINGS_GLOB`, `HISTORY_COLUMNS`; `find_new_standings(downloads, done_dir) -> list[Path]` (raises `PermissionError` if the folder can't be read — never silently empty); `read_standings(path) -> DataFrame[name, roster_position, actual_own, actual_pts]` (zip or csv); `snapshot_key(path) -> tuple[str date, str draft_group]`; `latest_slate_snapshot(slates_dir, as_of: date) -> Path | None`; `match_to_slate(standings, snapshot, slate_date, draft_group_id) -> DataFrame[HISTORY_COLUMNS]` (every playable slate player; undrafted players get `actual_own = 0.0`, `actual_pts = NaN`); `append_history(history_path, rows) -> DataFrame`; `report_card(history) -> dict`.

DraftKings' contest-standings export (one CSV inside a zip named `contest-standings-<contestId>.zip`) has entry columns `Rank, EntryId, EntryName, TimeRemaining, Points, Lineup`, a blank column, then a per-player block `Player, Roster Position, %Drafted, FPTS` (one row per drafted player; `%Drafted` like `40.52%`). Only the per-player block is read; `EntryName` is never copied anywhere. (Format re-checked against Nathan's first real file in Task 13.)

- [ ] **Step 1: Write the failing tests** — `tests/test_results.py`:

```python
import datetime as dt
import os
import zipfile

import numpy as np
import pandas as pd
import pytest

from nfldfs import results

CSV = ("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
       "1,111,secretuser (1/3),0,150.5,QB AAA QB1 ...,,AAA QB1,QB,40.00%,25.1\n"
       "2,112,otheruser,0,140.1,QB BBB QB1 ...,,AAA WR1,WR,12.50%,18.3\n"
       ",,,,,,,BBB DST1,DST,5.25%,7\n")


def _zip(path, csv=CSV):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-999.csv", csv)
    return path


def _snapshot():
    from tests.conftest import make_pool
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    p.loc[p["name"] == "AAA QB1", ["median", "own_pct"]] = [20.0, 30.0]
    p.loc[p["name"] == "AAA WR4", "playable"] = False
    p.loc[p["name"] == "BBB DST1", "name"] = "BBB DST1"
    return p


def test_read_standings_zip_and_privacy(tmp_path):
    s = results.read_standings(_zip(tmp_path / "contest-standings-999.zip"))
    assert list(s.columns) == ["name", "roster_position", "actual_own", "actual_pts"]
    assert s.set_index("name").loc["AAA QB1", "actual_own"] == 40.0
    assert s.set_index("name").loc["BBB DST1", "actual_pts"] == 7.0
    assert "secretuser" not in s.to_csv()


def test_read_standings_rejects_other_files(tmp_path):
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="contest standings"):
        results.read_standings(tmp_path / "x.csv")


def test_find_new_standings_skips_done(tmp_path):
    dl, done = tmp_path / "Downloads", tmp_path / "done"
    dl.mkdir(); done.mkdir()
    _zip(dl / "contest-standings-1.zip"); _zip(dl / "contest-standings-2.zip"); (dl / "other.zip").write_text("x")
    _zip(done / "contest-standings-1.zip")
    assert [p.name for p in results.find_new_standings(dl, done)] == ["contest-standings-2.zip"]


def test_find_new_standings_surfaces_permission_errors(tmp_path, monkeypatch):
    def deny(path):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(os, "listdir", deny)
    with pytest.raises(PermissionError):
        results.find_new_standings(tmp_path, tmp_path / "done")


def test_latest_snapshot_uses_file_date(tmp_path):
    for name in ("2026-10-11_100.parquet", "2026-10-18_154941.parquet", "2026-10-25_160000.parquet"):
        (tmp_path / name).write_bytes(b"")
    assert results.latest_slate_snapshot(tmp_path, dt.date(2026, 10, 19)).name == "2026-10-18_154941.parquet"
    assert results.latest_slate_snapshot(tmp_path, dt.date(2026, 10, 10)) is None
    assert results.snapshot_key(tmp_path / "2026-10-18_154941.parquet") == ("2026-10-18", "154941")


def test_match_to_slate_includes_undrafted_as_zero(tmp_path):
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    rows = results.match_to_slate(s, _snapshot(), "2026-10-18", "154941")
    assert list(rows.columns) == results.HISTORY_COLUMNS
    by = rows.set_index("name")
    assert by.loc["AAA QB1", "actual_own"] == 40.0 and by.loc["AAA QB1", "actual_pts"] == 25.1
    assert by.loc["AAA RB1", "actual_own"] == 0.0 and np.isnan(by.loc["AAA RB1", "actual_pts"])
    assert "AAA WR4" not in by.index                          # unplayable players are left out
    assert (rows.slate_date == "2026-10-18").all()


def test_append_history_dedups_and_report_card(tmp_path):
    s = results.read_standings(_zip(tmp_path / "c.zip"))
    rows = results.match_to_slate(s, _snapshot(), "2026-10-18", "154941")
    path = tmp_path / "history" / "results.parquet"
    results.append_history(path, rows)
    hist = results.append_history(path, rows)                 # same slate twice → no duplicates
    assert len(hist) == len(rows)
    card = results.report_card(hist)
    assert card["weeks"] == 1 and card["latest_slate"] == "2026-10-18"
    lat = card["latest"]
    assert lat["scored"] == 3
    # AAA QB1: |25.1-20|=5.1, AAA WR1: |18.3-10|=8.3, BBB DST1: |7-10|=3 → mean 5.47
    assert lat["proj_mae"] == pytest.approx(5.47, abs=0.01)
    assert 0 <= lat["in_range_pct"] <= 100 and lat["own_mae"] >= 0
    assert results.report_card(pd.DataFrame(columns=results.HISTORY_COLUMNS)) == {"weeks": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_results.py -v`
Expected: ImportError for `nfldfs.results`.

- [ ] **Step 3: Implement `nfldfs/results.py`**

```python
"""Import DraftKings contest-standings exports → actual ownership/points → history + report card.

Standings files contain other users' names; only the per-player block is read and nothing user-specific
is kept."""
from __future__ import annotations

import datetime as dt
import fnmatch
import io
import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .status import atomic_write_parquet
from .teams import normalize_name

STANDINGS_GLOB = "contest-standings-*.zip"
REQUIRED_COLUMNS = ("Player", "%Drafted", "FPTS")
HISTORY_COLUMNS = ["slate_date", "draft_group_id", "dk_id", "name", "position", "team", "salary", "median",
                   "floor", "ceiling", "own_pct", "implied_total", "opp_implied", "actual_own", "actual_pts"]
_SNAPSHOT = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\w+)\.parquet$")


def find_new_standings(downloads, done_dir) -> list[Path]:
    downloads, done_dir = Path(downloads), Path(done_dir)
    names = os.listdir(downloads)                     # raises PermissionError instead of looking empty
    done = set(os.listdir(done_dir)) if done_dir.exists() else set()
    found = [downloads / n for n in names if fnmatch.fnmatch(n, STANDINGS_GLOB) and n not in done]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def read_standings(path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"{path.name} has no CSV inside — is it a DraftKings contest standings export?")
            text = z.read(members[0]).decode("utf-8-sig")
    else:
        text = path.read_text(encoding="utf-8-sig")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"This doesn't look like a DraftKings contest standings export "
                         f"(missing columns: {missing})")
    df = df[df["Player"].str.strip() != ""]
    out = pd.DataFrame({
        "name": df["Player"].str.strip(),
        "roster_position": (df["Roster Position"].str.strip() if "Roster Position" in df.columns else ""),
        "actual_own": pd.to_numeric(df["%Drafted"].str.replace("%", "", regex=False), errors="coerce"),
        "actual_pts": pd.to_numeric(df["FPTS"], errors="coerce"),
    })
    return out.drop_duplicates("name").reset_index(drop=True)


def snapshot_key(path) -> tuple[str, str]:
    m = _SNAPSHOT.match(Path(path).name)
    if not m:
        raise ValueError(f"Not a slate snapshot file name: {Path(path).name}")
    return m.group(1), m.group(2)


def latest_slate_snapshot(slates_dir, as_of: dt.date) -> Path | None:
    best = None
    for p in Path(slates_dir).glob("*.parquet"):
        m = _SNAPSHOT.match(p.name)
        if m and dt.date.fromisoformat(m.group(1)) <= as_of and (best is None or m.group(1) > best[0]):
            best = (m.group(1), p)
    return best[1] if best else None


def match_to_slate(standings: pd.DataFrame, snapshot: pd.DataFrame, slate_date: str,
                   draft_group_id) -> pd.DataFrame:
    actual = standings.assign(k=standings["name"].map(normalize_name)).drop_duplicates("k").set_index("k")
    snap = snapshot[snapshot["playable"]].copy() if "playable" in snapshot.columns else snapshot.copy()
    k = snap["name"].map(normalize_name)
    snap["actual_own"] = k.map(actual["actual_own"]).fillna(0.0)
    snap["actual_pts"] = k.map(actual["actual_pts"])
    snap["slate_date"] = slate_date
    snap["draft_group_id"] = str(draft_group_id)
    return snap[HISTORY_COLUMNS].reset_index(drop=True)


def append_history(history_path, rows: pd.DataFrame) -> pd.DataFrame:
    history_path = Path(history_path)
    hist = pd.concat([pd.read_parquet(history_path), rows], ignore_index=True) if history_path.exists() \
        else rows.copy()
    hist = hist.drop_duplicates(["slate_date", "dk_id"], keep="last").reset_index(drop=True)
    atomic_write_parquet(hist, history_path)
    return hist


def _card(df: pd.DataFrame) -> dict:
    out = {"players": int(len(df))}
    pts = df.dropna(subset=["actual_pts"])
    out["scored"] = int(len(pts))
    if len(pts):
        err = pts["actual_pts"] - pts["median"]
        out["proj_mae"] = round(float(err.abs().mean()), 2)
        out["proj_bias"] = round(float(err.mean()), 2)
        inside = (pts["actual_pts"] >= pts["floor"]) & (pts["actual_pts"] <= pts["ceiling"])
        out["in_range_pct"] = round(float(inside.mean() * 100), 1)
    own = df.dropna(subset=["actual_own"])
    if len(own):
        out["own_mae"] = round(float((own["actual_own"] - own["own_pct"]).abs().mean()), 2)
        corr = float(own["actual_own"].corr(own["own_pct"])) if len(own) > 2 else float("nan")
        out["own_corr"] = None if np.isnan(corr) else round(corr, 3)
    return out


def report_card(history: pd.DataFrame) -> dict:
    if history.empty:
        return {"weeks": 0}
    latest = str(history["slate_date"].max())
    return {"weeks": int(history["slate_date"].nunique()), "latest_slate": latest,
            "latest": _card(history[history["slate_date"] == latest]), "season": _card(history)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_results.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nfldfs/results.py tests/test_results.py
git commit -m "Add DraftKings results import, history and report card" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: Ownership model learned from imported results

**Files:**
- Modify: `nfldfs/ownership.py`, `nfldfs/build.py` (`build_slate(..., ownership_model=None)`), `tests/test_ownership.py`

**Interfaces:**
- Consumes: history rows (`HISTORY_COLUMNS` from Task 3).
- Produces: `ownership.FEATURES = ("z_value", "z_median", "z_env")`, `MIN_MODEL_WEEKS = 3`, `MIN_ROWS_PER_POSITION = 25`; `ownership_features(pool) -> DataFrame[FEATURES]` (per-position z-scores among playable players; 0 for unplayable); `estimate_ownership(pool, model=None)` (model `None` → exactly today's heuristic); `fit_ownership_model(history) -> dict{"weeks", "rows", "coef": {position: [intercept, b_value, b_median, b_env]}} | None` (None until 3 slates with ≥ 25 rows for at least one position). `build_slate(..., ownership_model=None)` passes the model through.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ownership.py`:

```python
import numpy as np
import pandas as pd


def _history(weeks=3, n=30, seed=0):
    rng = np.random.default_rng(seed)
    parts = []
    for w in range(weeks):
        sal = rng.integers(30, 90, n) * 100
        med = rng.uniform(5, 20, n)
        h = pd.DataFrame({"slate_date": f"2026-10-{11 + 7 * w:02d}", "position": "WR", "salary": sal,
                          "median": med, "implied_total": rng.uniform(18, 28, n), "opp_implied": 22.0})
        value = med / (sal / 1000)
        h["actual_own"] = np.exp(1.5 * (value - value.mean()) / value.std()) * 5      # value drives ownership
        parts.append(h)
    return pd.concat(parts, ignore_index=True)


def test_estimate_without_model_matches_heuristic(pool):
    p = _projected(pool)
    assert ownership.estimate_ownership(p).equals(ownership.estimate_ownership(p, None))


def test_fit_needs_three_weeks():
    assert ownership.fit_ownership_model(_history(weeks=2)) is None


def test_fit_learns_value_effect_and_model_keeps_totals(pool):
    model = ownership.fit_ownership_model(_history())
    assert model["weeks"] == 3 and "WR" in model["coef"]
    b = model["coef"]["WR"]
    assert len(b) == 4 and b[1] > 1.0                          # strong positive z_value coefficient
    p = _projected(pool)
    own = ownership.estimate_ownership(p, model)
    sums = own.groupby(p.position).sum()
    for pos, total in ownership.SLOT_TOTALS.items():
        assert sums[pos] == pytest.approx(total, rel=1e-6)    # positions without a model use the heuristic


def test_ownership_features_zero_for_unplayable(pool):
    p = _projected(pool)
    p.loc[0, "playable"] = False
    f = ownership.ownership_features(p)
    assert list(f.columns) == list(ownership.FEATURES) and (f.loc[0] == 0).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_ownership.py -v`
Expected: FAIL (`fit_ownership_model`, `ownership_features`, `FEATURES` missing; `estimate_ownership` doesn't accept a model).

- [ ] **Step 3: Implement** — in `nfldfs/ownership.py` replace `estimate_ownership` with the following (keep `SLOT_TOTALS`, `MAX_OWN`, `TEMPERATURE`, `W_*`, `_z`, `_cap`, `ownership_tier` unchanged):

```python
FEATURES = ("z_value", "z_median", "z_env")
MIN_MODEL_WEEKS = 3
MIN_ROWS_PER_POSITION = 25


def ownership_features(pool: pd.DataFrame) -> pd.DataFrame:
    feats = pd.DataFrame(0.0, index=pool.index, columns=list(FEATURES))
    env = np.where(pool.position == "DST", -pool.opp_implied, pool.implied_total).astype(float)
    for pos in SLOT_TOTALS:
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        med = pool["median"].to_numpy(float)[m]
        value = med / (pool.salary.to_numpy(float)[m] / 1000)
        idx = pool.index[m]
        feats.loc[idx, "z_value"] = _z(value)
        feats.loc[idx, "z_median"] = _z(med)
        feats.loc[idx, "z_env"] = _z(env[m])
    return feats


def estimate_ownership(pool: pd.DataFrame, model: dict | None = None) -> pd.Series:
    own = pd.Series(0.0, index=pool.index)
    feats = ownership_features(pool)
    coefs = (model or {}).get("coef", {})
    for pos, total in SLOT_TOTALS.items():
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        X = feats.loc[pool.index[m], list(FEATURES)].to_numpy()
        if pos in coefs:
            b = np.asarray(coefs[pos], dtype=float)
            w = np.exp(np.clip(b[0] + X @ b[1:], -20, 20))
        else:
            w = np.exp((W_VALUE * X[:, 0] + W_MEDIAN * X[:, 1] + W_ENV * X[:, 2]) / TEMPERATURE)
        own[pool.index[m]] = _cap(w / w.sum() * total, MAX_OWN)
    return own


def fit_ownership_model(history: pd.DataFrame) -> dict | None:
    """Per-position log-linear fit of actual ownership on the same features the heuristic uses."""
    h = history.dropna(subset=["actual_own"])
    weeks = int(h["slate_date"].nunique()) if len(h) else 0
    if weeks < MIN_MODEL_WEEKS:
        return None
    parts = []
    for _, g in h.groupby("slate_date"):
        g = g.assign(playable=True).reset_index(drop=True)
        parts.append(pd.concat([g, ownership_features(g)], axis=1))
    data = pd.concat(parts, ignore_index=True)
    coef = {}
    for pos, g in data.groupby("position"):
        if len(g) < MIN_ROWS_PER_POSITION:
            continue
        X = np.column_stack([np.ones(len(g)), g[list(FEATURES)].to_numpy()])
        y = np.log(g["actual_own"].to_numpy(float) + 0.5)
        coef[pos] = np.linalg.lstsq(X, y, rcond=None)[0].round(5).tolist()
    return {"weeks": weeks, "rows": int(len(data)), "coef": coef} if coef else None
```

In `nfldfs/build.py`: add `ownership_model=None` to `build_slate`'s keyword parameters and change the ownership line to `pool["own_pct"] = ownership.estimate_ownership(pool, ownership_model)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_ownership.py tests/test_build.py -v && ./py -m pytest -q -W error`
Expected: all pass (existing ownership tests unchanged and green).

- [ ] **Step 5: Commit**

```bash
git add nfldfs/ownership.py nfldfs/build.py tests/test_ownership.py
git commit -m "Learn ownership from imported results once 3 weeks exist" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: Pipeline wiring — publish, results stage, Vegas reuse/fallback, slate archive

**Files:**
- Create: `nfldfs/publish.py`, `tests/test_publish.py`
- Modify: `nfldfs/config.py`, `nfldfs/build.py` (add `write_published()`), `run_pipeline.py`, `.gitignore`, `tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `config.DOWNLOADS` (env `NFLDFS_DOWNLOADS` overrides `~/Downloads`), `config.HISTORY = DATA / "history"`, `config.SLATES = PROCESSED / "slates"`, `config.VEGAS_REUSE_HOURS = 4`, `config.VEGAS_FALLBACK_HOURS = 48`.
  - `publish.publish(repo, paths, message, run=subprocess.run) -> str` — commits only `paths` (that exist) and pushes; returns `"published to GitHub"`, `"committed locally (no GitHub remote yet)"`, `"skipped: ..."` or `"WARNING: ..."`; never raises.
  - `build.write_published(res: dict, out_dir: Path, meta: dict) -> None` — writes `player_pool.parquet, lineups.parquet, swaps.parquet, sims.npy (float16, first N_SIMS_PUBLISHED rows), field.npy (int16), dk_upload_recommended.csv, build_meta.json`.
  - `run_pipeline` steps: `vegas_if_stale`, `results`, `publish`; stages:

```
tuesday:      salaries, stats
thursday:     salaries_if_stale, stats_if_missing, vegas, build, publish
sunday:       salaries, stats_if_missing, vegas, build, publish
sunday_late:  salaries, vegas_if_stale, build, publish
refresh:      salaries, stats_if_missing, vegas_if_stale, build, publish
results:      results, publish
build:        build
```
  - The `results` stage writes `data/published/results_status.json`; every other stage writes `run_status.json`.
  - CLI: `--results-file PATH` (import one specific standings file).
  - Files: `data/processed/slates/{slate_date}_{draft_group_id|upload}.parquet` (written by every build), `data/history/results.parquet`, `data/published/report_card.json`, `data/processed/ownership_model.json`.

- [ ] **Step 1: Write the failing tests**

`tests/test_publish.py`:

```python
import subprocess

import pytest

from nfldfs.publish import publish


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com"); _git(r, "config", "user.name", "T")
    (r / "README.md").write_text("x"); _git(r, "add", "."); _git(r, "commit", "-qm", "init")
    (r / "data" / "published").mkdir(parents=True)
    return r


def test_publish_without_remote_commits_only_given_paths(repo):
    (repo / "data/published/a.json").write_text("{}")
    (repo / "other.txt").write_text("not mine"); _git(repo, "add", "other.txt")
    assert publish(repo, ["data/published", "data/history"], "Slate update") == \
        "committed locally (no GitHub remote yet)"
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["data/published/a.json"]                      # other staged file not swept in
    assert publish(repo, ["data/published"], "again") == "skipped: nothing new to publish"


def test_publish_pushes_to_remote(repo, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare)); _git(repo, "push", "-q", "-u", "origin", "main")
    (repo / "data/published/b.json").write_text("{}")
    assert publish(repo, ["data/published"], "Slate update") == "published to GitHub"


def test_publish_push_failure_is_a_warning(repo):
    _git(repo, "remote", "add", "origin", "/nonexistent/remote.git")
    (repo / "data/published/c.json").write_text("{}")
    msg = publish(repo, ["data/published"], "Slate update")
    assert msg.startswith("WARNING: push to GitHub failed")


def test_publish_not_a_repo(tmp_path):
    assert publish(tmp_path, ["data/published"], "x") == "skipped: not a git repository"
```

Append to `tests/test_run_pipeline.py`:

```python
import datetime as dt
import json
import zipfile
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.conftest import make_pool


def _paths(tmp_path, monkeypatch):
    for name in ("PUBLISHED", "PROCESSED", "RAW", "HISTORY", "LOGS"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "SLATES", tmp_path / "processed" / "slates")
    monkeypatch.setattr(config, "DOWNLOADS", tmp_path / "Downloads")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "processed").mkdir()


def _odds(tmp_path, hours_ago):
    fetched = (dt.datetime.now() - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    (tmp_path / "processed" / "odds_meta.json").write_text(json.dumps({"fetched_at": fetched}))
    (tmp_path / "processed" / "vegas_games.parquet").write_bytes(b"x")


def test_vegas_if_stale_skips_recent_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 1)
    monkeypatch.setattr(run_pipeline, "step_vegas", lambda t, a: pytest.fail("should not refetch"))
    assert run_pipeline.step_vegas_if_stale(dt.date(2026, 10, 18), SimpleNamespace()).startswith("skipped")


def test_vegas_if_stale_refetches_old_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 5)
    monkeypatch.setattr(run_pipeline, "step_vegas", lambda t, a: "fetched")
    assert run_pipeline.step_vegas_if_stale(dt.date(2026, 10, 18), SimpleNamespace()) == "fetched"


def test_vegas_falls_back_to_recent_lines(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _odds(tmp_path, 10)
    monkeypatch.setattr(config, "odds_api_key", lambda: "k")
    def boom(key):
        raise RuntimeError("The Odds API request failed (HTTP 429)")
    monkeypatch.setattr(run_pipeline.vegas, "fetch_odds", boom)
    msg = run_pipeline.step_vegas(dt.date(2026, 10, 18), SimpleNamespace())
    assert msg.startswith("WARNING") and "Reusing lines" in msg
    _odds(tmp_path, 60)
    with pytest.raises(RuntimeError):
        run_pipeline.step_vegas(dt.date(2026, 10, 18), SimpleNamespace())


def test_results_stage_writes_its_own_status(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    monkeypatch.setitem(run_pipeline.STEP_FUNCS, "publish", lambda t, a: "skipped: test")
    assert run_pipeline.main(["--stage", "results", "--today", "2026-10-19"]) == 0
    status = json.loads((tmp_path / "published" / "results_status.json").read_text())
    assert status["steps"][0]["message"] == "skipped: no new contest-standings file"
    assert not (tmp_path / "published" / "run_status.json").exists()


def _snapshot_file(tmp_path, date="2026-10-18"):
    p = make_pool()
    p["median"], p["floor"], p["ceiling"], p["own_pct"] = 10.0, 5.0, 20.0, 8.0
    (tmp_path / "processed" / "slates").mkdir(parents=True, exist_ok=True)
    p.to_parquet(tmp_path / "processed" / "slates" / f"{date}_154941.parquet", index=False)


def _standings_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contest-standings-1.csv",
                   "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                   "1,1,someone,0,100,x,,AAA QB1,QB,30.00%,22.0\n")
    return path


def test_step_results_imports_moves_and_reports(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch); _snapshot_file(tmp_path)
    z = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    import os
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    os.utime(z, (monday, monday))                                 # file date drives slate matching
    msg = run_pipeline.step_results(dt.date(2026, 10, 19), SimpleNamespace(results_file=None))
    assert "2026-10-18" in msg
    assert not z.exists() and (tmp_path / "raw" / "standings" / z.name).exists()
    hist = pd.read_parquet(tmp_path / "history" / "results.parquet")
    assert "EntryName" not in hist.columns and "someone" not in hist.to_csv()
    assert json.loads((tmp_path / "published" / "report_card.json").read_text())["weeks"] == 1


def test_step_results_matches_by_download_date(tmp_path, monkeypatch):
    _paths(tmp_path, monkeypatch)
    _snapshot_file(tmp_path, "2026-10-18"); _snapshot_file(tmp_path, "2026-10-25")
    z = _standings_zip(tmp_path / "Downloads" / "contest-standings-1.zip")
    monday = dt.datetime(2026, 10, 19, 9, 0).timestamp()
    import os
    os.utime(z, (monday, monday))                                 # downloaded the Monday after 10/18
    msg = run_pipeline.step_results(dt.date(2026, 10, 27), SimpleNamespace(results_file=None))
    assert "2026-10-18" in msg                                    # not the 10/25 slate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_publish.py tests/test_run_pipeline.py -v`
Expected: ImportError for `nfldfs.publish`; new pipeline tests fail (missing steps/config).

- [ ] **Step 3: Implement `nfldfs/publish.py`**

```python
"""Commit and push published files so Streamlit Cloud redeploys. Never raises; never blocks local use."""
from __future__ import annotations

import subprocess
from pathlib import Path

PUSH_TIMEOUT = 90


def _git(repo: Path, *args: str, run=subprocess.run, timeout: int = 60):
    return run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def publish(repo, paths: list[str], message: str, run=subprocess.run) -> str:
    repo = Path(repo)
    if not (repo / ".git").exists():
        return "skipped: not a git repository"
    paths = [p for p in paths if (repo / p).exists()]
    if not paths:
        return "skipped: nothing to publish yet"
    try:
        add = _git(repo, "add", "--", *paths, run=run)
        if add.returncode != 0:
            return f"WARNING: git add failed — {add.stderr.strip()[:200]}"
        if _git(repo, "diff", "--cached", "--quiet", "--", *paths, run=run).returncode == 0:
            return "skipped: nothing new to publish"
        commit = _git(repo, "commit", "-m", message, "--", *paths, run=run)
        if commit.returncode != 0:
            return f"WARNING: git commit failed — {commit.stderr.strip()[:200]}"
        if not _git(repo, "remote", run=run).stdout.strip():
            return "committed locally (no GitHub remote yet)"
        push = _git(repo, "push", run=run, timeout=PUSH_TIMEOUT)
        if push.returncode != 0:
            return (f"WARNING: push to GitHub failed — {push.stderr.strip()[:200]} "
                    f"(the local app still works)")
        return "published to GitHub"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"WARNING: publishing failed — {type(e).__name__}"
```

- [ ] **Step 4: Config, `write_published`, pipeline, ignore rules**

`nfldfs/config.py` — add `import os` is already there; add after `LOGS`:

```python
HISTORY = DATA / "history"
SLATES = PROCESSED / "slates"
DOWNLOADS = Path(os.environ.get("NFLDFS_DOWNLOADS", str(Path.home() / "Downloads")))
VEGAS_REUSE_HOURS = 4              # Sunday 11:45 reuses the 9:00 lines
VEGAS_FALLBACK_HOURS = 48          # if the odds fetch fails, reuse lines up to this old (loud warning)
```

`nfldfs/build.py` — add (imports: `json`, `numpy as np`, `from pathlib import Path`, `from .config import N_SIMS_PUBLISHED`, `from .dk_rules import write_upload_csv`, `from .status import atomic_save_npy, atomic_write_parquet, atomic_write_text`):

```python
def write_published(res: dict, out_dir, meta: dict) -> None:
    """Everything the app reads. Each file is written atomically; build_meta.json goes last."""
    out = Path(out_dir)
    atomic_write_parquet(res["pool"], out / "player_pool.parquet")
    atomic_write_parquet(res["lineups"], out / "lineups.parquet")
    atomic_write_parquet(res["swaps"], out / "swaps.parquet")
    atomic_save_npy(res["sims"][:N_SIMS_PUBLISHED].astype(np.float16), out / "sims.npy")
    atomic_save_npy(np.asarray(res["field"]).astype(np.int16), out / "field.npy")
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    write_upload_csv([g for _, g in rec.groupby("contest_key", sort=False)], out / "dk_upload_recommended.csv")
    atomic_write_text(out / "build_meta.json", json.dumps(meta, indent=2, default=str))
```

`run_pipeline.py`:
- imports: add `shutil`, `from nfldfs import ownership, publish, results` and `from nfldfs.build import write_published`.
- `step_build`: load `schedule_rows` (Task 1) and `ownership_model.json` when present; call `build.build_slate(..., schedule_rows=..., ownership_model=...)`; compute `slate_date = str(pd.read_parquet(P / "pool_base.parquet", columns=["kickoff"]).kickoff.min().date())`; archive `atomic_write_parquet(res["pool"], config.SLATES / f"{slate_date}_{slate.get('draft_group_id') or 'upload'}.parquet")`; build `meta` as before plus `"slate_date": slate_date` and `"ownership_model_weeks": (model or {}).get("weeks")`; replace the individual published writes with `write_published(res, config.PUBLISHED, meta)`. (Remove the now-duplicated `atomic_*`/`write_upload_csv` calls; `field.npy` from Task 2 is now written by `write_published`.)
- add:

```python
def _odds_age_hours() -> float | None:
    p = config.PROCESSED / "odds_meta.json"
    if not p.exists():
        return None
    fetched = json.loads(p.read_text()).get("fetched_at")
    if not fetched:
        return None
    return (dt.datetime.now() - dt.datetime.fromisoformat(fetched)).total_seconds() / 3600


def step_vegas_if_stale(today, args) -> str:
    age = _odds_age_hours()
    if age is not None and age < config.VEGAS_REUSE_HOURS and (config.PROCESSED / "vegas_games.parquet").exists():
        return f"skipped: lines fetched {age * 60:.0f} min ago"
    return step_vegas(today, args)


def step_results(today, args) -> str:
    done = config.RAW / "standings"
    files = ([Path(args.results_file)] if getattr(args, "results_file", None)
             else results.find_new_standings(config.DOWNLOADS, done))
    if not files:
        return "skipped: no new contest-standings file"
    done.mkdir(parents=True, exist_ok=True)
    hist, slates = None, []
    for f in files:
        downloaded = dt.date.fromtimestamp(f.stat().st_mtime)
        snap = results.latest_slate_snapshot(config.SLATES, min(today, downloaded))
        if snap is None:
            raise RuntimeError(f"No built slate on or before {min(today, downloaded)} to match {f.name} to — "
                               "results can only be imported for slates this app built.")
        slate_date, dg = results.snapshot_key(snap)
        rows = results.match_to_slate(results.read_standings(f), pd.read_parquet(snap), slate_date, dg)
        hist = results.append_history(config.HISTORY / "results.parquet", rows)
        shutil.move(str(f), str(done / f.name))
        slates.append(slate_date)
    card = results.report_card(hist)
    atomic_write_text(config.PUBLISHED / "report_card.json", json.dumps(card, indent=2))
    model = ownership.fit_ownership_model(hist)
    if model:
        atomic_write_text(config.PROCESSED / "ownership_model.json", json.dumps(model, indent=2))
    return (f"imported {len(files)} file(s) for the {', '.join(sorted(set(slates)))} slate; "
            f"{card['weeks']} week(s) of results" + ("; ownership model updated" if model else ""))


def step_publish(today, args) -> str:
    return publish.publish(config.ROOT, ["data/published", "data/history"], f"Slate update: {args.stage} {today}")
```

- `step_vegas`: wrap the fetch:

```python
def step_vegas(today, args) -> str:
    try:
        events, remaining = vegas.fetch_odds(config.odds_api_key())
    except RuntimeError as e:
        age = _odds_age_hours()
        if age is not None and age <= config.VEGAS_FALLBACK_HOURS and \
                (config.PROCESSED / "vegas_games.parquet").exists():
            return f"WARNING: {e} Reusing lines fetched {age:.0f}h ago."
        raise
    games = vegas.parse_odds(events)
    atomic_write_parquet(games, config.PROCESSED / "vegas_games.parquet")
    atomic_write_text(config.PROCESSED / "odds_meta.json",
                      json.dumps({"fetched_at": _now(), "requests_remaining": remaining}, indent=2))
    return f"{len(games)} games with lines; Odds API requests remaining: {remaining}"
```

- replace `STAGES` with the table in Interfaces; add `"vegas_if_stale": step_vegas_if_stale, "results": step_results, "publish": step_publish` to `STEP_FUNCS`; add `ap.add_argument("--results-file", help="import one DraftKings contest-standings file")`; in `main`, `status_file = "results_status.json" if args.stage == "results" else "run_status.json"` and `RunStatus(config.PUBLISHED / status_file, args.stage)`.
- update the module docstring's usage lines to list every stage.

`.gitignore` — replace the `data/` line with:

```
data/*
!data/published/
!data/history/
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_publish.py tests/test_run_pipeline.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 6: Offline re-build and a dry publish check**

```bash
./py run_pipeline.py --stage build && ls data/published data/processed/slates && git status --short data/
```
Expected: build exits 0; `field.npy` present; one snapshot file in `data/processed/slates/`; `git status` now lists `data/published/` files as untracked (publishing them happens in Task 12 — do **not** commit them in this task).

- [ ] **Step 7: Commit**

```bash
git add nfldfs/publish.py nfldfs/config.py nfldfs/build.py run_pipeline.py .gitignore tests/test_publish.py tests/test_run_pipeline.py
git commit -m "Add publish, results stage, Vegas reuse/fallback and slate archive to the pipeline" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 6: App foundation — data loading, header, hosted mode, actions

**Files:**
- Create: `app.py`, `nfldfs_app/__init__.py`, `nfldfs_app/data.py`, `nfldfs_app/ui.py`, `nfldfs_app/actions.py`, `nfldfs_app/scoring.py`, stub views `nfldfs_app/view_recommended.py`, `nfldfs_app/view_builder.py`, `nfldfs_app/view_pool.py`, `nfldfs_app/view_sidebar.py`, `tests/test_app_data.py`, `tests/test_ui.py`, `tests/test_app_smoke.py`
- Modify: `nfldfs/dk_rules.py` (`upload_csv_text`), `run_pipeline.py` (`build_meta.json` gains `built_at_utc`), `requirements.txt` (`streamlit>=1.58`), `tests/conftest.py` (move the synthetic inputs here + `published_dir` and `make_app` fixtures), `tests/test_build.py` (import the moved helpers), `tests/test_dk_rules.py`

**Interfaces:**
- Produces:
  - `dk_rules.upload_csv_text(lineups: list[DataFrame]) -> str` (same validation as `write_upload_csv`, which now calls it).
  - `nfldfs_app.data`: `REQUIRED_FILES`, `published_dir() -> Path` (env `NFLDFS_PUBLISHED`), `is_hosted() -> bool` (env `NFLDFS_FORCE_HOSTED` = "1"/"0" overrides; else "no `caffeinate` binary"), `missing_files(pub) -> list[str]`, `stamp(pub) -> tuple` (cache key), `load(pub) -> AppData`, `minutes_since(iso, now=None) -> float | None` (handles naive-local and timezone-aware ISO strings). `AppData` fields: `pool, lineups (with mu_label/mu_color/mu_text joined in), swaps, sims (float32), field (int), meta, run_status, results_status, report_card, row_of: dict[dk_id → pool row]`.
  - `nfldfs_app.ui`: `TIER_ICON`, `KEY_MARKDOWN`, `MODEL_RELATIVE_HELP`, `money(v) -> "$7,500"`, `metric_phrase(contest_key, group) -> str`, `updated_text(minutes) -> (text, color)`, `styled_lineup(df) -> Styler` (needs columns `slot, name, team, opp, mu_label, mu_color, salary, median, floor, ceiling, own_pct, tier`), `styled_pool(df) -> Styler` (needs `name, position, team, opp, mu_label, mu_color, salary, median, floor, ceiling, boom_rate, value, own_pct, tier`).
  - `nfldfs_app.scoring.published_metric(d, ids, contest_key, field_scores) -> float`.
  - `nfldfs_app.actions`: `run_stage(stage, *extra, run=subprocess.run) -> (ok: bool, tail: str)`, `save_upload(uploaded, folder) -> Path`.
  - Each `view_*.render(...)` signature (filled in by Tasks 7–10): `view_recommended.render(d, key, label, field_scores)`, `view_builder.render(d, key, label, field_scores)`, `view_pool.render(d, key, label, field_scores)`, `view_sidebar.render(d, hosted)`.
  - Test fixtures in `tests/conftest.py`: `synthetic_inputs()`, `SYNTH_MODEL`, session fixture `published_dir`, fixture `make_app(pub, hosted="1") -> AppTest` (sets `NFLDFS_PUBLISHED`, `NFLDFS_FORCE_HOSTED`, `NFLDFS_NO_COMPONENT=1`).

- [ ] **Step 1: Move the synthetic build inputs into `tests/conftest.py` and add fixtures**

Move `MODEL` → `SYNTH_MODEL` and `_inputs()` → `synthetic_inputs()` from `tests/test_build.py` into `tests/conftest.py` unchanged (same bodies), and in `tests/test_build.py` replace them with `from tests.conftest import SYNTH_MODEL as MODEL, synthetic_inputs as _inputs`. Then append to `tests/conftest.py`:

```python
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(scope="session")
def published_dir(tmp_path_factory):
    from nfldfs import build
    pool_base, pw, tw, games = synthetic_inputs()
    res = build.build_slate(pool_base, pw, tw, SYNTH_MODEL, games, n_sims=300, seed=1, n_candidates=3,
                            field_size=150)
    out = tmp_path_factory.mktemp("published")
    meta = {"game_count": 2, "draft_group_id": 1, "slate_date": "2026-10-18", "built_at": "2026-10-15T09:00:00",
            "built_at_utc": "2026-10-15T13:00:00+00:00", "n_sims": 300, "match_rate": 1.0,
            "odds_requests_remaining": "490"}
    build.write_published(res, out, meta)
    (out / "run_status.json").write_text(json.dumps({"stage": "thursday", "ok": True, "steps": []}))
    return out


@pytest.fixture
def make_app(monkeypatch):
    def _make(pub, hosted="1"):
        monkeypatch.setenv("NFLDFS_PUBLISHED", str(pub))
        monkeypatch.setenv("NFLDFS_FORCE_HOSTED", hosted)
        monkeypatch.setenv("NFLDFS_NO_COMPONENT", "1")
        at = AppTest.from_file(APP, default_timeout=90)
        at.run()
        return at
    return _make
```

- [ ] **Step 2: Write the failing tests**

`tests/test_dk_rules.py` — append:

```python
def test_upload_csv_text_matches_file(pool, tmp_path):
    good = _lineup(pool, _valid_ids(pool))
    text = dk_rules.upload_csv_text([good])
    dk_rules.write_upload_csv([good], tmp_path / "u.csv")
    assert text == (tmp_path / "u.csv").read_text() and text.startswith("QB,RB,RB,WR,WR,WR,TE,FLEX,DST\n")
```

`tests/test_app_data.py`:

```python
import datetime as dt

from nfldfs_app import data


def test_load_published(published_dir):
    d = data.load(published_dir)
    assert data.missing_files(published_dir) == []
    assert {"mu_label", "mu_color", "mu_text"} <= set(d.lineups.columns)
    assert d.sims.dtype.name == "float32" and d.field.shape[1] == 9
    assert d.row_of[int(d.pool.dk_id.iloc[5])] == 5
    assert d.meta["game_count"] == 2


def test_missing_files_and_hosted_override(tmp_path, monkeypatch):
    assert "player_pool.parquet" in data.missing_files(tmp_path)
    monkeypatch.setenv("NFLDFS_FORCE_HOSTED", "1"); assert data.is_hosted()
    monkeypatch.setenv("NFLDFS_FORCE_HOSTED", "0"); assert not data.is_hosted()


def test_minutes_since_naive_and_aware():
    now = dt.datetime(2026, 10, 15, 10, 0)
    assert data.minutes_since("2026-10-15T09:00:00", now) == 60
    aware_now = dt.datetime(2026, 10, 15, 14, 0, tzinfo=dt.timezone.utc)
    assert data.minutes_since("2026-10-15T13:00:00+00:00", aware_now) == 60
    assert data.minutes_since(None) is None
```

`tests/test_ui.py`:

```python
import pandas as pd

from nfldfs_app import ui


def test_money_full_dollars():
    assert ui.money(7500) == "$7,500" and ui.money(-1700) == "-$1,700" and ui.money(49900.0) == "$49,900"


def test_metric_phrase():
    assert ui.metric_phrase("h2h", "Cash") == "Wins the head-to-head"
    assert ui.metric_phrase("fifty_fifty", "Cash") == "Cashes"
    assert ui.metric_phrase("multiplier_3x", "Multiplier") == "Hits the multiplier"
    assert ui.metric_phrase("tournament", "Tournament") == "Finishes top-1%"


def test_updated_text_colors():
    assert ui.updated_text(5) == ("Updated 5 min ago", "green")
    assert ui.updated_text(180) == ("Updated 3 h ago", "orange")
    assert ui.updated_text(3000)[1] == "red" and ui.updated_text(None)[1] == "gray"


def test_styled_lineup_formats_salary(published_dir):
    from nfldfs_app import data
    d = data.load(published_dir)
    rec = d.lineups[(d.lineups.contest_key == "fifty_fifty") & (d.lineups["rank"] == 0)]
    html = ui.styled_lineup(rec).to_html()
    assert "$" in html and "," in html and "background-color" in html
```

`tests/test_app_smoke.py`:

```python
import json
import shutil

from nfldfs.config import CONTEST_TYPES


def test_app_renders_header(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    assert at.title[0].value == "NFL DFS Lineups"
    assert at.selectbox(key="contest_label").options == [c["label"] for c in CONTEST_TYPES.values()]
    assert any("hosted copy" in i.value for i in at.info)            # hosted banner


def test_app_without_published_files(make_app, tmp_path):
    at = make_app(tmp_path)
    assert not at.exception
    assert "No lineups built yet" in at.warning[0].value


def test_failed_run_shows_banner(make_app, published_dir, tmp_path):
    pub = tmp_path / "pub"
    shutil.copytree(published_dir, pub)
    (pub / "run_status.json").write_text(json.dumps({"stage": "sunday", "ok": False, "steps": [
        {"name": "vegas", "ok": False, "message": "RuntimeError: The Odds API request failed (HTTP 429)"}]}))
    at = make_app(pub)
    assert any("failed at **vegas**" in e.value for e in at.error)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./py -m pytest tests/test_dk_rules.py tests/test_app_data.py tests/test_ui.py tests/test_app_smoke.py -v`
Expected: ImportErrors (`nfldfs_app`, `upload_csv_text`, missing `app.py`).

- [ ] **Step 4: Implement**

`nfldfs/dk_rules.py` — replace `write_upload_csv` with:

```python
def upload_csv_text(lineups: list[pd.DataFrame]) -> str:
    """DraftKings bulk-upload format: slot header row, then one row of player IDs per lineup."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ROSTER_SLOTS)
    for lu in lineups:
        w.writerow(assign_slots(lu))
    return buf.getvalue()


def write_upload_csv(lineups: list[pd.DataFrame], path) -> None:
    atomic_write_text(path, upload_csv_text(lineups))
```

`run_pipeline.py` `step_build`: add `"built_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")` to `meta`.

`requirements.txt`: add a line `streamlit>=1.58` (above `# Testing`).

`nfldfs_app/__init__.py`: empty file.

`nfldfs_app/data.py`:

```python
"""Load the engine's published files for the app (local Mac or Streamlit Cloud)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import numpy as np
import pandas as pd

from nfldfs import config

REQUIRED_FILES = ("player_pool.parquet", "lineups.parquet", "swaps.parquet", "sims.npy", "field.npy",
                  "build_meta.json")
OPTIONAL_FILES = ("run_status.json", "results_status.json", "report_card.json")
MATCHUP_DEFAULTS = {"mu_label": "Neutral", "mu_color": "#8a8a3d", "mu_text": ""}


def published_dir() -> Path:
    return Path(os.environ.get("NFLDFS_PUBLISHED", str(config.PUBLISHED)))


def is_hosted() -> bool:
    forced = os.environ.get("NFLDFS_FORCE_HOSTED")
    if forced is not None:
        return forced == "1"
    return shutil.which("caffeinate") is None      # macOS-only binary; absent on Streamlit Cloud (MLB pattern)


def missing_files(pub: Path) -> list[str]:
    return [f for f in REQUIRED_FILES if not (Path(pub) / f).exists()]


def stamp(pub: Path) -> tuple:
    pub = Path(pub)
    return tuple((f, (pub / f).stat().st_mtime if (pub / f).exists() else 0.0)
                 for f in (*REQUIRED_FILES, *OPTIONAL_FILES))


def _json(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


@dataclass
class AppData:
    pool: pd.DataFrame
    lineups: pd.DataFrame
    swaps: pd.DataFrame
    sims: np.ndarray
    field: np.ndarray
    meta: dict
    run_status: dict
    results_status: dict
    report_card: dict
    row_of: dict = dc_field(default_factory=dict)

    def __post_init__(self):
        self.row_of = {int(d): i for i, d in enumerate(self.pool["dk_id"])}


def load(pub: Path) -> AppData:
    pub = Path(pub)
    pool = pd.read_parquet(pub / "player_pool.parquet")
    for col, default in MATCHUP_DEFAULTS.items():          # builds made before matchups existed
        if col not in pool.columns:
            pool[col] = default
    lineups = pd.read_parquet(pub / "lineups.parquet").merge(
        pool[["dk_id", *MATCHUP_DEFAULTS]], on="dk_id", how="left")
    return AppData(pool=pool, lineups=lineups, swaps=pd.read_parquet(pub / "swaps.parquet"),
                   sims=np.load(pub / "sims.npy").astype(np.float32),
                   field=np.load(pub / "field.npy").astype(np.int64),
                   meta=_json(pub / "build_meta.json"), run_status=_json(pub / "run_status.json"),
                   results_status=_json(pub / "results_status.json"),
                   report_card=_json(pub / "report_card.json"))


def minutes_since(iso: str | None, now: dt.datetime | None = None) -> float | None:
    if not iso:
        return None
    then = dt.datetime.fromisoformat(str(iso))
    if now is None:
        now = dt.datetime.now(then.tzinfo) if then.tzinfo else dt.datetime.now()
    return (now - then).total_seconds() / 60
```

`nfldfs_app/ui.py`:

```python
"""Formatting and small widgets shared by the app's tabs."""
from __future__ import annotations

import pandas as pd

TIER_ICON = {"Chalk": "🔥 Chalk", "Popular": "Popular", "Moderate": "Moderate", "Contrarian": "💎 Contrarian"}
MODEL_RELATIVE_HELP = "Share of simulated Sundays where this happens — for comparing lineups, not real-world odds."
KEY_MARKDOWN = (
    "**Ownership** — share of the field expected to play him\n"
    "- 🔥 **Chalk** 25%+ · safe, but no edge\n"
    "- **Popular** 10–25%\n"
    "- **Moderate** 5–10%\n"
    "- 💎 **Contrarian** under 5% · if he hits, you pass most of the field\n\n"
    "**Matchup** — points the defense allows to that position (last 6 games)\n"
    "- 🟩 green = soft defense · 🟥 red = tough defense\n\n"
    "_Cash games: lean Chalk. Tournaments: mix in Moderate/Contrarian._")


def money(v) -> str:
    v = int(round(float(v)))
    return f"-${abs(v):,}" if v < 0 else f"${v:,}"


def metric_phrase(contest_key: str, group: str) -> str:
    if contest_key == "h2h":
        return "Wins the head-to-head"
    return {"Cash": "Cashes", "Multiplier": "Hits the multiplier", "Tournament": "Finishes top-1%"}[group]


def updated_text(minutes: float | None) -> tuple[str, str]:
    if minutes is None:
        return "Update time unknown", "gray"
    if minutes < 60:
        return f"Updated {max(int(minutes), 0)} min ago", "green"
    if minutes < 24 * 60:
        return f"Updated {int(minutes // 60)} h ago", "orange"
    return f"Updated {int(minutes // 1440)} days ago", "red"


def _matchup_css(colors: list[str]):
    return lambda col: [f"background-color: {c}; color: white; font-weight: 600" for c in colors]


def _matchup(df: pd.DataFrame):
    return ("vs " + df["opp"].astype(str) + " · " + df["mu_label"].astype(str)).to_numpy()


def styled_lineup(df: pd.DataFrame):
    view = pd.DataFrame({
        "Pos": df["slot"].to_numpy(), "Player": df["name"].to_numpy(), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(), "Own %": df["own_pct"].to_numpy(),
        "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Own %": "{:.0f}%"}))


def styled_pool(df: pd.DataFrame):
    view = pd.DataFrame({
        "Player": df["name"].to_numpy(), "Pos": df["position"].to_numpy(), "Team": df["team"].to_numpy(),
        "Matchup": _matchup(df), "Salary": df["salary"].to_numpy(), "Median": df["median"].to_numpy(),
        "Floor": df["floor"].to_numpy(), "Ceiling": df["ceiling"].to_numpy(),
        "Boom %": (df["boom_rate"] * 100).to_numpy(), "Pts/$1K": df["value"].to_numpy(),
        "Own %": df["own_pct"].to_numpy(), "Tier": df["tier"].map(TIER_ICON).to_numpy()})
    return (view.style.apply(_matchup_css(df["mu_color"].tolist()), subset=["Matchup"])
            .format({"Salary": "${:,.0f}", "Median": "{:.1f}", "Floor": "{:.1f}", "Ceiling": "{:.1f}",
                     "Boom %": "{:.0f}%", "Pts/$1K": "{:.2f}", "Own %": "{:.1f}%"}))
```

`nfldfs_app/scoring.py`:

```python
"""Contest metrics for any lineup against the published simulations and field."""
from __future__ import annotations

from nfldfs.config import CONTEST_TYPES
from nfldfs.sim_eval import contest_metric, lineup_scores


def published_metric(d, ids, contest_key: str, field_scores) -> float:
    rows = [d.row_of[int(i)] for i in ids]
    scores = lineup_scores(d.sims, [rows])
    return float(contest_metric(scores, field_scores, CONTEST_TYPES[contest_key]["metric"])[0])
```

`nfldfs_app/actions.py`:

```python
"""Local-only actions: run pipeline stages from the app and save uploaded files."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nfldfs.config import ROOT

STAGE_TIMEOUT = 900


def run_stage(stage: str, *extra: str, run=subprocess.run) -> tuple[bool, str]:
    r = run([sys.executable, str(ROOT / "run_pipeline.py"), "--stage", stage, *extra], cwd=str(ROOT),
            capture_output=True, text=True, timeout=STAGE_TIMEOUT)
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode == 0, "\n".join(lines[-15:])


def save_upload(uploaded, folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(uploaded.name).name
    path.write_bytes(uploaded.getvalue())
    return path
```

Stub views (replaced in Tasks 7–10) — each of `nfldfs_app/view_recommended.py`, `view_builder.py`, `view_pool.py`:

```python
import streamlit as st


def render(d, key, label, field_scores):
    st.info("This tab is built in a later task.")
```

and `nfldfs_app/view_sidebar.py`:

```python
import streamlit as st


def render(d, hosted):
    st.sidebar.markdown("### 🏈 NFL DFS")
```

`app.py`:

```python
"""NFL DFS Lineups — Streamlit app. Runs locally (full features) and on Streamlit Community Cloud (view/build)."""
from pathlib import Path

import streamlit as st

from nfldfs.config import CONTEST_TYPES
from nfldfs.sim_eval import lineup_scores
from nfldfs_app import actions, data, ui, view_builder, view_pool, view_recommended, view_sidebar

st.set_page_config(page_title="NFL DFS Lineups", page_icon="🏈", layout="wide")


@st.cache_resource(show_spinner=False, max_entries=2)
def _load(pub: str, stamp: tuple):
    d = data.load(Path(pub))
    return d, lineup_scores(d.sims, d.field)


pub = data.published_dir()
hosted = data.is_hosted()
if data.missing_files(pub):
    st.title("NFL DFS Lineups")
    st.warning("No lineups built yet. On your Mac run `./py run_pipeline.py --stage thursday`"
               + (" — this page updates automatically once it publishes." if hosted else "."))
    st.stop()
d, field_scores = _load(str(pub), data.stamp(pub))

flash = st.session_state.pop("flash", None)
if flash:
    (st.success if flash[0] else st.error)(flash[1].splitlines()[-1] if flash[1] else "Done")
    if not flash[0]:
        st.code(flash[1])
if hosted:
    st.info("📱 This is the hosted copy — view lineups, build variations and download CSVs. Refreshing data and "
            "importing results happen on your Mac and publish here automatically.")
failed = [s for s in d.run_status.get("steps", []) if s.get("ok") is False]
if failed:
    st.error(f"⚠ The last {d.run_status.get('stage', '')} run failed at **{failed[0]['name']}**: "
             f"{failed[0]['message']}")

labels = {c["label"]: k for k, c in CONTEST_TYPES.items()}
top = st.columns([3, 3, 1, 1], vertical_alignment="bottom")
with top[0]:
    st.title("NFL DFS Lineups")
    text, color = ui.updated_text(data.minutes_since(d.meta.get("built_at_utc") or d.meta.get("built_at")))
    st.markdown(f"Sunday main slate · {d.meta.get('game_count', '?')} games · :{color}[{text}]")
label = top[1].selectbox("DraftKings contest type", list(labels), index=list(labels.values()).index("single_entry"),
                         key="contest_label")
key = labels[label]
with top[2].popover("ℹ️ Key", width="stretch"):
    st.markdown(ui.KEY_MARKDOWN)
if not hosted and top[3].button("⟳ Refresh", width="stretch", key="refresh",
                                help="Re-fetch injuries and lines, then rebuild lineups (about 2 minutes)"):
    with st.spinner("Refreshing — about 2 minutes…"):
        st.session_state.flash = actions.run_stage("refresh")
    st.cache_resource.clear()
    st.rerun()

view_sidebar.render(d, hosted)
tab_rec, tab_mine, tab_pool = st.tabs(["⭐ Recommended", "🛠 My Lineup", "📋 Player pool"])
with tab_rec:
    view_recommended.render(d, key, label, field_scores)
with tab_mine:
    view_builder.render(d, key, label, field_scores)
with tab_pool:
    view_pool.render(d, key, label, field_scores)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pip install -r requirements.txt -q && ./py -m pytest tests/test_dk_rules.py tests/test_app_data.py tests/test_ui.py tests/test_app_smoke.py tests/test_build.py -v && ./py -m pytest -q -W error`
Expected: all pass. If `AppTest` can't render `st.popover`/`width=` in this Streamlit version, report the exact error rather than removing the feature.

- [ ] **Step 6: Commit**

```bash
git add app.py nfldfs_app nfldfs/dk_rules.py run_pipeline.py requirements.txt tests/conftest.py tests/test_build.py tests/test_dk_rules.py tests/test_app_data.py tests/test_ui.py tests/test_app_smoke.py
git commit -m "Add the Streamlit app foundation: data loading, header, hosted mode, actions" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 7: ⭐ Recommended tab + report card

**Files:**
- Modify: `nfldfs_app/view_recommended.py` (replace stub), `nfldfs_app/ui.py` (add `swap_line`, `report_card_widget`)
- Create: `tests/test_view_recommended.py`

**Interfaces:**
- Consumes: `AppData`, `ui.*`, `scoring.published_metric`, `dk_rules.upload_csv_text`.
- Produces: `view_recommended.stack_summary(lineup_df) -> str`; `apply_swap(rec_ids, out_id, in_id) -> (new_ids, slot_index)`; `render(d, key, label, field_scores)`. Session keys set by **Apply**: `my_ids` (list of 9 dk_ids), `focus_slot` (int), `focus_token` (incrementing int). `ui.swap_line(swap_row, pool_by_id) -> str` (markdown, `$` escaped), `ui.report_card_widget(card)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_view_recommended.py`:

```python
import pandas as pd

from nfldfs_app import data, scoring, view_recommended


def _lu(rows):
    return pd.DataFrame(rows, columns=["name", "position", "team", "opp"])


def test_stack_summary():
    lu = _lu([("QB A", "QB", "BUF", "LV"), ("WR B", "WR", "BUF", "LV"), ("WR C", "WR", "LV", "BUF"),
              ("RB D", "RB", "KC", "LAC")])
    assert view_recommended.stack_summary(lu) == "Stack: QB A + WR B · bring-back: WR C"
    assert view_recommended.stack_summary(_lu([("QB A", "QB", "BUF", "LV")])) == "No QB stack (QB A alone)"


def test_apply_swap():
    ids, slot = view_recommended.apply_swap([1, 2, 3, 4, 5, 6, 7, 8, 9], 4, 40)
    assert ids == [1, 2, 3, 40, 5, 6, 7, 8, 9] and slot == 3


def test_published_metric_in_range(published_dir):
    from nfldfs.sim_eval import lineup_scores
    d = data.load(published_dir)
    rec = d.lineups[(d.lineups.contest_key == "fifty_fifty") & (d.lineups["rank"] == 0)]
    m = scoring.published_metric(d, rec.dk_id.tolist(), "fifty_fifty", lineup_scores(d.sims, d.field))
    assert 0.0 <= m <= 1.0


def test_recommended_tab_renders_and_apply_copies(make_app, published_dir):
    at = make_app(published_dir)
    at.selectbox(key="contest_label").set_value("50/50").run()
    assert not at.exception
    assert len(at.dataframe) >= 1
    apply = [b for b in at.button if b.key and b.key.startswith("apply_fifty_fifty_")]
    assert apply, "expected at least one outlier swap for 50/50 on the synthetic slate"
    apply[0].click().run()
    assert len(at.session_state["my_ids"]) == 9 and isinstance(at.session_state["focus_slot"], int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_view_recommended.py -v`
Expected: FAIL (`stack_summary`, `apply_swap` missing; stub renders no dataframe).

- [ ] **Step 3: Implement**

Append to `nfldfs_app/ui.py`:

```python
def swap_line(s, pool_by_id) -> str:
    p = pool_by_id.loc[int(s.in_dk_id)]
    sign = "+" if s.salary_delta > 0 else "−"
    tag = (f"<span style='background:{p['mu_color']};color:#fff;font-weight:600;font-size:12px;"
           f"padding:1px 6px;border-radius:4px'>vs {p['opp']} · {p['mu_label']}</span>")
    return (f"Swap **{s.out_name}** → **{s.in_name}** ({s.position}, {s.in_team}, {TIER_ICON[s.in_tier]} "
            f"{s.in_own_pct:.1f}%) {tag} · {sign}\\${abs(int(s.salary_delta)):,} · "
            f"\\${int(s.remaining_salary):,} left · ceiling {s.ceiling_delta:+.1f}")


def report_card_widget(card: dict) -> None:
    import streamlit as st
    if not card or not card.get("weeks"):
        st.caption("No results imported yet — after Sunday's games, follow 📥 in the sidebar.")
        return
    lat, sea = card.get("latest", {}), card.get("season", {})
    c = st.columns(3)
    c[0].metric("Projection error", f"{lat.get('proj_mae', '—')} pts",
                help="Average gap between our median and the actual DraftKings points.")
    c[1].metric("Actual inside floor–ceiling", f"{lat.get('in_range_pct', '—')}%",
                help="About 65% means the floor/ceiling ranges are well calibrated.")
    c[2].metric("Ownership error", f"{lat.get('own_mae', '—')} pts of %",
                help="Average gap between estimated and actual ownership.")
    st.caption(f"Latest slate {card.get('latest_slate')} · season to date ({card['weeks']} weeks): "
               f"{sea.get('proj_mae', '—')} pts error, {sea.get('in_range_pct', '—')}% in range, "
               f"ownership error {sea.get('own_mae', '—')}")
```

Replace `nfldfs_app/view_recommended.py`:

```python
"""⭐ Recommended tab: the contest's best lineup, alternates, outlier swaps, report card."""
from __future__ import annotations

import streamlit as st

from nfldfs.config import CONTEST_TYPES, SALARY_CAP
from nfldfs.dk_rules import upload_csv_text
from nfldfs_app import ui
from nfldfs_app.scoring import published_metric


def stack_summary(lu) -> str:
    qbs = lu[lu["position"] == "QB"]
    if qbs.empty:
        return ""
    qb = qbs.iloc[0]
    mates = lu[(lu["team"] == qb["team"]) & lu["position"].isin(["WR", "TE"])]["name"].tolist()
    back = lu[(lu["team"] == qb["opp"]) & lu["position"].isin(["RB", "WR", "TE"])]["name"].tolist()
    if not mates:
        return f"No QB stack ({qb['name']} alone)"
    return f"Stack: {qb['name']} + {', '.join(mates)}" + (f" · bring-back: {', '.join(back)}" if back else "")


def apply_swap(rec_ids, out_id, in_id) -> tuple[list[int], int]:
    ids = [int(i) for i in rec_ids]
    slot = ids.index(int(out_id))
    ids[slot] = int(in_id)
    return ids, slot


def render(d, key, label, field_scores):
    contest = CONTEST_TYPES[key]
    rec = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)]
    ids = rec.dk_id.astype(int).tolist()
    total = int(rec.salary.sum())
    m = st.columns(4)
    m[0].metric("Salary used", ui.money(total), f"{ui.money(SALARY_CAP - total)} left", delta_color="off")
    m[1].metric("Projected median", f"{rec['median'].sum():.1f}")
    m[2].metric("Ceiling (p85 sum)", f"{rec['ceiling'].sum():.1f}")
    m[3].metric(f"{ui.metric_phrase(key, contest['group'])} in",
                f"{published_metric(d, ids, key, field_scores):.0%} of sims", help=ui.MODEL_RELATIVE_HELP)
    st.dataframe(ui.styled_lineup(rec), hide_index=True, width="stretch")
    st.caption(stack_summary(rec))
    st.download_button("⬇ Download DraftKings upload CSV", upload_csv_text([rec]), file_name=f"dk_upload_{key}.csv",
                       mime="text/csv", key=f"dl_{key}")

    with st.expander("Alternates (#2 and #3)"):
        for r in (1, 2):
            alt = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == r)]
            if alt.empty:
                continue
            st.markdown(f"**#{r + 1}** — {ui.money(alt.total_salary.iloc[0]).replace('$', chr(92) + '$')} · "
                        f"{ui.metric_phrase(key, contest['group']).lower()} in "
                        f"{published_metric(d, alt.dk_id.astype(int).tolist(), key, field_scores):.0%} of sims")
            st.dataframe(ui.styled_lineup(alt), hide_index=True, width="stretch")

    st.subheader("💎 Outliers — swaps that keep you under the cap")
    sw = d.swaps[d.swaps.contest_key == key]
    if sw.empty:
        st.caption("No cap-safe swaps for this lineup.")
    by_id = d.pool.set_index("dk_id")
    for i, s in enumerate(sw.itertuples(index=False)):
        c = st.columns([7, 1], vertical_alignment="center")
        c[0].markdown(ui.swap_line(s, by_id), unsafe_allow_html=True)
        if c[1].button("Apply", key=f"apply_{key}_{i}"):
            new_ids, slot = apply_swap(ids, s.out_dk_id, s.in_dk_id)
            st.session_state.my_ids = new_ids
            st.session_state.focus_slot = slot
            st.session_state.focus_token = st.session_state.get("focus_token", 0) + 1
            st.toast("Swap copied into 🛠 My Lineup — open that tab.")

    with st.expander("📈 Report card — projections vs. actual results"):
        ui.report_card_widget(d.report_card)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_view_recommended.py tests/test_app_smoke.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nfldfs_app/view_recommended.py nfldfs_app/ui.py tests/test_view_recommended.py
git commit -m "Add the Recommended tab with matchups, outliers and report card" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 8: 🛠 My Lineup — interactive builder component + tab

**Files:**
- Create: `nfldfs_app/builder_component.py` (verbatim below — proven in the approved prototype), `tests/test_view_builder.py`
- Modify: `nfldfs_app/view_builder.py` (replace stub)

**Interfaces:**
- Consumes: session keys from Task 7 (`my_ids`, `focus_slot`, `focus_token`); `scoring.published_metric`; `dk_rules.ROSTER_SLOTS, upload_csv_text, validate_lineup`.
- Produces: `builder_component.lineup_builder` (components v2 mount; data keys `pool, lineup, slots, cap, focus_slot, focus_token`; state value `lineup = {"ids": [...9], "t": ms}`); `view_builder.BUILDER_FIELDS`; `builder_records(pool, weights) -> list[dict]`; `apply_builder_value(value, seen, current) -> (new_ids | None, new_seen)`; `lineup_status(ids, pool) -> {"picked", "used", "valid", "messages"}`; `render(d, key, label, field_scores)`. Env `NFLDFS_NO_COMPONENT=1` skips mounting the component (tests).

- [ ] **Step 1: Create `nfldfs_app/builder_component.py` exactly as follows**

```python
"""My Lineup builder — a Streamlit components v2 custom component.

Left: the 9 lineup slots. Right: the whole playable pool. Swap by clicking a slot then a player, a player
then a slot, or dragging a player onto a slot. Every change is sent back to Python as the state value
`lineup` = {"ids": [9 dk_ids or null], "t": timestamp}."""
import streamlit as st

HTML = '<div id="lb"></div>'

CSS = """
#lb { --bg2: var(--st-secondary-background-color, #262730); --fg: var(--st-text-color, #fafafa);
      --muted: color-mix(in srgb, var(--fg) 55%, transparent); --line: color-mix(in srgb, var(--fg) 14%, transparent);
      --accent: var(--st-primary-color, #ff4b4b); --ok: #21c354; --bad: #ff6b6b;
      font-family: var(--st-font, "Source Sans Pro", sans-serif); color: var(--fg); font-size: 14px; }
.lb { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 760px) { .lb { grid-template-columns: 1fr; } }
.hdr { display: flex; justify-content: space-between; align-items: baseline; margin: 0 0 8px; gap: 8px; flex-wrap: wrap; }
.hdr b { font-size: 15px; }
.cap { color: var(--muted); font-size: 13px; } .cap.over { color: var(--bad); font-weight: 600; }
.slot { display: grid; grid-template-columns: 48px 1fr auto; align-items: center; gap: 8px; padding: 8px 10px;
        margin-bottom: 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg2);
        cursor: pointer; transition: opacity .12s, border-color .12s; min-height: 44px; }
.slot .pos { font-weight: 700; font-size: 12px; color: var(--muted); }
.slot .nm { font-weight: 600; } .slot .meta { color: var(--muted); font-size: 12px; }
.slot.empty .nm { color: var(--muted); font-style: italic; font-weight: 400; }
.slot.sel, .pr.sel { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.slot.target { border-color: var(--ok); border-style: dashed; }
.slot.dropover { background: color-mix(in srgb, var(--ok) 18%, var(--bg2)); }
.dim { opacity: .28; pointer-events: none; }
.x { background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.x:hover { color: var(--bad); }
.hint { color: var(--muted); font-size: 12px; margin-top: 6px; min-height: 16px; }
.bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.chip { border: 1px solid var(--line); background: transparent; color: var(--fg); border-radius: 999px;
        padding: 3px 11px; font-size: 13px; cursor: pointer; }
.chip.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.ctl { display: flex; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; align-items: center; }
.ctl input[type=search], .ctl select { background: var(--bg2); color: var(--fg); border: 1px solid var(--line);
        border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.ctl input[type=search] { flex: 1; min-width: 120px; }
.ctl label { color: var(--muted); font-size: 13px; display: flex; gap: 4px; align-items: center; }
.list { max-height: 560px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; }
.pr { display: grid; grid-template-columns: 1fr 70px 92px 70px; gap: 8px; align-items: center; padding: 7px 10px;
      border-bottom: 1px solid var(--line); cursor: grab; border-left: 3px solid transparent; }
.pr:last-child { border-bottom: none; }
.pr:hover { background: var(--bg2); }
.pr .nm { font-weight: 600; } .pr .meta, .pr .sub { color: var(--muted); font-size: 12px; }
.pr .num { text-align: right; font-variant-numeric: tabular-nums; }
.pr.inlu { opacity: .45; cursor: default; }
.pr .left.neg { color: var(--bad); }
.tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; border: 1px solid var(--line); margin-left: 4px; }
.colhdr { display: grid; grid-template-columns: 1fr 70px 92px 70px; gap: 8px; padding: 0 10px 4px; color: var(--muted); font-size: 12px; }
.colhdr span:not(:first-child) { text-align: right; }
.mu { color: #fff; font-weight: 600; font-size: 11px; padding: 1px 6px; border-radius: 4px; white-space: nowrap; cursor: help; }
"""

JS = r"""
export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector('#lb');
  if (!root || !data) return;
  const UI = (globalThis.__lbUI ||= { filter: 'ALL', sort: 'score', q: '', afford: true, selSlot: null, selPlayer: null });
  if (data.focus_token != null && data.focus_token !== globalThis.__lbFocusSeen) {   // "Apply" from Outliers
    globalThis.__lbFocusSeen = data.focus_token;
    UI.selSlot = Number.isInteger(data.focus_slot) ? data.focus_slot : null;
    UI.selPlayer = null;
  }
  const SLOTS = data.slots, CAP = data.cap;
  const ELIG = { QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], FLEX: ['RB', 'WR', 'TE'], DST: ['DST'] };
  const pool = data.pool, byId = new Map(pool.map(p => [p.dk_id, p]));
  let lineup = data.lineup.map(v => (v == null ? null : Number(v)));
  const ICON = { Chalk: '🔥 Chalk', Popular: 'Popular', Moderate: 'Moderate', Contrarian: '💎 Contrarian' };
  const money = v => '$' + Math.round(v).toLocaleString();
  const k = v => money(v);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const mu = p => `<span class="mu" style="background:${p.mu_color}" title="${esc(p.mu_text)}">vs ${p.opp} · ${p.mu_label}</span>`;
  const used = () => lineup.reduce((a, id) => a + (id ? byId.get(id).salary : 0), 0);
  const fits = (i, p) => ELIG[SLOTS[i]].includes(p.position);

  function commit() { setStateValue('lineup', { ids: lineup, t: Date.now() }); }
  function place(i, id) {
    const p = byId.get(id);
    if (!p || !fits(i, p)) return;
    const from = lineup.indexOf(id);
    if (from >= 0 && from !== i) {             // moving a lineup player (e.g. RB -> FLEX): swap the two slots
      const other = lineup[i];
      lineup[from] = other != null && fits(from, byId.get(other)) ? other : null;
    }
    lineup[i] = id;
    UI.selSlot = null; UI.selPlayer = null;
    render(); commit();
  }

  function shell() {
    root.innerHTML = `
      <div class="lb">
        <div><div class="hdr"><b>Your lineup</b><span class="cap" id="cap"></span></div>
          <div id="slots"></div><div class="hint" id="hint"></div></div>
        <div><div class="hdr"><b>Player pool</b><span class="cap" id="cnt"></span></div>
          <div class="bar" id="chips"></div>
          <div class="ctl">
            <input type="search" id="q" placeholder="Search player or team">
            <select id="sort">
              <option value="score">Rank: Recommended</option><option value="median">Rank: Expected points</option>
              <option value="ceiling">Rank: Ceiling (upside)</option><option value="price_desc">Rank: Price high → low</option>
              <option value="price_asc">Rank: Price low → high</option><option value="value">Rank: Value (pts / $1K)</option>
              <option value="own">Rank: Ownership low → high</option>
            </select>
            <label><input type="checkbox" id="afford"> Only what I can afford</label>
          </div>
          <div class="colhdr"><span>Player</span><span>Salary</span><span>Median / Ceil</span><span>Own</span></div>
          <div class="list" id="list"></div></div>
      </div>`;
    root.querySelector('#chips').innerHTML = ['ALL', 'QB', 'RB', 'WR', 'TE', 'FLEX', 'DST']
      .map(f => `<button class="chip" data-f="${f}">${f === 'ALL' ? 'All' : f}</button>`).join('');
    const q = root.querySelector('#q'); q.value = UI.q;
    q.oninput = () => { UI.q = q.value; renderList(); };
    const sort = root.querySelector('#sort'); sort.value = UI.sort;
    sort.onchange = () => { UI.sort = sort.value; renderList(); };
    const af = root.querySelector('#afford'); af.checked = UI.afford;
    af.onchange = () => { UI.afford = af.checked; renderList(); };
  }

  function renderSlots() {
    const u = used(), sp = UI.selPlayer != null ? byId.get(UI.selPlayer) : null;
    const cap = root.querySelector('#cap');
    cap.textContent = `${money(u)} / ${money(CAP)} · ${u <= CAP ? money(CAP - u) + ' left' : money(u - CAP) + ' over'}`;
    cap.className = 'cap' + (u > CAP ? ' over' : '');
    root.querySelector('#slots').innerHTML = SLOTS.map((s, i) => {
      const id = lineup[i], p = id ? byId.get(id) : null;
      const cls = ['slot', p ? '' : 'empty', UI.selSlot === i ? 'sel' : '',
                   sp ? (fits(i, sp) ? 'target' : 'dim') : ''].join(' ');
      const body = p ? `<div><div class="nm">${esc(p.name)}</div><div class="meta">${p.team} ${mu(p)} · ${k(p.salary)} · ${p.median.toFixed(1)} pts · ${ICON[p.tier]}</div></div>`
                     : `<div class="nm">— empty — drop or pick a ${s === 'FLEX' ? 'RB/WR/TE' : s}</div>`;
      return `<div class="${cls}" data-i="${i}"><span class="pos">${s}</span>${body}${p ? `<button class="x" data-rm="${i}" title="Remove">×</button>` : '<span></span>'}</div>`;
    }).join('');
    const hint = root.querySelector('#hint');
    hint.textContent = sp ? `Click a highlighted slot (or drag) to put ${sp.name} in. Gray slots can't take a ${sp.position}.`
      : UI.selSlot != null ? `Pick a player on the right for ${SLOTS[UI.selSlot]} — ineligible players are grayed out.`
      : 'Click a slot or a player to start, or drag a player onto a slot.';
    root.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c.dataset.f === activeFilter()));
  }

  function activeFilter() { return UI.selSlot != null ? (SLOTS[UI.selSlot] === 'FLEX' ? 'FLEX' : SLOTS[UI.selSlot]) : UI.filter; }

  function renderList() {
    const f = activeFilter(), q = UI.q.trim().toLowerCase(), u = used();
    const selSlot = UI.selSlot, curSal = selSlot != null && lineup[selSlot] ? byId.get(lineup[selSlot]).salary : 0;
    let rows = pool.filter(p => (f === 'ALL' || (f === 'FLEX' ? ELIG.FLEX : [f]).includes(p.position))
      && (!q || (p.name + ' ' + p.team).toLowerCase().includes(q)));
    const leftAfter = p => CAP - (u - curSal) - p.salary;
    if (UI.afford && selSlot != null) rows = rows.filter(p => leftAfter(p) >= 0 || lineup.includes(p.dk_id));
    const key = { score: p => -p.score, median: p => -p.median, ceiling: p => -p.ceiling, price_desc: p => -p.salary,
                  price_asc: p => p.salary, value: p => -p.value, own: p => p.own_pct }[UI.sort];
    rows.sort((a, b) => key(a) - key(b));
    root.querySelector('#cnt').textContent = `${rows.length} players`;
    root.querySelector('#list').innerHTML = rows.map(p => {
      const inlu = lineup.includes(p.dk_id);
      const dim = selSlot != null && !fits(selSlot, p);
      const la = leftAfter(p);
      const cls = ['pr', inlu ? 'inlu' : '', dim ? 'dim' : '', UI.selPlayer === p.dk_id ? 'sel' : ''].join(' ');
      const after = selSlot != null && !inlu ? `<div class="sub left ${la < 0 ? 'neg' : ''}">${la < 0 ? money(-la) + ' over' : money(la) + ' left'}</div>` : '';
      return `<div class="${cls}" data-id="${p.dk_id}" draggable="${!inlu}">
        <div><div class="nm">${esc(p.name)}${inlu ? '<span class="tag">in lineup</span>' : ''}</div>
             <div class="meta">${p.position} · ${p.team} ${mu(p)}</div></div>
        <div class="num">${k(p.salary)}${after}</div>
        <div class="num">${p.median.toFixed(1)} / ${p.ceiling.toFixed(1)}<div class="sub">${p.value.toFixed(2)} pts/$1K</div></div>
        <div class="num">${p.own_pct.toFixed(0)}%<div class="sub">${ICON[p.tier]}</div></div></div>`;
    }).join('') || '<div class="pr"><div class="meta">No players match.</div></div>';
  }

  function render() { renderSlots(); renderList(); }

  shell(); render();

  root.onclick = (e) => {
    const rm = e.target.closest('[data-rm]');
    if (rm) { lineup[+rm.dataset.rm] = null; UI.selSlot = null; render(); commit(); return; }
    const chip = e.target.closest('.chip');
    if (chip) { UI.filter = chip.dataset.f; UI.selSlot = null; render(); return; }
    const slot = e.target.closest('.slot');
    if (slot) {
      const i = +slot.dataset.i;
      if (UI.selPlayer != null) { place(i, UI.selPlayer); return; }
      UI.selSlot = UI.selSlot === i ? null : i; UI.selPlayer = null; render(); return;
    }
    const pr = e.target.closest('.pr[data-id]');
    if (pr && !pr.classList.contains('inlu')) {
      const id = +pr.dataset.id;
      if (UI.selSlot != null) { place(UI.selSlot, id); return; }
      UI.selPlayer = UI.selPlayer === id ? null : id; render();
    }
  };
  root.onkeydown = (e) => { if (e.key === 'Escape') { UI.selSlot = null; UI.selPlayer = null; render(); } };
  root.ondragstart = (e) => {
    const pr = e.target.closest('.pr[data-id]'); if (!pr) return;
    e.dataTransfer.setData('text/plain', pr.dataset.id); e.dataTransfer.effectAllowed = 'move';
    UI.selSlot = null; UI.selPlayer = +pr.dataset.id; renderSlots();
  };
  root.ondragend = () => { if (UI.selPlayer != null) { UI.selPlayer = null; renderSlots(); renderList(); } };
  root.ondragover = (e) => {
    const s = e.target.closest('.slot'); root.querySelectorAll('.dropover').forEach(n => n !== s && n.classList.remove('dropover'));
    if (s && UI.selPlayer != null && fits(+s.dataset.i, byId.get(UI.selPlayer))) { e.preventDefault(); s.classList.add('dropover'); }
  };
  root.ondrop = (e) => {
    const s = e.target.closest('.slot'); if (!s) return; e.preventDefault();
    place(+s.dataset.i, +e.dataTransfer.getData('text/plain'));
  };
}
"""

lineup_builder = st.components.v2.component("nfldfs_lineup_builder", html=HTML, css=CSS, js=JS)
```

- [ ] **Step 2: Write the failing tests** — `tests/test_view_builder.py`:

```python
import pandas as pd

from nfldfs.config import CONTEST_TYPES
from nfldfs_app import data, view_builder


def _d(published_dir):
    return data.load(published_dir)


def _rec_ids(d, key="fifty_fifty"):
    return d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)].dk_id.astype(int).tolist()


def test_builder_records(published_dir):
    d = _d(published_dir)
    w = CONTEST_TYPES["large_tournament"]["weights"]
    recs = view_builder.builder_records(d.pool, w)
    assert len(recs) == int(d.pool.playable.sum())
    r = recs[0]
    assert set(view_builder.BUILDER_FIELDS) <= set(r) and isinstance(r["dk_id"], int)
    row = d.pool.set_index("dk_id").loc[r["dk_id"]]
    assert abs(r["score"] - (row.ceiling - 0.30 * row.own_pct)) < 1e-2


def test_apply_builder_value():
    cur = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert view_builder.apply_builder_value(None, None, cur) == (None, None)
    v = {"ids": [1, 2, 3, 4, 5, 6, 7, 8, 10], "t": 1}
    new, seen = view_builder.apply_builder_value(v, None, cur)
    assert new == [1, 2, 3, 4, 5, 6, 7, 8, 10] and seen == v
    assert view_builder.apply_builder_value(v, v, cur) == (None, v)               # already applied
    same = {"ids": cur, "t": 2}
    assert view_builder.apply_builder_value(same, v, cur) == (None, same)


def test_lineup_status_valid_and_errors(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    ok = view_builder.lineup_status(ids, d.pool)
    assert ok["valid"] and ok["messages"] == [] and ok["used"] <= 50_000
    empty = view_builder.lineup_status([None] * 9, d.pool)
    assert not empty["valid"] and "9 slot(s) still empty." in empty["messages"]
    dup = view_builder.lineup_status(ids[:8] + [ids[0]], d.pool)
    assert not dup["valid"]


def test_lineup_status_flags_out_player(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    pool = d.pool.copy()
    pool.loc[pool.dk_id == ids[1], "playable"] = False
    st = view_builder.lineup_status(ids, pool)
    assert not st["valid"] and any("ruled out" in m for m in st["messages"])


def test_lineup_status_over_cap(published_dir):
    d = _d(published_dir)
    ids = _rec_ids(d)
    pool = d.pool.copy()
    pool.loc[pool.dk_id == ids[0], "salary"] += 20_000
    st = view_builder.lineup_status(ids, pool)
    assert not st["valid"] and any("Over the cap" in m for m in st["messages"])


def test_my_lineup_tab_defaults_and_load_blank(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    d = _d(published_dir)
    assert at.session_state["my_ids"] == _rec_ids(d, "single_entry")
    at.selectbox(key="builder_start").set_value("Blank lineup").run()
    at.button(key="builder_load").click().run()
    assert at.session_state["my_ids"] == [None] * 9 and not at.exception
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./py -m pytest tests/test_view_builder.py -v`
Expected: FAIL (functions missing; stub tab).

- [ ] **Step 4: Implement `nfldfs_app/view_builder.py`**

```python
"""🛠 My Lineup tab: live totals, the interactive builder component, export."""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from nfldfs.config import CONTEST_TYPES, SALARY_CAP
from nfldfs.dk_rules import ROSTER_SLOTS, upload_csv_text, validate_lineup
from nfldfs_app import ui
from nfldfs_app.scoring import published_metric

BUILDER_FIELDS = ["dk_id", "name", "position", "team", "opp", "salary", "median", "ceiling", "own_pct", "tier",
                  "score", "value", "mu_color", "mu_text", "mu_label"]


def builder_records(pool: pd.DataFrame, weights: dict) -> list[dict]:
    play = pool[pool["playable"]].copy()
    play["score"] = (weights.get("floor", 0) * play["floor"] + weights.get("median", 0) * play["median"]
                     + weights.get("ceiling", 0) * play["ceiling"] - weights.get("own_penalty", 0) * play["own_pct"])
    play["value"] = play["median"] / (play["salary"] / 1000)
    recs = play[BUILDER_FIELDS].round(3).to_dict("records")
    for r in recs:
        r["dk_id"], r["salary"] = int(r["dk_id"]), int(r["salary"])
    return recs


def apply_builder_value(value, seen, current):
    """The component reports its whole lineup; apply it only when it is a new user action."""
    if not value or value == seen:
        return None, seen
    new = [None if v is None else int(v) for v in value["ids"]]
    return (new if new != list(current) else None), value


def lineup_status(ids, pool: pd.DataFrame) -> dict:
    by = pool.set_index("dk_id")
    picked = [int(i) for i in ids if i is not None]
    gone = [i for i in picked if i not in by.index]
    known = [i for i in picked if i in by.index]
    out = [by.at[i, "name"] for i in known if not bool(by.at[i, "playable"])]
    used = int(by.loc[known, "salary"].sum()) if known else 0
    dupes = len(set(picked)) != len(picked)
    messages = [f"⚠ {n} is now ruled out — swap him before lock." for n in out]
    if gone:
        messages.append("⚠ A player in this lineup is no longer on the slate — swap him.")
    if dupes:
        messages.append("⚠ The same player is in two slots.")
    if used > SALARY_CAP:
        messages.append(f"Over the cap by {ui.money(used - SALARY_CAP)} — export disabled.")
    if len(picked) < 9:
        messages.append(f"{9 - len(picked)} slot(s) still empty.")
    valid = (len(picked) == 9 and not gone and not out and not dupes
             and validate_lineup(by.loc[known].reset_index()) == [])
    return {"picked": picked, "used": used, "valid": valid, "messages": messages}


def render(d, key, label, field_scores):
    contest = CONTEST_TYPES[key]
    keys = list(CONTEST_TYPES)
    labels = [CONTEST_TYPES[k]["label"] for k in keys]
    rec_of = lambda k: d.lineups[(d.lineups.contest_key == k) & (d.lineups["rank"] == 0)].dk_id.astype(int).tolist()
    rec_ids = rec_of(key)
    if "my_ids" not in st.session_state:
        st.session_state.my_ids = rec_ids

    t = st.columns([3, 1, 4], vertical_alignment="bottom")
    start = t[0].selectbox("Start from", ["Blank lineup"] + labels, index=1 + keys.index(key), key="builder_start")
    if t[1].button("Load", width="stretch", key="builder_load"):
        st.session_state.my_ids = [None] * 9 if start == "Blank lineup" else rec_of(keys[labels.index(start)])
        st.session_state.pop("focus_slot", None)
        st.rerun()

    ids = list(st.session_state.my_ids)
    status = lineup_status(ids, d.pool)
    by = d.pool.set_index("dk_id")
    known = [i for i in status["picked"] if i in by.index]
    used = status["used"]
    m = st.columns(4)
    m[0].metric("Salary used", ui.money(used),
                f"{ui.money(SALARY_CAP - used)} left" if used <= SALARY_CAP else f"-{ui.money(used - SALARY_CAP)} over",
                delta_color="normal")
    m[1].metric("Projected median", f"{by.loc[known, 'median'].sum():.1f}")
    m[2].metric("Ceiling (p85 sum)", f"{by.loc[known, 'ceiling'].sum():.1f}")
    if status["valid"]:
        mine = published_metric(d, status["picked"], key, field_scores)
        recm = published_metric(d, rec_ids, key, field_scores)
        m[3].metric(f"{ui.metric_phrase(key, contest['group'])} in", f"{mine:.0%} of sims", f"recommended: {recm:.0%}",
                    delta_color="off", help=ui.MODEL_RELATIVE_HELP)
    for msg in status["messages"]:
        (st.error if msg.startswith("⚠") or msg.startswith("Over the cap") else st.info)(msg)
    st.caption(f"“Recommended” ranking = best fit for **{label}**. Click a slot then a player (or a player then a "
               "slot), or drag a player onto a slot. Gray = not eligible. Esc clears a selection.")

    value = None
    if os.environ.get("NFLDFS_NO_COMPONENT") == "1":
        st.info("Interactive builder is off in test mode.")
    else:
        from nfldfs_app.builder_component import lineup_builder
        res = lineup_builder(key="builder", on_lineup_change=lambda: None, data={
            "pool": builder_records(d.pool, contest["weights"]), "lineup": ids, "slots": list(ROSTER_SLOTS),
            "cap": SALARY_CAP, "focus_slot": st.session_state.get("focus_slot"),
            "focus_token": st.session_state.get("focus_token")})
        value = getattr(res, "lineup", None)
    new, st.session_state.lb_seen = apply_builder_value(value, st.session_state.get("lb_seen"), ids)
    if new is not None:
        st.session_state.my_ids = new
        st.rerun()

    csv = upload_csv_text([by.loc[status["picked"]].reset_index()]) if status["valid"] else ""
    st.download_button("⬇ Download My Lineup (DraftKings CSV)", csv, file_name="dk_upload_my_lineup.csv",
                       mime="text/csv", disabled=not status["valid"], key="dl_mine")
    if status["valid"]:
        with st.expander("Side by side with the recommended lineup"):
            rec = d.lineups[(d.lineups.contest_key == key) & (d.lineups["rank"] == 0)].reset_index(drop=True)
            mine = by.loc[status["picked"]].reset_index()
            st.dataframe(pd.DataFrame({
                "Pos": rec["slot"], "Recommended": rec["name"], "Salary": rec["salary"].map(ui.money),
                "Median": rec["median"].round(1), "My pick": mine["name"], "My salary": mine["salary"].map(ui.money),
                "My median": mine["median"].round(1)}), hide_index=True, width="stretch")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_view_builder.py tests/test_app_smoke.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add nfldfs_app/builder_component.py nfldfs_app/view_builder.py tests/test_view_builder.py
git commit -m "Add the interactive My Lineup builder (click-to-swap both ways + drag and drop)" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

- [ ] **Step 7: Browser verification (controller — the component's JavaScript can't run under AppTest)**

Start the real app (`./launch.sh` exists only after Task 11; until then run `/Library/Frameworks/Python.framework/Versions/3.14/bin/streamlit run app.py --server.headless true --server.port 8502`), open http://localhost:8502 → 🛠 My Lineup, and confirm, as in the approved prototype: (1) click RB slot → pool filters to RBs, others gray, click a player → swapped and totals update; (2) click a TE in the pool → only TE and FLEX slots stay active, click FLEX → placed; (3) drag a WR onto a WR slot → swapped; (4) over-cap turns the salary bar red and disables download; (5) Recommended → **Apply** on an outlier, then My Lineup opens with that slot selected; (6) server log shows no errors. Record results in the task report; any failure goes back to the implementer as a finding.

---

### Task 9: 📋 Player pool + locks/excludes + Rebuild

**Files:**
- Modify: `nfldfs_app/view_pool.py` (replace stub)
- Create: `tests/test_view_pool.py`

**Interfaces:**
- Consumes: `lineups.best_lineup`, `optimizer.InfeasibleError`, `dk_rules.assign_slots, ROSTER_SLOTS`, `ui.styled_pool/styled_lineup`.
- Produces: `view_pool.SORTS`; `pool_view(pool, positions, tiers, sort_label) -> DataFrame` (playable only, adds `value`, sorted descending); `rebuild(d, key, locks, excludes) -> (lineup_df with slot column in DK order, metric)`; `render(d, key, label, field_scores)`; session key `rebuilt = {"key", "ids", "metric"}`; **Send to 🛠 My Lineup** sets `my_ids`.

- [ ] **Step 1: Write the failing tests** — `tests/test_view_pool.py`:

```python
import pytest

from nfldfs import dk_rules
from nfldfs.optimizer import InfeasibleError
from nfldfs_app import data, view_pool


def test_pool_view_filters_and_sorts(published_dir):
    d = data.load(published_dir)
    v = view_pool.pool_view(d.pool, ["WR", "TE"], ["Chalk", "Popular", "Moderate", "Contrarian"], "Ceiling")
    assert set(v.position) <= {"WR", "TE"} and v.playable.all()
    assert v.ceiling.is_monotonic_decreasing and "value" in v.columns


def test_rebuild_respects_locks(published_dir):
    d = data.load(published_dir)
    lock = int(d.pool[(d.pool.position == "TE") & d.pool.playable].sort_values("salary").dk_id.iloc[0])
    lu, metric = view_pool.rebuild(d, "tournament", [lock], [])
    assert dk_rules.validate_lineup(lu) == [] and lock in lu.dk_id.tolist() and 0 <= metric <= 1
    assert list(lu.slot) == list(dk_rules.ROSTER_SLOTS)


def test_rebuild_impossible_locks_raise(published_dir):
    d = data.load(published_dir)
    qbs = d.pool[(d.pool.position == "QB") & d.pool.playable].dk_id.astype(int).tolist()[:2]
    with pytest.raises(InfeasibleError):
        view_pool.rebuild(d, "tournament", qbs, [])                     # two QBs can't both fit


def test_pool_tab_renders(make_app, published_dir):
    at = make_app(published_dir)
    assert not at.exception
    assert at.multiselect(key="pool_locks") is not None and at.button(key="pool_rebuild").disabled
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_view_pool.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `nfldfs_app/view_pool.py`**

```python
"""📋 Player pool tab: every playable player, locks/excludes, and Rebuild with my locks."""
from __future__ import annotations

import streamlit as st

from nfldfs import lineups
from nfldfs.config import CONTEST_TYPES
from nfldfs.dk_rules import ROSTER_SLOTS, assign_slots
from nfldfs.optimizer import InfeasibleError
from nfldfs_app import ui

SORTS = {"Median": "median", "Ceiling": "ceiling", "Boom %": "boom_rate", "Value (pts/$1K)": "value",
         "Ownership": "own_pct", "Salary": "salary"}
POSITIONS = ["QB", "RB", "WR", "TE", "DST"]


def pool_view(pool, positions, tiers, sort_label):
    v = pool[pool["playable"] & pool["position"].isin(positions) & pool["tier"].isin(tiers)].copy()
    v["value"] = v["median"] / (v["salary"] / 1000)
    return v.sort_values(SORTS[sort_label], ascending=False, kind="stable").reset_index(drop=True)


def rebuild(d, key, locks, excludes):
    rows, metric = lineups.best_lineup(d.pool, d.sims, d.field, CONTEST_TYPES[key], locks=locks, excludes=excludes)
    lu = d.pool.loc[rows]
    order = assign_slots(lu)
    lu = lu.set_index("dk_id").loc[order].reset_index()
    lu.insert(0, "slot", list(ROSTER_SLOTS))
    return lu, metric


def render(d, key, label, field_scores):
    f = st.columns(3)
    pos = f[0].multiselect("Position", POSITIONS, default=POSITIONS, key="pool_pos")
    tiers = f[1].multiselect("Ownership tier", list(ui.TIER_ICON), default=list(ui.TIER_ICON), key="pool_tiers")
    sort = f[2].selectbox("Sort by", list(SORTS), key="pool_sort")
    st.dataframe(ui.styled_pool(pool_view(d.pool, pos, tiers, sort)), hide_index=True, width="stretch", height=480)

    play = d.pool[d.pool["playable"]].sort_values("salary", ascending=False)
    names = {f"{r['name']} · {r.position} · {r.team} · {ui.money(r.salary)}": int(r.dk_id) for _, r in play.iterrows()}
    c = st.columns(2)
    locks = [names[n] for n in c[0].multiselect("🔒 Lock players (must be in the lineup)", list(names), key="pool_locks")]
    excl = [names[n] for n in c[1].multiselect("✖ Exclude players", list(names), key="pool_excludes")]
    if st.button(f"🔁 Rebuild {label} lineup with my locks", disabled=not (locks or excl), key="pool_rebuild"):
        try:
            with st.spinner("Building…"):
                lu, metric = rebuild(d, key, locks, excl)
            st.session_state.rebuilt = {"key": key, "ids": lu.dk_id.astype(int).tolist(), "metric": metric}
        except InfeasibleError as e:
            st.error(str(e))
    rb = st.session_state.get("rebuilt")
    if rb and rb["key"] == key:
        lu = d.pool.set_index("dk_id").loc[rb["ids"]].reset_index()
        lu.insert(0, "slot", list(ROSTER_SLOTS))
        st.markdown(f"**Rebuilt lineup** — {ui.metric_phrase(key, CONTEST_TYPES[key]['group']).lower()} in "
                    f"{rb['metric']:.0%} of sims")
        st.dataframe(ui.styled_lineup(lu), hide_index=True, width="stretch")
        if st.button("Send to 🛠 My Lineup", key="pool_send"):
            st.session_state.my_ids = rb["ids"]
            st.toast("Copied into 🛠 My Lineup")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_view_pool.py tests/test_app_smoke.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nfldfs_app/view_pool.py tests/test_view_pool.py
git commit -m "Add the Player pool tab with locks, excludes and rebuild" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 10: Sidebar — status, import guide, local actions

**Files:**
- Modify: `nfldfs_app/view_sidebar.py` (replace stub)
- Create: `tests/test_view_sidebar.py`

**Interfaces:**
- Consumes: `actions.run_stage/save_upload`, `config.RAW`, `AppData`.
- Produces: `view_sidebar.IMPORT_GUIDE` (markdown; final DraftKings wording set in Task 13), `results_message(results_status) -> str | None`, `render(d, hosted)`. Widget keys: `check_results`, `up_results`, `import_upload`, `up_salaries`, `use_salaries`. Local actions set `st.session_state.flash = (ok, tail)` and rerun (shown by `app.py`).

- [ ] **Step 1: Write the failing tests** — `tests/test_view_sidebar.py`:

```python
from types import SimpleNamespace

from nfldfs_app import actions, view_sidebar


def test_results_message():
    assert view_sidebar.results_message({}) is None
    s = {"finished": "2026-10-19T09:01:00", "steps": [{"name": "results", "ok": True,
                                                      "message": "imported 1 file(s) for the 2026-10-18 slate"}]}
    assert view_sidebar.results_message(s).startswith("✅ imported 1 file(s)")
    bad = {"steps": [{"name": "results", "ok": False, "message": "ValueError: not a standings file"}]}
    assert view_sidebar.results_message(bad).startswith("⚠")


def test_save_upload(tmp_path):
    up = SimpleNamespace(name="../../contest-standings-1.zip", getvalue=lambda: b"PK")
    p = actions.save_upload(up, tmp_path / "inbox")
    assert p == tmp_path / "inbox" / "contest-standings-1.zip" and p.read_bytes() == b"PK"


def test_sidebar_actions_disabled_when_hosted(make_app, published_dir):
    at = make_app(published_dir, hosted="1")
    assert at.sidebar.button(key="check_results").disabled


def test_check_results_runs_stage_locally(make_app, published_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "run_stage", lambda *a: calls.append(a) or (True, "imported 1 file(s)"))
    at = make_app(published_dir, hosted="0")
    at.sidebar.button(key="check_results").click().run()
    assert calls == [("results",)] and not at.exception
    assert any("imported 1 file" in s.value for s in at.success)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_view_sidebar.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `nfldfs_app/view_sidebar.py`**

```python
"""Sidebar: slate status, accuracy, results-import guide and local-only actions."""
from __future__ import annotations

import streamlit as st

from nfldfs import config
from nfldfs_app import actions

# Plain-language steps. Final DraftKings button names are confirmed from Nathan's screenshots (Task 13).
IMPORT_GUIDE = """
1. On a **computer** (not the phone app), open **draftkings.com** and sign in as usual.
2. At the top, click **My Contests**.
3. Click the tab for **completed** contests.
4. Click last Sunday's contest to open it.
5. Next to the standings, click **Export** once.
6. A file named like `contest-standings-123456789.zip` downloads to your **Downloads** folder. Don't open,
   rename or move it.
7. That's it — your Mac imports it within a minute (or click **Check for results** below) and files it away.
8. You'll see **✅ imported …** here. The 📈 Report card on the Recommended tab updates after that.

**If nothing happens:** drag the zip file into **Upload results** below and click **Import**.
"""


def results_message(results_status: dict) -> str | None:
    steps = results_status.get("steps") or []
    if not steps:
        return None
    s = steps[0]
    return (f"✅ {s['message']}" if s.get("ok") else f"⚠ Results import failed: {s.get('message', '')}")


def _run(stage: str, *extra: str) -> None:
    with st.spinner("Working…"):
        st.session_state.flash = actions.run_stage(stage, *extra)
    st.cache_resource.clear()
    st.rerun()


def render(d, hosted: bool) -> None:
    with st.sidebar:
        st.markdown("### 🏈 NFL DFS")
        st.metric("Slate", f"{d.meta.get('game_count', '?')} games")
        st.caption(f"Built {str(d.meta.get('built_at', ''))[:16].replace('T', ' ')} · "
                   f"{d.meta.get('n_sims', 0):,} sims · name match {d.meta.get('match_rate', 0):.0%} · "
                   f"Odds API left: {d.meta.get('odds_requests_remaining', '?')}")
        sea = d.report_card.get("season") if d.report_card.get("weeks") else None
        if sea:
            st.caption(f"Season accuracy: {sea.get('proj_mae', '—')} pts avg error · "
                       f"{sea.get('in_range_pct', '—')}% inside floor–ceiling")
        st.divider()
        with st.expander("📥 How to import last week's results"):
            st.markdown(IMPORT_GUIDE)
        msg = results_message(d.results_status)
        if msg:
            st.caption(msg)
        if hosted:
            st.caption("Importing results and uploading files work in the app on your Mac.")
        if st.button("Check for results", disabled=hosted, key="check_results", width="stretch"):
            _run("results")
        up = st.file_uploader("Upload results (fallback)", type=["zip", "csv"], disabled=hosted, key="up_results")
        if up is not None and st.button("Import", key="import_upload", disabled=hosted):
            _run("results", "--results-file", str(actions.save_upload(up, config.RAW / "standings_inbox")))
        sal = st.file_uploader("Upload DKSalaries.csv (fallback)", type=["csv"], disabled=hosted, key="up_salaries")
        if sal is not None and st.button("Rebuild with this salary file", key="use_salaries", disabled=hosted):
            _run("refresh", "--salary-csv", str(actions.save_upload(sal, config.RAW / "manual")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_view_sidebar.py tests/test_app_smoke.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add nfldfs_app/view_sidebar.py tests/test_view_sidebar.py
git commit -m "Add the sidebar: status, results import guide and local actions" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 11: Weekly schedule on the Mac + local launcher

**Files:**
- Create: `scripts/run_stage.sh`, `scripts/install_schedule.sh`, `scripts/uninstall_schedule.sh`, `scripts/make_desktop_launcher.sh`, `scripts/launchagents/com.nfldfs.{tuesday,thursday,sunday,sunday_late,results}.plist.template`, `launch.sh`, `tests/test_schedule_files.py`

**Interfaces:**
- Produces: LaunchAgents (after install) — Tue 9:00 `tuesday`; Thu 9:00 `thursday`; Sun 9:00 `sunday` (keeps the Mac awake ~3h15m); Sun 11:45 `sunday_late`; `results` whenever `~/Downloads` changes. Logs: `logs/launchagent.log`, `logs/pipeline.log`, `logs/streamlit.log`. Local app on http://localhost:8502.

- [ ] **Step 1: Write the failing tests** — `tests/test_schedule_files.py`:

```python
import plistlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "scripts" / "launchagents"
EXPECTED = {"tuesday": (2, 9, 0), "thursday": (4, 9, 0), "sunday": (0, 9, 0), "sunday_late": (0, 11, 45)}


def _render(name):
    text = (TEMPLATES / f"com.nfldfs.{name}.plist.template").read_text()
    return plistlib.loads(text.replace("__PROJECT__", "/p").replace("__HOME__", "/h").encode())


@pytest.mark.parametrize("name", list(EXPECTED))
def test_calendar_agents(name):
    p = _render(name)
    assert p["Label"] == f"com.nfldfs.{name}"
    assert p["ProgramArguments"] == ["/bin/bash", "/p/scripts/run_stage.sh", name]
    sci = p["StartCalendarInterval"]
    assert (sci["Weekday"], sci["Hour"], sci["Minute"]) == EXPECTED[name]


def test_results_agent_watches_downloads():
    p = _render("results")
    assert p["WatchPaths"] == ["/h/Downloads"] and p["ProgramArguments"][-1] == "results"
    assert "StartCalendarInterval" not in p


@pytest.mark.parametrize("script", ["scripts/run_stage.sh", "scripts/install_schedule.sh",
                                    "scripts/uninstall_schedule.sh", "scripts/make_desktop_launcher.sh", "launch.sh"])
def test_scripts_parse_and_are_executable(script):
    path = ROOT / script
    assert path.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(path)], check=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_schedule_files.py -v`
Expected: FAIL (files missing).

- [ ] **Step 3: Create the scripts and templates**

`scripts/run_stage.sh`:

```bash
#!/bin/bash
# LaunchAgent wrapper: ./scripts/run_stage.sh <stage>
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
LOG="$PROJECT/logs/launchagent.log"
STAGE="$1"
mkdir -p "$PROJECT/logs"
cd "$PROJECT" || exit 1
if [ "$STAGE" = "sunday" ]; then
    # Keep the Mac awake from 9:00 through the 11:45 run (3h15m).
    caffeinate -dims -t 11700 >/dev/null 2>&1 &
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE starting ===" >> "$LOG"
caffeinate -i "$PYTHON" run_pipeline.py --stage "$STAGE" >> "$LOG" 2>&1
RC=$?
echo "[$(date '+%Y-%m-%d %H:%M:%S')] === $STAGE finished (exit $RC) ===" >> "$LOG"
exit $RC
```

Calendar template — create `scripts/launchagents/com.nfldfs.tuesday.plist.template`; the other three calendar templates are identical except the three marked values (`thursday`: Weekday 4, Hour 9, Minute 0; `sunday`: Weekday 0, Hour 9, Minute 0; `sunday_late`: Weekday 0, Hour 11, Minute 45), and the Label/stage name in both places:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nfldfs.tuesday</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>__PROJECT__/scripts/run_stage.sh</string>
        <string>tuesday</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>2</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>__PROJECT__</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

`scripts/launchagents/com.nfldfs.results.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.nfldfs.results</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>__PROJECT__/scripts/run_stage.sh</string>
        <string>results</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>__HOME__/Downloads</string>
    </array>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>WorkingDirectory</key>
    <string>__PROJECT__</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

`scripts/install_schedule.sh`:

```bash
#!/bin/bash
# Installs (or re-installs) the weekly NFL DFS schedule as macOS LaunchAgents.
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$PROJECT/logs"
for tpl in "$PROJECT"/scripts/launchagents/*.plist.template; do
    name="$(basename "$tpl" .template)"
    label="${name%.plist}"
    sed -e "s#__PROJECT__#$PROJECT#g" -e "s#__HOME__#$HOME#g" "$tpl" > "$AGENTS/$name"
    plutil -lint "$AGENTS/$name" >/dev/null
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name"
    echo "installed $label"
done
echo
echo "Last step — lets your Mac wake itself before each run (asks for your Mac password):"
echo "  sudo pmset repeat wakeorpoweron TRU 08:55:00"
```

`scripts/uninstall_schedule.sh`:

```bash
#!/bin/bash
# Removes the NFL DFS LaunchAgents.
AGENTS="$HOME/Library/LaunchAgents"
for f in "$AGENTS"/com.nfldfs.*.plist; do
    [ -e "$f" ] || continue
    launchctl bootout "gui/$(id -u)/$(basename "$f" .plist)" 2>/dev/null || true
    rm -f "$f"
    echo "removed $(basename "$f" .plist)"
done
```

`launch.sh`:

```bash
#!/bin/bash
# Starts the local NFL DFS app on http://localhost:8502 and opens Chrome (data refresh is in the app).
PROJECT="$(cd "$(dirname "$0")" && pwd)"
STREAMLIT="/Library/Frameworks/Python.framework/Versions/3.14/bin/streamlit"
LOG="$PROJECT/logs/streamlit.log"
mkdir -p "$PROJECT/logs"
cd "$PROJECT" || exit 1
pkill -f "streamlit run app.py --server.headless true --server.port 8502" 2>/dev/null || true
sleep 1
nohup caffeinate -i "$STREAMLIT" run app.py --server.headless true --server.port 8502 >> "$LOG" 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if lsof -i :8502 -sTCP:LISTEN >/dev/null 2>&1; then
        open -a "Google Chrome" http://localhost:8502 2>/dev/null || open http://localhost:8502
        echo "NFL DFS app running at http://localhost:8502"
        exit 0
    fi
done
echo "The app didn't start — see $LOG"
tail -20 "$LOG"
exit 1
```

`scripts/make_desktop_launcher.sh`:

```bash
#!/bin/bash
# Creates a double-clickable "Launch NFL DFS" on the Desktop.
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/Desktop/Launch_NFL_DFS.command"
printf '#!/bin/bash\nbash "%s/launch.sh"\n' "$PROJECT" > "$TARGET"
chmod +x "$TARGET"
echo "created $TARGET"
```

Then: `chmod +x scripts/*.sh launch.sh`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_schedule_files.py -v && ./py -m pytest -q -W error`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts launch.sh tests/test_schedule_files.py
git commit -m "Add the weekly LaunchAgent schedule, results watcher and local launcher" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
```

- [ ] **Step 6: Install on Nathan's Mac (controller; Nathan-approval step)**

Ask Nathan before each of these; they change his Mac outside the repo:
1. `bash scripts/install_schedule.sh` → expect 5 "installed com.nfldfs.*" lines; `launchctl list | grep nfldfs` shows 5 labels.
2. `bash scripts/make_desktop_launcher.sh` → `~/Desktop/Launch_NFL_DFS.command`.
3. **Nathan runs** (needs his password): `sudo pmset repeat wakeorpoweron TRU 08:55:00`; then `pmset -g sched` shows the repeating wake. Note: this replaces any existing `pmset repeat` schedule — check `pmset -g sched` first and tell Nathan if one exists.
4. Downloads-access check: `touch ~/Downloads/nfldfs_watch_test.txt && sleep 45 && cat data/published/results_status.json && rm ~/Downloads/nfldfs_watch_test.txt`. Expected message `skipped: no new contest-standings file`. If the message shows `PermissionError`, macOS is blocking the background job from reading Downloads: walk Nathan through **System Settings → Privacy & Security → Full Disk Access → + → press ⌘⇧G → paste `/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app` → Open → turn it on**, then repeat the check.

---

### Task 12: GitHub repo + Streamlit Cloud (hosted copy)

**Files:**
- Create: `.devcontainer/devcontainer.json`
- No code changes otherwise; this task publishes.

- [ ] **Step 1: Codespaces/devcontainer file (same as MLB)** — `.devcontainer/devcontainer.json`:

```json
{
  "name": "Python 3",
  "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
  "customizations": {"codespaces": {"openFiles": ["README.md", "app.py"]},
                     "vscode": {"extensions": ["ms-python.python", "ms-python.vscode-pylance"]}},
  "updateContentCommand": "[ -f requirements.txt ] && pip3 install --user -r requirements.txt; echo '✅ Packages installed'",
  "postAttachCommand": {"server": "streamlit run app.py --server.enableCORS false --server.enableXsrfProtection false"},
  "portsAttributes": {"8501": {"label": "Application", "onAutoForward": "openPreview"}},
  "forwardPorts": [8501]
}
```

Commit: `git add .devcontainer && git commit -m "Add devcontainer for Codespaces" -m "Co-Authored-By: <model> <noreply@anthropic.com>"`.

- [ ] **Step 2: Fix author email on the first 8 commits (local history only, before any push — controller)**

```bash
git rebase -r --root --exec "git commit --amend --no-edit --reset-author --no-verify" && git log --format='%ae' | sort -u
```
Expected: only `nathan.l.tessler@gmail.com`. (Safe: nothing has been pushed yet. Commit messages and Co-Authored-By trailers are unchanged.)

- [ ] **Step 3: Publish the first build (controller)** — `./py run_pipeline.py --stage build && ./py run_pipeline.py --stage results` is NOT needed; instead commit the current published data once: `./py -c "from nfldfs.publish import publish; from nfldfs import config; print(publish(config.ROOT, ['data/published','data/history'], 'First published slate'))"` → `committed locally (no GitHub remote yet)`.

- [ ] **Step 4: Nathan creates the GitHub repo (Nathan does this; exact clicks)**
1. Open **github.com** and sign in as **natergater24**.
2. Top-right **+** → **New repository**.
3. Repository name: `nfl-dfs-optimizer`. Visibility: **Public** (same as the MLB project — no secrets or usernames are in it).
4. Leave **Add a README**, **.gitignore** and **license** all **off**.
5. Click **Create repository**. Tell Claude when done.

- [ ] **Step 5: First push (controller; Nathan-approval step)**

```bash
git remote add origin https://github.com/natergater24/nfl-dfs-optimizer.git && git push -u origin main
```
Expected: push succeeds using the Mac's saved GitHub login (same keychain the MLB project uses). If it asks for a username/password, stop and walk Nathan through it rather than entering anything.

- [ ] **Step 6: Nathan deploys on Streamlit Community Cloud (Nathan does this; exact clicks)**
1. Open **share.streamlit.io** and sign in (same account as the MLB app).
2. Click **Create app** → **Deploy a public app from GitHub** (or "Yup, I have an app").
3. Repository: `natergater24/nfl-dfs-optimizer` · Branch: `main` · Main file path: `app.py`.
4. **Advanced settings** → Python version: the newest offered (3.12 or later). No secrets needed. **Save**.
5. Click **Deploy**. First start takes a few minutes. Copy the app's URL and send it to Claude.
6. Optional (privacy): in the app's **Settings → Sharing**, choose "Only specific people can view" and add your email.

- [ ] **Step 7: Verify the hosted copy (Nathan on his phone + controller)**
- The page loads with the hosted banner, the slate, and the contest-type selector.
- Switching contest types changes the lineup; **ℹ️ Key** opens; matchups are colored; salaries read like `$7,500`.
- 🛠 My Lineup: tap a slot, tap a player → swap works; download button works when valid.
- Sidebar: **Check for results** is disabled with the "works on your Mac" note.
- After the next scheduled run, `logs/pipeline.log` shows `publish ok: published to GitHub` and the hosted page's "Updated … ago" refreshes within a few minutes.

---

### Task 13: User manual, finalized import guide, project docs

**Files:**
- Create: `USER_MANUAL.md`
- Modify: `nfldfs_app/view_sidebar.py` (`IMPORT_GUIDE` final wording), `README.md`, `claude-context.txt`, `claude-prompts.txt`

- [ ] **Step 1: Finalize the DraftKings export steps from Nathan's screenshots (controller + Nathan)**

Ask Nathan to take a screenshot of each screen while doing the export once (My Contests page, completed tab, the contest page with the Export link, and the downloaded file in Finder) and send them. From the screenshots, rewrite `IMPORT_GUIDE` so every step names the exact button text and where it is on screen, one action per step, no assumed technical knowledge. Also open his real zip once (`./py -c "from nfldfs.results import read_standings; print(read_standings('<path>').head())"`) to confirm the column names match Task 3; if they differ, fix `read_standings` + its test in this task.

- [ ] **Step 2: Write `USER_MANUAL.md`** (plain language; this exact structure and content, updating only the bracketed live values from the real setup):

```markdown
# NFL DFS Lineups — User Manual

## What happens automatically each week
| When | What your Mac does |
|---|---|
| Tuesday 9:00 AM | Downloads this week's DraftKings salaries and last week's NFL stats |
| Thursday 9:00 AM | Gets Vegas lines, builds every contest type's lineups, publishes to your phone |
| Sunday 9:00 AM | Re-checks injuries and lines, rebuilds, publishes |
| Sunday 11:45 AM | Re-checks injuries after inactives are announced, rebuilds, publishes |
| Whenever a results file lands in Downloads | Imports it and updates the report card |

Your Mac must be plugged in. It wakes itself 5 minutes before each run.

## Your 2 minutes on Sunday
1. Open the app — on your phone (the Streamlit link) or on the Mac (double-click **Launch_NFL_DFS** on the Desktop).
2. Pick the **DraftKings contest type** you're entering (top of the page).
3. Use the ⭐ **Recommended** lineup, or build your own in 🛠 **My Lineup**.
4. Click **Download** and upload that CSV on DraftKings (Lineups → Upload Lineups).

## Building your own lineup (🛠 My Lineup)
- Click a slot on the left → the right side shows who can fill it. Click a player to swap him in.
- Or click a player on the right → slots he can't fill turn gray. Click a highlighted slot.
- Or drag a player onto a slot. On a phone, tap instead of dragging.
- The salary bar turns red over $50,000 and the download button turns off until you fix it.

## What the colors and labels mean
Open **ℹ️ Key** in the app. Short version: 🔥 Chalk = most people have him; 💎 Contrarian = few do.
Green matchup = soft defense, red = tough defense.

## After Sunday's games (optional, 2 clicks)
Follow **📥 How to import last week's results** in the app's sidebar. The 📈 report card then shows how
close the projections were. After 3 imported weeks, ownership estimates start learning from your results.

## If something goes wrong
- **A red banner at the top** says which step failed and what to do. Most fix themselves on the next run.
- **"DraftKings returned something other than the salary CSV"**: on draftkings.com open any main-slate
  contest, click **Export to CSV**, then in the Mac app's sidebar use **Upload DKSalaries.csv**.
- **"The Odds API request failed"**: the monthly free limit may be used up (shared with the MLB app). The app
  reuses lines up to 48 hours old automatically.
- **The phone copy didn't update**: check `logs/pipeline.log` on the Mac for the `publish` line.

## Useful commands (Terminal, in the NFL_DFS folder)
- Run a stage now: `./py run_pipeline.py --stage thursday` (or tuesday, sunday, refresh, results, build)
- Start the Mac app: `bash launch.sh`
- Turn the schedule off / on: `bash scripts/uninstall_schedule.sh` / `bash scripts/install_schedule.sh`
- Logs: `tail -50 logs/pipeline.log`, `tail -50 logs/launchagent.log`, `tail -50 logs/streamlit.log`
```

- [ ] **Step 3: Update `README.md`, `claude-context.txt`, `claude-prompts.txt`**
- README: add "Weekly use" pointing to USER_MANUAL.md, the hosted URL, the local launcher, and the stage list.
- `claude-context.txt`: a dated (today) section describing Plan 2 — app modules, stages, publish flow, results/history privacy rule, ownership model activation, schedule + pmset + Downloads access result from Task 11 Step 6, hosted URL, and the OUTSTANDING list: red-zone shares, option C (Sleeper blend), matchup as a projection input (decide from the report card), historical backtest (spec §12), and reviewing the report card after 3–4 weeks.
- `claude-prompts.txt`: dated session-log entry summarizing the prototype decisions (two-panel builder, drag/drop, matchups, Key, full prices) and the Plan 2 build.

- [ ] **Step 4: Run the full suite, then commit and publish**

```bash
./py -m pytest -q -W error
git add USER_MANUAL.md README.md claude-context.txt claude-prompts.txt nfldfs_app/view_sidebar.py nfldfs/results.py tests/test_results.py
git commit -m "Add user manual, finalize the DraftKings import guide, update project docs" -m "Co-Authored-By: <model> <noreply@anthropic.com>"
git push
```
Expected: suite green; push succeeds (Streamlit Cloud redeploys the app with the final guide).

---

## Self-Review Notes

- **Spec coverage:** §5 schedule → Tasks 5, 11; §9 app (header, Key, Recommended, outliers + Apply, My Lineup builder with three swap methods, pool + locks/rebuild, report card, pre-lock/OUT warning, sidebar import guide + fallbacks, hosted vs local) → Tasks 6–10, 13; §9 display rules (full dollars, matchup gradient, tiers, model-relative labels) → Tasks 1, 6, 7; §10 layout → File Structure; §11 errors (status per step, publish never blocks, Vegas 48h fallback, missing files) → Tasks 5, 6; §12 report card → Tasks 3, 7; §7.4 ownership regression after 3 weeks → Task 4; §3 privacy/credentials → Global Constraints + Tasks 3, 5; Plan 1 rulings carried: Sunday 11:45 reuses Vegas (Task 5), author reset before first push (Task 12), swaps spread across positions and model-relative labels (Tasks 2, 7). **Not in this plan:** red-zone shares, Sleeper blend, historical backtest — listed as outstanding in Task 13.
- **Placeholder scan:** commit trailers say `<model>` deliberately (each implementer names its own model, per the Plan 1 ruling). `USER_MANUAL.md` has no bracketed values left except what Step 2 says to fill from the live setup (none required). Task 12/13 human steps are exact clicks, not placeholders.
- **Type consistency:** `build_all` returns 3 values everywhere after Task 2; `best_lineup` returns row positions; `AppData.row_of` maps dk_id → row; session keys `my_ids/focus_slot/focus_token/lb_seen/rebuilt/flash` are defined once (Tasks 6–10) and used consistently; `results_status.json` only for the results stage.
