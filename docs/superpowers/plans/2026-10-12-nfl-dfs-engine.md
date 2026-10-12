# NFL DFS Engine (Plan 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command (`./py run_pipeline.py --stage thursday`) turns this week's DraftKings Sunday main-slate salaries, nflverse stats and Vegas lines into a recommended lineup + ranked alternates + outlier swaps for every DraftKings contest type, plus a DK upload CSV.

**Architecture:** A small Python package `nfldfs/` with one module per pipeline step (salaries → stats → team environment → player shares → simulation → ownership → optimizer → contest evaluation), orchestrated in-process by `run_pipeline.py`, which records every step's outcome in `data/published/run_status.json`. Plan 2 (written after this lands) adds the Streamlit app, publishing to GitHub/Streamlit Cloud, LaunchAgent scheduling, results import and user docs on top of the files this plan writes to `data/published/`.

**Tech Stack:** Python 3.14 (system install), pandas 3, numpy 2, pyarrow, requests, python-dotenv, PuLP (HiGHS solver via `highspy`, CBC fallback), nflreadpy (+ polars), pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-nfl-dfs-optimizer-design.md`

## Global Constraints

- Python: always run via the repo's `./py` wrapper (created in Task 1), which execs `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3` — same interpreter convention as `MLB_Pipeline`. Never bare `python3`.
- Salary cap **$50,000**; default minimum lineup salary **$49,000**; roster exactly `QB, RB, RB, WR, WR, WR, TE, FLEX, DST` (FLEX = RB/WR/TE). An invalid lineup must be impossible to export.
- **No DraftKings credentials anywhere in the project.** No login automation, no contest entry. DK access is limited to the unauthenticated lobby JSON and the official "Export to CSV" URL, a handful of requests per run.
- DK URLs (verified live 2026-10-12): lobby `https://www.draftkings.com/lobby/getcontests?sport=NFL`; salary CSV `https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId={contest_type_id}&draftGroupId={draft_group_id}`. The JSON draftables API returns 403 and must not be used.
- Contest types use DraftKings' names: Head-to-Head, 50/50, Double Up, Multiplier (3x/5x/10x), Single Entry / 3-Max Tournament, Tournament, Large-Field Tournament. All tunable numbers live in `nfldfs/config.py`.
- Secrets: `ODDS_API_KEY` in git-ignored `env.txt`; only `env.txt.example` is committed.
- Every file a later step or the app reads is written atomically (`.tmp` then `os.replace`).
- Any failure must be loud: a failing step stops the run, is recorded in `run_status.json` with a plain-language message, and makes `run_pipeline.py` exit non-zero.
- Commit messages end with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (the second `-m` in every commit command below does this).

**Deliberate deviations from the spec (approved scope, simpler build):**
- Spec §10's numbered `src/NN_*.py` scripts become importable modules in `nfldfs/` (numbered filenames can't be imported or unit-tested); `run_pipeline.py` runs them in-process. Same steps, same order.
- Spec §7.2 red-zone shares are not in v1: touchdowns are allocated by target/carry share × a position TD weight (`simulate.TD_WEIGHT`). Red-zone shares need full play-by-play downloads; revisit after the report card shows whether TD allocation is a weak spot.
- Spec §6's DK "draftables" endpoint is replaced by DK's own CSV export URL (the JSON endpoint is blocked; the CSV URL is the same file as the manual fallback, so one parser serves both).

## Review Focus

1. **A DraftKings player with no nflverse history or a differently-spelled name** (rookie, "Kenneth Walker III" vs "Kenneth Walker") must get conservative fallback shares, never crash, and the build must report the match rate → Task 6 `test_unmatched_player_gets_fallback_shares`, `test_suffix_name_matches`; Task 11 `test_build_slate_end_to_end` asserts `match_rate`.
2. **A slate game with no Vegas line yet** (lines not posted, odds quota exhausted) must stop the build with a message naming the teams, not silently project zero → Task 11 `test_missing_vegas_lines_names_teams`.
3. **The starting QB ruled OUT** must hand passing volume and his carry share to the backup → Task 6 `test_redistribute_moves_out_qb_carries_to_backup`; Task 7 `test_backup_qb_throws_when_starter_out`.
4. **Locks or a minimum salary that make a lineup impossible** must raise a plain-language `InfeasibleError`, not return a broken lineup → Task 9 `test_impossible_min_salary_raises`, `test_lock_of_unplayable_player_raises`.
5. **DraftKings returning something other than the CSV** (blocked/HTML page) or a CSV with a BOM, blank statuses, OUT/IR/D players → clear error / correct playable flags → Task 3 `test_fetch_salary_csv_rejects_html`, `test_parse_salary_csv_statuses_and_bom`.

---

## File Structure

```
NFL_DFS/
  py                         wrapper → system Python 3.14
  requirements.txt
  pytest.ini
  .gitignore
  env.txt.example
  run_pipeline.py            stage runner (Task 11)
  nfldfs/
    __init__.py
    config.py                paths, every tunable number, contest types (Task 1)
    status.py                atomic writes + RunStatus (Task 1)
    teams.py                 team abbreviations, Odds-API names, name normalization (Task 2)
    dk_rules.py              roster/cap rules, DK scoring, slot assignment, upload CSV (Task 2)
    dk_salaries.py           lobby → main slate → salary CSV → player pool (Task 3)
    vegas.py                 The Odds API → game lines → implied team totals (Task 4)
    nfl_stats.py             nflreadpy loaders + normalization (Task 5)
    team_env.py              implied total → expected team stats model (Task 5)
    shares.py                player usage shares, name matching, injury redistribution (Task 6)
    simulate.py              Monte Carlo → DK points matrix + summaries (Task 7)
    ownership.py             ownership estimate + tiers (Task 8)
    optimizer.py             PuLP lineup solver (Task 9)
    sim_eval.py              simulated field + contest metrics (Task 10)
    lineups.py               candidates, contest picks, swaps (Task 10)
    build.py                 assembles a full slate build from loaded inputs (Task 11)
  tests/
    conftest.py              synthetic 2-game slate fixtures (Task 1, extended in Tasks 7 & 11)
    fixtures/                lobby_sample.json, dk_salaries_sample.csv, odds_sample.json
    test_*.py                one per module
  data/                      git-ignored (raw/, processed/, published/)
  logs/                      git-ignored
```

---

### Task 1: Project scaffold, config, status tracking

**Files:**
- Create: `py`, `requirements.txt`, `pytest.ini`, `.gitignore`, `env.txt.example`, `nfldfs/__init__.py`, `nfldfs/config.py`, `nfldfs/status.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_status.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.ROOT, RAW, PROCESSED, PUBLISHED, LOGS` (Paths); constants `SALARY_CAP, MIN_SALARY_DEFAULT, FIELD_MIN_SALARY, N_SIMS, N_SIMS_PUBLISHED, N_CANDIDATES, FIELD_SIZE, MIN_UNIQUE_PLAYERS, CANDIDATE_PERTURBATION, N_SWAPS, SWAP_MAX_OWN_TOURNAMENT, SEED, STATS_SEASONS_BACK, QB_STACK_MIN, OWNERSHIP_TIERS, CONTEST_TYPES`; `season_for(date) -> int`; `odds_api_key() -> str`.
- Produces: `status.atomic_write_bytes(path, data: bytes)`, `atomic_write_text(path, text: str)`, `atomic_write_parquet(df, path)`, `atomic_save_npy(arr, path)`, `class RunStatus(path, stage)` with `.step(name)` context manager yielding a dict record (set `rec["message"]`) and `.finish(ok: bool)`.
- Produces: `tests/conftest.py::make_pool() -> pd.DataFrame` (synthetic 2-game, 4-team, 64-player slate) and fixture `pool`.

- [ ] **Step 1: Create the Python wrapper, requirements, pytest config, ignore file, env example**

`py`:
```sh
#!/bin/sh
# Always use the system Python 3.14 install (same convention as MLB_Pipeline).
exec /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 "$@"
```

`requirements.txt`:
```
# NFL DFS optimizer — install with: ./py -m pip install -r requirements.txt
pandas>=2.2
numpy>=2.0
pyarrow>=15.0
requests>=2.31
python-dotenv>=1.0
pulp>=3.0
highspy>=1.7
nflreadpy>=0.1.5
polars>=1.0

# Testing
pytest>=8.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.gitignore`:
```
# Secrets — never commit real keys
env.txt
*env*.txt
!env.txt.example
.env

# Built data and logs (Plan 2 un-ignores the published files the hosted app needs)
data/
logs/

# Python / OS
__pycache__/
*.py[cod]
.pytest_cache/
.DS_Store
```

`env.txt.example`:
```
# Copy to env.txt and fill in. env.txt is git-ignored.
# The Odds API key (free tier, 500 requests/month) — https://the-odds-api.com
ODDS_API_KEY=
```

Run:
```bash
cd ~/Desktop/Nathan/Claude/NFL_DFS && chmod +x py && mkdir -p nfldfs tests/fixtures && touch nfldfs/__init__.py tests/__init__.py
```

- [ ] **Step 2: Install dependencies and confirm a MILP solver and nflreadpy work**

```bash
cd ~/Desktop/Nathan/Claude/NFL_DFS && ./py -m pip install -r requirements.txt
./py -c "import pulp; print(pulp.__version__, pulp.listSolvers(onlyAvailable=True))"
./py -c "import nflreadpy, polars; print('nflreadpy ok', polars.__version__)"
```
Expected: the solver list contains `HiGHS` and/or `PULP_CBC_CMD`; nflreadpy imports. **If `highspy` fails to install on 3.14**, remove that line from `requirements.txt`, re-run the install, and confirm `PULP_CBC_CMD` is listed. **If the solver list is empty, stop and report** — every later task needs a solver.

- [ ] **Step 3: Write failing tests for config and status**

`tests/test_config.py`:
```python
import datetime as dt

from nfldfs import config


def test_contest_types_use_draftkings_names_and_valid_metrics():
    labels = [c["label"] for c in config.CONTEST_TYPES.values()]
    assert labels == [
        "Head-to-Head", "50/50", "Double Up",
        "Multiplier (3x)", "Multiplier (5x)", "Multiplier (10x)",
        "Single Entry / 3-Max Tournament", "Tournament", "Large-Field Tournament",
    ]
    for c in config.CONTEST_TYPES.values():
        assert c["group"] in ("Cash", "Multiplier", "Tournament")
        assert c["metric"]["kind"] in ("h2h", "top_pct")
        if c["metric"]["kind"] == "top_pct":
            assert 0 < c["metric"]["pct"] < 1
        assert set(c["weights"]) <= {"floor", "median", "ceiling", "own_penalty"}
        assert c["stack"] == (c["group"] == "Tournament")


def test_season_for_rolls_over_in_september():
    assert config.season_for(dt.date(2026, 10, 12)) == 2026
    assert config.season_for(dt.date(2027, 1, 3)) == 2026
    assert config.season_for(dt.date(2026, 9, 1)) == 2026
```

`tests/test_status.py`:
```python
import json

import numpy as np
import pandas as pd
import pytest

from nfldfs.status import (RunStatus, atomic_save_npy, atomic_write_parquet,
                           atomic_write_text)


def test_atomic_writes_leave_no_tmp_files(tmp_path):
    atomic_write_text(tmp_path / "a" / "x.json", '{"k": 1}')
    atomic_write_parquet(pd.DataFrame({"a": [1, 2]}), tmp_path / "a" / "x.parquet")
    atomic_save_npy(np.arange(3), tmp_path / "a" / "x.npy")
    names = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert names == ["x.json", "x.npy", "x.parquet"]
    assert np.load(tmp_path / "a" / "x.npy").tolist() == [0, 1, 2]


def test_run_status_records_success_failure_and_reraises(tmp_path):
    path = tmp_path / "run_status.json"
    rs = RunStatus(path, "thursday")
    with rs.step("salaries") as rec:
        rec["message"] = "fetched 513 players"
    with pytest.raises(ValueError):
        with rs.step("vegas"):
            raise ValueError("quota exhausted")
    rs.finish(False)
    data = json.loads(path.read_text())
    assert data["stage"] == "thursday" and data["ok"] is False
    assert [s["name"] for s in data["steps"]] == ["salaries", "vegas"]
    assert data["steps"][0]["ok"] is True and data["steps"][0]["message"] == "fetched 513 players"
    assert data["steps"][1]["ok"] is False and "quota exhausted" in data["steps"][1]["message"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `./py -m pytest tests/test_config.py tests/test_status.py -v`
Expected: FAIL / ERROR with `ImportError` (modules don't exist yet).

- [ ] **Step 5: Implement `nfldfs/config.py` and `nfldfs/status.py`**

`nfldfs/config.py`:
```python
"""Project-wide settings. Every tunable number lives here."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
PUBLISHED = DATA / "published"
LOGS = ROOT / "logs"

SALARY_CAP = 50_000
MIN_SALARY_DEFAULT = 49_000
FIELD_MIN_SALARY = 45_000          # simulated opponents leave a bit more salary unused
N_SIMS = 10_000
N_SIMS_PUBLISHED = 5_000           # float16 copy the hosted app re-scores swaps with
N_CANDIDATES = 150
FIELD_SIZE = 2_000
MIN_UNIQUE_PLAYERS = 3             # each candidate differs from earlier ones by >= 3 players
CANDIDATE_PERTURBATION = 0.35      # how far a random simulated week nudges each candidate solve
N_SWAPS = 8
SWAP_MAX_OWN_TOURNAMENT = 10.0     # tournament outliers must be Moderate or Contrarian
SEED = 20261012
STATS_SEASONS_BACK = 3             # current season + 3 prior seasons of nflverse data
QB_STACK_MIN = 1                   # tournament lineups pair the QB with >= 1 own WR/TE

OWNERSHIP_TIERS = ((25.0, "Chalk"), (10.0, "Popular"), (5.0, "Moderate"), (0.0, "Contrarian"))

_CASH = {"floor": 0.5, "median": 0.5}
_MULT = {"median": 0.5, "ceiling": 0.5, "own_penalty": 0.05}


def _contest(label, group, weights, metric):
    return {"label": label, "group": group, "weights": weights,
            "stack": group == "Tournament", "metric": metric}


CONTEST_TYPES = {
    "h2h": _contest("Head-to-Head", "Cash", _CASH, {"kind": "h2h"}),
    "fifty_fifty": _contest("50/50", "Cash", _CASH, {"kind": "top_pct", "pct": 0.50}),
    "double_up": _contest("Double Up", "Cash", _CASH, {"kind": "top_pct", "pct": 0.44}),
    "multiplier_3x": _contest("Multiplier (3x)", "Multiplier", _MULT, {"kind": "top_pct", "pct": 1 / 3}),
    "multiplier_5x": _contest("Multiplier (5x)", "Multiplier", _MULT, {"kind": "top_pct", "pct": 0.20}),
    "multiplier_10x": _contest("Multiplier (10x)", "Multiplier", _MULT, {"kind": "top_pct", "pct": 0.10}),
    "single_entry": _contest("Single Entry / 3-Max Tournament", "Tournament",
                             {"ceiling": 1.0, "own_penalty": 0.05}, {"kind": "top_pct", "pct": 0.01}),
    "tournament": _contest("Tournament", "Tournament",
                           {"ceiling": 1.0, "own_penalty": 0.15}, {"kind": "top_pct", "pct": 0.01}),
    "large_tournament": _contest("Large-Field Tournament", "Tournament",
                                 {"ceiling": 1.0, "own_penalty": 0.30}, {"kind": "top_pct", "pct": 0.01}),
}


def season_for(date: dt.date) -> int:
    """NFL season year: games in Jan/Feb belong to the previous year's season."""
    return date.year if date.month >= 9 else date.year - 1


def odds_api_key() -> str:
    load_dotenv(ROOT / "env.txt")
    key = os.getenv("ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ODDS_API_KEY is not set — add it to env.txt (see env.txt.example)")
    return key
```

`nfldfs/status.py`:
```python
"""Atomic file writes and per-step run status (read by the app's failure banner)."""
from __future__ import annotations

import datetime as dt
import json
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd


def _tmp(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.with_name(path.name + ".tmp")


def atomic_write_bytes(path, data: bytes) -> None:
    path = Path(path)
    tmp = _tmp(path)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_parquet(df: pd.DataFrame, path) -> None:
    path = Path(path)
    tmp = _tmp(path)
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_save_npy(arr: np.ndarray, path) -> None:
    path = Path(path)
    tmp = _tmp(path)
    with open(tmp, "wb") as f:
        np.save(f, arr)
    os.replace(tmp, path)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class RunStatus:
    """Writes {stage, started, finished, ok, steps[...]} after every change."""

    def __init__(self, path, stage: str):
        self.path = Path(path)
        self.data = {"stage": stage, "started": _now(), "finished": None, "ok": None, "steps": []}
        self._write()

    @contextmanager
    def step(self, name: str):
        rec = {"name": name, "started": _now(), "finished": None, "ok": None, "message": ""}
        self.data["steps"].append(rec)
        self._write()
        try:
            yield rec
        except Exception as e:
            rec.update(ok=False, finished=_now(), message=f"{type(e).__name__}: {e}")
            self._write()
            raise
        rec.update(ok=True, finished=_now())
        self._write()

    def finish(self, ok: bool) -> None:
        self.data.update(ok=ok, finished=_now())
        self._write()

    def _write(self) -> None:
        atomic_write_text(self.path, json.dumps(self.data, indent=2, default=str))
```

`tests/conftest.py`:
```python
"""Synthetic 2-game slate shared by the optimizer/simulation/lineup tests."""
import pandas as pd
import pytest

GAMES = [("AAA", "BBB"), ("CCC", "DDD")]  # (away, home)
SALARIES = {
    "QB": [7000, 4500],
    "RB": [8000, 6000, 5000, 4000],
    "WR": [8500, 7000, 6000, 5000, 4000, 3000],
    "TE": [6000, 4000, 2500],
    "DST": [3000],
}
TGT = {"RB": [0.10, 0.06, 0.04, 0.02], "WR": [0.26, 0.20, 0.14, 0.08, 0.04, 0.02], "TE": [0.15, 0.05, 0.02]}
CAR = {"QB": [0.10, 0.0], "RB": [0.55, 0.20, 0.10, 0.03]}
CATCH = {"RB": 0.78, "WR": 0.64, "TE": 0.70}
YPT = {"RB": 6.0, "WR": 8.3, "TE": 7.2}
YPC = {"QB": 5.0, "RB": 4.3}
IMPLIED = {"AAA": 21.0, "BBB": 24.0, "CCC": 24.5, "DDD": 22.5}


def make_pool() -> pd.DataFrame:
    rows, dk = [], 1000
    for away, home in GAMES:
        kickoff = pd.Timestamp("2026-10-18 13:00") if away == "AAA" else pd.Timestamp("2026-10-18 16:25")
        for team, opp in ((away, home), (home, away)):
            for pos, sals in SALARIES.items():
                for r, sal in enumerate(sals):
                    dk += 1
                    rows.append(dict(
                        dk_id=dk, name=f"{team} {pos}{r + 1}", position=pos, salary=sal,
                        team=team, opp=opp, game_id=f"{away}@{home}", is_home=team == home,
                        kickoff=kickoff, status="", playable=True, dk_avg=sal / 500,
                        tgt_share=TGT[pos][r] if pos in TGT else 0.0,
                        carry_share=CAR[pos][r] if pos in CAR else 0.0,
                        catch_rate=CATCH.get(pos, 0.0), ypt=YPT.get(pos, 0.0), ypc=YPC.get(pos, 0.0),
                        implied_total=IMPLIED[team], opp_implied=IMPLIED[opp],
                    ))
    return pd.DataFrame(rows)


@pytest.fixture
def pool() -> pd.DataFrame:
    return make_pool()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./py -m pytest tests/test_config.py tests/test_status.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add py requirements.txt pytest.ini .gitignore env.txt.example nfldfs tests
git commit -m "Scaffold NFL DFS engine: config, contest types, status tracking" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Teams, names and DraftKings rules

**Files:**
- Create: `nfldfs/teams.py`, `nfldfs/dk_rules.py`, `tests/test_teams.py`, `tests/test_dk_rules.py`

**Interfaces:**
- Consumes: `config.SALARY_CAP`; `status.atomic_write_text`.
- Produces: `teams.ODDS_API_NAMES: dict[str, str]`, `teams.to_dk_team(abbr) -> str`, `teams.normalize_name(name) -> str`.
- Produces: `dk_rules.ROSTER_SLOTS` (tuple of 9 slot names), `FLEX_ELIGIBLE`, `POSITION_BOUNDS: dict[str, tuple[int,int]]`, `offense_points(pass_yds=0, pass_td=0, ints=0, rush_yds=0, rush_td=0, receptions=0, rec_yds=0, rec_td=0, fumbles_lost=0, two_pt=0) -> np.ndarray`, `points_allowed_score(pa) -> np.ndarray`, `dst_points(points_allowed, sacks=0, ints=0, fumble_recoveries=0, def_tds=0, safeties=0, blocked_kicks=0) -> np.ndarray`, `validate_lineup(players: DataFrame[dk_id, position, salary]) -> list[str]`, `assign_slots(players) -> list[int]` (dk_ids in `ROSTER_SLOTS` order), `write_upload_csv(lineups: list[DataFrame], path) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_teams.py`:
```python
from nfldfs.teams import ODDS_API_NAMES, normalize_name, to_dk_team


def test_nflverse_abbreviations_map_to_draftkings():
    assert to_dk_team("LA") == "LAR"
    assert to_dk_team("kc") == "KC"
    assert to_dk_team("JAX") == "JAX"


def test_odds_api_names_cover_32_teams():
    assert len(ODDS_API_NAMES) == 32 and len(set(ODDS_API_NAMES.values())) == 32
    assert ODDS_API_NAMES["Los Angeles Rams"] == "LAR"


def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("Kenneth Walker III") == normalize_name("Kenneth Walker") == "kenneth walker"
    assert normalize_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert normalize_name("D'Andre Swift") == "dandre swift"
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
```

`tests/test_dk_rules.py`:
```python
import csv

import numpy as np
import pandas as pd
import pytest

from nfldfs import dk_rules


def test_offense_scoring_with_bonuses():
    assert dk_rules.offense_points(pass_yds=300, pass_td=2, ints=1) == pytest.approx(22.0)
    assert dk_rules.offense_points(pass_yds=299) == pytest.approx(11.96)
    assert dk_rules.offense_points(rush_yds=100, rush_td=1, receptions=3, rec_yds=25) == pytest.approx(24.5)
    assert dk_rules.offense_points(rec_yds=100, fumbles_lost=1, two_pt=1) == pytest.approx(14.0)


def test_offense_scoring_vectorized():
    pts = dk_rules.offense_points(rec_yds=np.array([[50.0, 100.0]]), receptions=np.array([[4, 6]]))
    assert pts.shape == (1, 2) and pts.tolist() == [[9.0, 19.0]]


@pytest.mark.parametrize("pa,expected", [(0, 10), (1, 7), (6, 7), (7, 4), (13, 4), (14, 1), (20, 1),
                                         (21, 0), (27, 0), (28, -1), (34, -1), (35, -4), (52, -4)])
def test_points_allowed_tiers(pa, expected):
    assert dk_rules.points_allowed_score(pa) == expected


def test_dst_points():
    assert dk_rules.dst_points(points_allowed=0, sacks=3, ints=1) == pytest.approx(15.0)
    assert dk_rules.dst_points(points_allowed=24, fumble_recoveries=1, def_tds=1,
                               safeties=1, blocked_kicks=1) == pytest.approx(12.0)


def _lineup(pool, ids):
    return pool[pool.dk_id.isin(ids)]


def _valid_ids(pool):
    """Cheapest-end picks: $33,000 total, all from the 1:00 PM AAA@BBB game."""
    a = pool[pool.team == "AAA"]
    b = pool[pool.team == "BBB"]
    pick = lambda df, pos, n: df[df.position == pos].dk_id.tolist()[-n:]
    return (pick(a, "QB", 1) + pick(a, "RB", 2) + pick(b, "RB", 1) + pick(a, "WR", 2)
            + pick(b, "WR", 1) + pick(a, "TE", 1) + pick(b, "DST", 1))


def test_validate_lineup_accepts_valid_and_rejects_invalid(pool):
    good = _lineup(pool, _valid_ids(pool))
    assert dk_rules.validate_lineup(good) == []
    over = good.assign(salary=good.salary + 2000)
    assert any("over the $50,000 cap" in e for e in dk_rules.validate_lineup(over))
    two_qb = pd.concat([good.iloc[:8], pool[(pool.position == "QB") & (pool.team == "BBB")].iloc[:1]])
    assert dk_rules.validate_lineup(two_qb) != []
    assert any("needs 9" in e for e in dk_rules.validate_lineup(good.iloc[:8]))


def test_assign_slots_puts_latest_kickoff_extra_in_flex(pool):
    good = _lineup(pool, _valid_ids(pool)).copy()
    late_rb = good[(good.position == "RB") & (good.team == "BBB")].dk_id.iloc[0]
    good.loc[good.dk_id == late_rb, "kickoff"] = pd.Timestamp("2026-10-18 16:25")
    slots = dk_rules.assign_slots(good)
    assert len(slots) == 9 and slots[7] == late_rb
    pos = dict(zip(good.dk_id, good.position))
    assert [pos[s] for s in slots] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "RB", "DST"]


def test_write_upload_csv_header_and_rows(pool, tmp_path):
    good = _lineup(pool, _valid_ids(pool))
    path = tmp_path / "upload.csv"
    dk_rules.write_upload_csv([good, good], path)
    rows = list(csv.reader(path.open()))
    assert rows[0] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
    assert len(rows) == 3 and sorted(map(int, rows[1])) == sorted(good.dk_id.tolist())


def test_write_upload_csv_refuses_invalid_lineup(pool, tmp_path):
    bad = _lineup(pool, _valid_ids(pool)).iloc[:8]
    with pytest.raises(ValueError):
        dk_rules.write_upload_csv([bad], tmp_path / "upload.csv")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_teams.py tests/test_dk_rules.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/teams.py`**

```python
"""Team abbreviations and player-name normalization shared by every data source."""
from __future__ import annotations

import re
import unicodedata

# nflverse abbreviations that differ from DraftKings'. Everything else matches.
NFLVERSE_TO_DK = {"LA": "LAR", "WSH": "WAS"}

ODDS_API_NAMES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def to_dk_team(abbr) -> str:
    a = str(abbr).strip().upper()
    return NFLVERSE_TO_DK.get(a, a)


def normalize_name(name) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    s = _SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", s).strip()
```

- [ ] **Step 4: Implement `nfldfs/dk_rules.py`**

```python
"""DraftKings NFL Classic rules: roster, salary cap, scoring, upload CSV. Single source of truth."""
from __future__ import annotations

import csv
import io

import numpy as np
import pandas as pd

from .config import SALARY_CAP
from .status import atomic_write_text

ROSTER_SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
FLEX_ELIGIBLE = ("RB", "WR", "TE")
# Min/max count of each position in a 9-player lineup once FLEX is included.
POSITION_BOUNDS = {"QB": (1, 1), "RB": (2, 3), "WR": (3, 4), "TE": (1, 2), "DST": (1, 1)}


def offense_points(pass_yds=0, pass_td=0, ints=0, rush_yds=0, rush_td=0, receptions=0,
                   rec_yds=0, rec_td=0, fumbles_lost=0, two_pt=0) -> np.ndarray:
    a = lambda v: np.asarray(v, dtype=float)
    pass_yds, rush_yds, rec_yds = a(pass_yds), a(rush_yds), a(rec_yds)
    pts = (0.04 * pass_yds + 4 * a(pass_td) - a(ints)
           + 0.1 * rush_yds + 6 * a(rush_td)
           + a(receptions) + 0.1 * rec_yds + 6 * a(rec_td)
           - a(fumbles_lost) + 2 * a(two_pt))
    pts = pts + 3 * (pass_yds >= 300) + 3 * (rush_yds >= 100) + 3 * (rec_yds >= 100)
    return pts


def points_allowed_score(pa) -> np.ndarray:
    pa = np.asarray(pa, dtype=float)
    return np.select([pa == 0, pa <= 6, pa <= 13, pa <= 20, pa <= 27, pa <= 34],
                     [10, 7, 4, 1, 0, -1], default=-4)


def dst_points(points_allowed, sacks=0, ints=0, fumble_recoveries=0, def_tds=0,
               safeties=0, blocked_kicks=0) -> np.ndarray:
    a = lambda v: np.asarray(v, dtype=float)
    return (a(sacks) + 2 * a(ints) + 2 * a(fumble_recoveries) + 6 * a(def_tds)
            + 2 * a(safeties) + 2 * a(blocked_kicks) + points_allowed_score(points_allowed))


def validate_lineup(players: pd.DataFrame) -> list[str]:
    errors = []
    if len(players) != len(ROSTER_SLOTS):
        errors.append(f"lineup has {len(players)} players, needs 9")
    if players.dk_id.duplicated().any():
        errors.append("lineup repeats a player")
    total = int(players.salary.sum())
    if total > SALARY_CAP:
        errors.append(f"salary ${total:,} is over the ${SALARY_CAP:,} cap")
    counts = players.position.value_counts()
    unknown = set(players.position) - set(POSITION_BOUNDS)
    if unknown:
        errors.append(f"unknown positions: {sorted(unknown)}")
    for pos, (lo, hi) in POSITION_BOUNDS.items():
        c = int(counts.get(pos, 0))
        if not lo <= c <= hi:
            errors.append(f"{c} {pos} (needs {lo}-{hi})")
    return errors


def assign_slots(players: pd.DataFrame) -> list[int]:
    """dk_ids in ROSTER_SLOTS order. FLEX gets the extra RB/WR/TE with the latest kickoff
    (keeps late-swap options open), cheapest on ties."""
    errors = validate_lineup(players)
    if errors:
        raise ValueError("; ".join(errors))
    p = players.copy()
    if "kickoff" not in p.columns:
        p["kickoff"] = pd.Timestamp(0)
    flex_id = None
    for pos in FLEX_ELIGIBLE:
        group = p[p.position == pos]
        if len(group) > POSITION_BOUNDS[pos][0]:
            flex_id = int(group.sort_values(["kickoff", "salary"], ascending=[False, True]).dk_id.iloc[0])
    remaining = p[p.dk_id != flex_id].sort_values("salary", ascending=False)
    slots = []
    for slot in ROSTER_SLOTS:
        if slot == "FLEX":
            slots.append(flex_id)
            continue
        pick = int(remaining[remaining.position == slot].dk_id.iloc[0])
        slots.append(pick)
        remaining = remaining[remaining.dk_id != pick]
    return slots


def write_upload_csv(lineups: list[pd.DataFrame], path) -> None:
    """DraftKings bulk-upload format: slot header row, then one row of player IDs per lineup."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(ROSTER_SLOTS)
    for lu in lineups:
        w.writerow(assign_slots(lu))
    atomic_write_text(path, buf.getvalue())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_teams.py tests/test_dk_rules.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add nfldfs/teams.py nfldfs/dk_rules.py tests/test_teams.py tests/test_dk_rules.py
git commit -m "Add DraftKings roster/scoring rules, team and name normalization" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: DraftKings salaries (lobby → main slate → CSV → player pool)

**Files:**
- Create: `nfldfs/dk_salaries.py`, `tests/test_dk_salaries.py`, `tests/fixtures/lobby_sample.json`, `tests/fixtures/dk_salaries_sample.csv`

**Interfaces:**
- Consumes: `teams.to_dk_team`.
- Produces: `find_main_slate(lobby: dict, today: date) -> dict{draft_group_id:int, contest_type_id:int, start:str, game_count:int}`; `fetch_lobby(session=None) -> dict`; `fetch_salary_csv(slate: dict, session=None) -> str`; `parse_salary_csv(text: str) -> DataFrame` with columns `dk_id(int64), name, position, salary(int), team, opp, game_id ("AWAY@HOME"), is_home(bool), kickoff(datetime), dk_avg(float), status(str, "" when blank), playable(bool)`; `PLAYABLE_STATUSES = {"", "Q", "P"}`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/lobby_sample.json` (shape copied from the live lobby on 2026-10-12; trimmed):
```json
{
  "DraftGroups": [
    {"DraftGroupId": 154488, "ContestTypeId": 96, "GameTypeId": 96, "GameCount": 1, "StartDateEst": "2026-10-12T20:15:00.0000000", "DraftGroupTag": "Featured"},
    {"DraftGroupId": 154856, "ContestTypeId": 145, "GameTypeId": 145, "GameCount": 14, "StartDateEst": "2026-10-15T20:15:00.0000000", "DraftGroupTag": ""},
    {"DraftGroupId": 154900, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 7, "StartDateEst": "2026-10-18T13:00:00.0000000", "DraftGroupTag": ""},
    {"DraftGroupId": 154941, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 10, "StartDateEst": "2026-10-18T13:00:00.0000000", "DraftGroupTag": "Featured"},
    {"DraftGroupId": 154950, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 3, "StartDateEst": "2026-10-18T16:05:00.0000000", "DraftGroupTag": ""},
    {"DraftGroupId": 153728, "ContestTypeId": 21, "GameTypeId": 1, "GameCount": 11, "StartDateEst": "2026-11-01T13:00:00.0000000", "DraftGroupTag": ""}
  ]
}
```

`tests/fixtures/dk_salaries_sample.csv` — write it with a UTF-8 BOM exactly like DK does (header copied from the live file):
```bash
printf '\xef\xbb\xbfPosition,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame,Status\nRB,Bijan Robinson (44475736),Bijan Robinson,44475736,RB/FLEX,8700,CHI@ATL 10/18/2026 01:00PM ET,ATL,25.4,\nWR,Puka Nacua (44475972),Puka Nacua,44475972,WR/FLEX,8100,ARI@LAR 10/18/2026 04:05PM ET,LAR,21.6,Q\nQB,Some Quarterback (44470001),Some Quarterback,44470001,QB,6200,ARI@LAR 10/18/2026 04:05PM ET,ARI,18.1,OUT\nTE,Some Tightend (44470002),Some Tightend,44470002,TE/FLEX,3000,CHI@ATL 10/18/2026 01:00PM ET,CHI,4.2,IR\nWR,Doubtful Receiver (44470003),Doubtful Receiver,44470003,WR/FLEX,3500,CHI@ATL 10/18/2026 01:00PM ET,CHI,6.0,D\nDST,Rams (44476586),Rams,44476586,DST,3800,ARI@LAR 10/18/2026 04:05PM ET,LAR,5.3,\n' > tests/fixtures/dk_salaries_sample.csv
```

- [ ] **Step 2: Write the failing tests**

`tests/test_dk_salaries.py`:
```python
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from nfldfs import dk_salaries

FIX = Path(__file__).parent / "fixtures"


def _lobby():
    return json.loads((FIX / "lobby_sample.json").read_text())


def test_find_main_slate_picks_biggest_sunday_1pm_classic():
    slate = dk_salaries.find_main_slate(_lobby(), dt.date(2026, 10, 12))
    assert slate == {"draft_group_id": 154941, "contest_type_id": 21,
                     "start": "2026-10-18T13:00:00", "game_count": 10}


def test_find_main_slate_skips_past_weeks():
    assert dk_salaries.find_main_slate(_lobby(), dt.date(2026, 10, 19))["draft_group_id"] == 153728


def test_find_main_slate_raises_when_none():
    with pytest.raises(LookupError, match="main slate"):
        dk_salaries.find_main_slate({"DraftGroups": []}, dt.date(2026, 10, 12))


def test_parse_salary_csv_statuses_and_bom():
    text = (FIX / "dk_salaries_sample.csv").read_bytes().decode("utf-8")
    pool = dk_salaries.parse_salary_csv(text)
    assert list(pool.columns) == ["dk_id", "name", "position", "salary", "team", "opp", "game_id",
                                  "is_home", "kickoff", "dk_avg", "status", "playable"]
    puka = pool[pool.name == "Puka Nacua"].iloc[0]
    assert puka.dk_id == 44475972 and puka.salary == 8100 and puka.team == "LAR"
    assert puka.opp == "ARI" and puka.game_id == "ARI@LAR" and bool(puka.is_home)
    assert puka.kickoff == pd.Timestamp("2026-10-18 16:05") and puka.status == "Q"
    assert dict(zip(pool.name, pool.playable)) == {
        "Bijan Robinson": True, "Puka Nacua": True, "Some Quarterback": False,
        "Some Tightend": False, "Doubtful Receiver": False, "Rams": True}
    assert pool[pool.name == "Bijan Robinson"].status.iloc[0] == ""


def test_parse_salary_csv_rejects_wrong_file():
    with pytest.raises(ValueError, match="missing columns"):
        dk_salaries.parse_salary_csv("a,b\n1,2\n")


class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class _Session:
    def __init__(self, resp):
        self.resp, self.urls = resp, []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.resp


def test_fetch_salary_csv_builds_url_and_returns_text():
    s = _Session(_Resp("﻿Position,Name + ID\n"))
    text = dk_salaries.fetch_salary_csv({"draft_group_id": 154941, "contest_type_id": 21}, session=s)
    assert text.startswith("Position")
    assert s.urls == ["https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId=154941"]


def test_fetch_salary_csv_rejects_html():
    s = _Session(_Resp("<HTML><HEAD><TITLE>Access Denied</TITLE>"))
    with pytest.raises(RuntimeError, match="DKSalaries.csv"):
        dk_salaries.fetch_salary_csv({"draft_group_id": 1, "contest_type_id": 21}, session=s)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./py -m pytest tests/test_dk_salaries.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 4: Implement `nfldfs/dk_salaries.py`**

```python
"""DraftKings salaries: find the Sunday main slate in the lobby, download its official CSV, parse it."""
from __future__ import annotations

import datetime as dt
import io

import numpy as np
import pandas as pd
import requests

from .teams import to_dk_team

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NFL"
CSV_URL = ("https://www.draftkings.com/lineup/getavailableplayerscsv"
           "?contestTypeId={contest_type_id}&draftGroupId={draft_group_id}")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CLASSIC_GAME_TYPE_ID = 1
PLAYABLE_STATUSES = {"", "Q", "P"}
REQUIRED_COLUMNS = ["Position", "Name", "ID", "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame", "Status"]


def find_main_slate(lobby: dict, today: dt.date) -> dict:
    """Earliest upcoming Sunday 1:00 PM ET Classic draft group with the most games."""
    rows = []
    for g in lobby.get("DraftGroups", []):
        if g.get("GameTypeId") != CLASSIC_GAME_TYPE_ID:
            continue
        start = dt.datetime.fromisoformat(g["StartDateEst"][:19])
        if start.date() < today or start.weekday() != 6 or (start.hour, start.minute) != (13, 0):
            continue
        rows.append(((start.date(), -int(g.get("GameCount", 0)), g.get("DraftGroupTag") != "Featured"), g, start))
    if not rows:
        raise LookupError("No Sunday 1:00 PM Classic main slate found in the DraftKings lobby")
    rows.sort(key=lambda r: r[0])
    _, g, start = rows[0]
    return {"draft_group_id": int(g["DraftGroupId"]), "contest_type_id": int(g["ContestTypeId"]),
            "start": start.isoformat(), "game_count": int(g["GameCount"])}


def fetch_lobby(session=None) -> dict:
    s = session or requests.Session()
    r = s.get(LOBBY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_salary_csv(slate: dict, session=None) -> str:
    s = session or requests.Session()
    r = s.get(CSV_URL.format(**slate), headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text.lstrip("﻿")
    if not text.startswith("Position"):
        raise RuntimeError("DraftKings returned something other than the salary CSV (it may be blocking "
                           "automated downloads). Download DKSalaries.csv from any main-slate contest "
                           "and run with --salary-csv PATH.")
    return text


def parse_salary_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text.lstrip("﻿")), keep_default_na=False, dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DraftKings salary file is missing columns: {missing}")
    game = df["Game Info"].str.extract(r"^(?P<away>[A-Z]+)@(?P<home>[A-Z]+) (?P<date>\S+) (?P<time>\S+)")
    bad = game["away"].isna()
    if bad.any():
        raise ValueError(f"Unreadable 'Game Info' for: {df.loc[bad, 'Name'].tolist()[:5]}")
    out = pd.DataFrame({
        "dk_id": df["ID"].astype("int64"),
        "name": df["Name"].str.strip(),
        "position": df["Position"].str.strip(),
        "salary": df["Salary"].astype(int),
        "team": df["TeamAbbrev"].map(to_dk_team),
    })
    away, home = game["away"].map(to_dk_team), game["home"].map(to_dk_team)
    out["is_home"] = out["team"] == home
    out["opp"] = np.where(out["is_home"], away, home)
    out["game_id"] = away + "@" + home
    out["kickoff"] = pd.to_datetime(game["date"] + " " + game["time"], format="%m/%d/%Y %I:%M%p")
    out["dk_avg"] = pd.to_numeric(df["AvgPointsPerGame"], errors="coerce").fillna(0.0)
    out["status"] = df["Status"].str.strip().str.upper()
    out["playable"] = out["status"].isin(PLAYABLE_STATUSES)
    return out[["dk_id", "name", "position", "salary", "team", "opp", "game_id",
                "is_home", "kickoff", "dk_avg", "status", "playable"]]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_dk_salaries.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Live smoke check (read-only, two requests)**

```bash
./py -c "
import datetime as dt
from nfldfs import dk_salaries as d
slate = d.find_main_slate(d.fetch_lobby(), dt.date.today()); print(slate)
pool = d.parse_salary_csv(d.fetch_salary_csv(slate))
print(len(pool), pool.position.value_counts().to_dict(), pool.playable.mean().round(2))
"
```
Expected: a slate dict with ~10–13 games, ~400–550 players, all five positions present. If DK returns HTML, the RuntimeError message appears — report it; the CSV-upload path still covers this.

- [ ] **Step 7: Commit**

```bash
git add nfldfs/dk_salaries.py tests/test_dk_salaries.py tests/fixtures/lobby_sample.json tests/fixtures/dk_salaries_sample.csv
git commit -m "Add DraftKings main-slate finder and salary CSV parser" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Vegas lines → implied team totals

**Files:**
- Create: `nfldfs/vegas.py`, `tests/test_vegas.py`, `tests/fixtures/odds_sample.json`

**Interfaces:**
- Consumes: `teams.ODDS_API_NAMES`.
- Produces: `fetch_odds(api_key, session=None) -> tuple[list[dict], str | None]` (events, requests-remaining header); `parse_odds(events) -> DataFrame[game_id, home, away, total, home_spread, n_books, commence_time]` (home_spread < 0 means home favored; medians across books); `implied_totals(games) -> DataFrame[team, opp, game_id, implied_total, exp_margin]` (exp_margin > 0 means that team is favored).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/odds_sample.json`:
```json
[
  {"id": "e1", "commence_time": "2026-10-18T20:05:00Z", "home_team": "Los Angeles Rams", "away_team": "Arizona Cardinals",
   "bookmakers": [
     {"key": "draftkings", "markets": [
       {"key": "totals", "outcomes": [{"name": "Over", "point": 47.5, "price": -110}, {"name": "Under", "point": 47.5, "price": -110}]},
       {"key": "spreads", "outcomes": [{"name": "Los Angeles Rams", "point": -3.5, "price": -110}, {"name": "Arizona Cardinals", "point": 3.5, "price": -110}]}]},
     {"key": "fanduel", "markets": [
       {"key": "totals", "outcomes": [{"name": "Over", "point": 48.5, "price": -110}, {"name": "Under", "point": 48.5, "price": -110}]},
       {"key": "spreads", "outcomes": [{"name": "Los Angeles Rams", "point": -2.5, "price": -110}, {"name": "Arizona Cardinals", "point": 2.5, "price": -110}]}]}
   ]},
  {"id": "e2", "commence_time": "2026-10-18T17:00:00Z", "home_team": "Atlanta Falcons", "away_team": "Chicago Bears",
   "bookmakers": [
     {"key": "draftkings", "markets": [
       {"key": "totals", "outcomes": [{"name": "Over", "point": 44.0, "price": -110}, {"name": "Under", "point": 44.0, "price": -110}]},
       {"key": "spreads", "outcomes": [{"name": "Atlanta Falcons", "point": 1.5, "price": -110}, {"name": "Chicago Bears", "point": -1.5, "price": -110}]}]}
   ]},
  {"id": "e3", "commence_time": "2026-10-18T17:00:00Z", "home_team": "London Monarchs", "away_team": "Chicago Bears", "bookmakers": []}
]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_vegas.py`:
```python
import json
from pathlib import Path

import pytest

from nfldfs import vegas

FIX = Path(__file__).parent / "fixtures"


def _games():
    return vegas.parse_odds(json.loads((FIX / "odds_sample.json").read_text()))


def test_parse_odds_takes_median_and_skips_unknown_or_empty():
    g = _games()
    assert sorted(g.game_id) == ["ARI@LAR", "CHI@ATL"]
    rams = g[g.game_id == "ARI@LAR"].iloc[0]
    assert rams.total == pytest.approx(48.0) and rams.home_spread == pytest.approx(-3.0) and rams.n_books == 2


def test_implied_totals_split_total_by_spread():
    it = _games().pipe(vegas.implied_totals).set_index("team")
    assert it.loc["LAR", "implied_total"] == pytest.approx(25.5)
    assert it.loc["ARI", "implied_total"] == pytest.approx(22.5)
    assert it.loc["LAR", "exp_margin"] == pytest.approx(3.0)
    assert it.loc["ARI", "exp_margin"] == pytest.approx(-3.0)
    assert it.loc["ATL", "implied_total"] == pytest.approx(21.25)   # home underdog by 1.5
    assert it.loc["CHI", "opp"] == "ATL" and it.loc["CHI", "game_id"] == "CHI@ATL"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./py -m pytest tests/test_vegas.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 4: Implement `nfldfs/vegas.py`**

```python
"""The Odds API → consensus game lines → implied team totals."""
from __future__ import annotations

import statistics

import pandas as pd
import requests

from .teams import ODDS_API_NAMES

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"


def fetch_odds(api_key: str, session=None) -> tuple[list[dict], str | None]:
    """One request (costs 2 quota units: spreads + totals, US region)."""
    s = session or requests.Session()
    r = s.get(ODDS_URL, params={"apiKey": api_key, "regions": "us", "markets": "spreads,totals",
                                "oddsFormat": "american"}, timeout=30)
    r.raise_for_status()
    return r.json(), r.headers.get("x-requests-remaining")


def parse_odds(events: list[dict]) -> pd.DataFrame:
    rows = []
    for ev in events:
        home, away = ODDS_API_NAMES.get(ev.get("home_team")), ODDS_API_NAMES.get(ev.get("away_team"))
        if not home or not away:
            continue
        totals, spreads = [], []
        for book in ev.get("bookmakers", []):
            for m in book.get("markets", []):
                if m["key"] == "totals":
                    over = next((o for o in m["outcomes"] if o["name"] == "Over"), None)
                    if over is not None:
                        totals.append(float(over["point"]))
                elif m["key"] == "spreads":
                    h = next((o for o in m["outcomes"] if o["name"] == ev["home_team"]), None)
                    if h is not None:
                        spreads.append(float(h["point"]))
        if not totals or not spreads:
            continue
        rows.append({"game_id": f"{away}@{home}", "home": home, "away": away,
                     "total": statistics.median(totals), "home_spread": statistics.median(spreads),
                     "n_books": min(len(totals), len(spreads)), "commence_time": ev.get("commence_time")})
    cols = ["game_id", "home", "away", "total", "home_spread", "n_books", "commence_time"]
    return pd.DataFrame(rows, columns=cols).sort_values("commence_time").reset_index(drop=True)


def implied_totals(games: pd.DataFrame) -> pd.DataFrame:
    """Home implied = (total - home_spread)/2; away = (total + home_spread)/2."""
    home = pd.DataFrame({"team": games.home, "opp": games.away, "game_id": games.game_id,
                         "implied_total": (games.total - games.home_spread) / 2,
                         "exp_margin": -games.home_spread})
    away = pd.DataFrame({"team": games.away, "opp": games.home, "game_id": games.game_id,
                         "implied_total": (games.total + games.home_spread) / 2,
                         "exp_margin": games.home_spread})
    return pd.concat([home, away], ignore_index=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_vegas.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add nfldfs/vegas.py tests/test_vegas.py tests/fixtures/odds_sample.json
git commit -m "Add Vegas consensus lines and implied team totals" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: nflverse stats and the team-environment model

**Files:**
- Create: `nfldfs/nfl_stats.py`, `nfldfs/team_env.py`, `tests/test_nfl_stats.py`, `tests/test_team_env.py`

**Interfaces:**
- Consumes: `teams.to_dk_team`, `dk_rules.offense_points`.
- Produces: `nfl_stats.normalize_player_stats(raw) -> DataFrame[player_id, name, position, team, season, week, pass_att, pass_yds, pass_td, ints, carries, rush_yds, rush_td, targets, receptions, rec_yds, rec_td, fumbles_lost, two_pt, dk_pts]` (REG season, QB/RB/WR/TE only, DK team codes); `team_week_totals(player_weeks) -> DataFrame[season, week, team, pass_att, pass_yds, pass_td, ints, targets, carries, rush_yds, rush_td]`; `normalize_schedules(raw) -> DataFrame[season, week, team, opp, is_home, implied_total, exp_margin, points]`; `load_raw(seasons) -> tuple[DataFrame, DataFrame]` (player stats, schedules — network).
- Produces: `team_env.TEAM_STATS` tuple; `build_training_frame(team_weeks, schedule_rows) -> DataFrame`; `fit_team_model(frame) -> dict{"coef": {stat: [a, b_implied, c_margin]}, "n_games": int}`; `expected_team_stats(implied: DataFrame[team, implied_total, exp_margin], model) -> DataFrame[team, exp_pass_att, exp_pass_yds, exp_pass_td, exp_ints, exp_carries, exp_rush_yds, exp_rush_td]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_nfl_stats.py`:
```python
import pandas as pd
import pytest

from nfldfs import nfl_stats


def _raw_stats():
    return pd.DataFrame({
        "player_id": ["00-1", "00-2", "00-3"], "player_display_name": ["Puka Nacua", "Matthew Stafford", "Some Kicker"],
        "position": ["WR", "QB", "K"], "recent_team": ["LA", "LA", "LA"], "season": [2026] * 3, "week": [5] * 3,
        "season_type": ["REG"] * 3, "attempts": [0, 35, 0], "passing_yards": [0, 310, 0], "passing_tds": [0, 2, 0],
        "interceptions": [0, 1, 0], "carries": [1, 2, 0], "rushing_yards": [5, 3, 0], "rushing_tds": [0, 0, 0],
        "targets": [9, 0, 0], "receptions": [7, 0, 0], "receiving_yards": [95, 0, 0], "receiving_tds": [1, 0, 0],
        "sack_fumbles_lost": [0, 1, 0], "rushing_fumbles_lost": [0, 0, 0],
    })


def test_normalize_player_stats_handles_aliases_and_scores():
    ps = nfl_stats.normalize_player_stats(_raw_stats())
    assert list(ps.name) == ["Puka Nacua", "Matthew Stafford"]          # kicker dropped
    assert set(ps.team) == {"LAR"}
    by = ps.set_index("name")
    assert by.loc["Puka Nacua", "dk_pts"] == pytest.approx(23.0)
    assert by.loc["Matthew Stafford", "dk_pts"] == pytest.approx(21.7)
    assert by.loc["Matthew Stafford", "ints"] == 1 and by.loc["Matthew Stafford", "fumbles_lost"] == 1


def test_normalize_player_stats_errors_clearly_on_schema_change():
    with pytest.raises(KeyError, match="targets"):
        nfl_stats.normalize_player_stats(_raw_stats().drop(columns=["targets"]))


def test_team_week_totals_sums_players():
    tw = nfl_stats.team_week_totals(nfl_stats.normalize_player_stats(_raw_stats()))
    row = tw.iloc[0]
    assert (row.team, row.pass_att, row.pass_yds, row.targets, row.carries, row.rush_yds) == ("LAR", 35, 310, 9, 3, 8)


def test_normalize_schedules_uses_nflverse_spread_convention():
    raw = pd.DataFrame({"season": [2026], "week": [5], "game_type": ["REG"], "home_team": ["LA"],
                        "away_team": ["ARI"], "home_score": [27], "away_score": [20],
                        "total_line": [47.0], "spread_line": [3.0]})
    s = nfl_stats.normalize_schedules(raw).set_index("team")
    assert s.loc["LAR", "implied_total"] == pytest.approx(25.0) and s.loc["LAR", "exp_margin"] == 3.0
    assert s.loc["ARI", "implied_total"] == pytest.approx(22.0) and s.loc["ARI", "points"] == 20
    assert bool(s.loc["LAR", "is_home"]) and s.loc["ARI", "opp"] == "LAR"
```

`tests/test_team_env.py`:
```python
import numpy as np
import pandas as pd
import pytest

from nfldfs import team_env


def _frame(n=300, seed=0):
    rng = np.random.default_rng(seed)
    it = rng.uniform(14, 32, n)
    m = rng.uniform(-10, 10, n)
    f = pd.DataFrame({"implied_total": it, "exp_margin": m})
    f["pass_att"] = 20 + 0.5 * it - 0.3 * m
    f["pass_yds"] = 100 + 5 * it - 2 * m
    f["pass_td"] = 0.07 * it
    f["ints"] = 0.8 + 0 * it
    f["carries"] = 15 + 0.4 * it + 0.3 * m
    f["rush_yds"] = 60 + 2.5 * it + 1 * m
    f["rush_td"] = 0.04 * it
    return f


def test_fit_recovers_exact_linear_relationships():
    model = team_env.fit_team_model(_frame())
    assert model["n_games"] == 300
    assert np.allclose(model["coef"]["pass_yds"], [100, 5, -2], atol=1e-6)
    assert np.allclose(model["coef"]["carries"], [15, 0.4, 0.3], atol=1e-6)


def test_fit_refuses_tiny_samples():
    with pytest.raises(ValueError, match="at least 50"):
        team_env.fit_team_model(_frame(n=10))


def test_expected_team_stats_clips_and_names_columns():
    model = team_env.fit_team_model(_frame())
    out = team_env.expected_team_stats(pd.DataFrame({"team": ["LAR", "XXX"], "implied_total": [25.0, 0.0],
                                                     "exp_margin": [3.0, -40.0]}), model)
    assert list(out.columns) == ["team"] + [f"exp_{s}" for s in team_env.TEAM_STATS]
    assert out.iloc[0].exp_pass_yds == pytest.approx(100 + 5 * 25 - 2 * 3)
    assert (out.drop(columns="team") > 0).all().all()


def test_build_training_frame_joins_on_team_week():
    tw = pd.DataFrame({"season": [2026], "week": [5], "team": ["LAR"], "pass_att": [35], "pass_yds": [310],
                       "pass_td": [2], "ints": [1], "targets": [33], "carries": [25], "rush_yds": [110], "rush_td": [1]})
    sched = pd.DataFrame({"season": [2026, 2026], "week": [5, 5], "team": ["LAR", "ARI"], "opp": ["ARI", "LAR"],
                          "is_home": [True, False], "implied_total": [25.0, 22.0], "exp_margin": [3.0, -3.0],
                          "points": [27, 20]})
    f = team_env.build_training_frame(tw, sched)
    assert len(f) == 1 and f.iloc[0].implied_total == 25.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_nfl_stats.py tests/test_team_env.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/nfl_stats.py`**

```python
"""nflverse (via nflreadpy) → normalized weekly player stats, team-week totals, schedule lines."""
from __future__ import annotations

import pandas as pd

from .dk_rules import offense_points
from .teams import to_dk_team

# nflverse has renamed columns across releases; the first name present wins.
_ALIASES = {
    "player_id": ["player_id"], "name": ["player_display_name", "player_name"], "position": ["position"],
    "team": ["team", "recent_team"], "season": ["season"], "week": ["week"],
    "pass_att": ["attempts"], "pass_yds": ["passing_yards"], "pass_td": ["passing_tds"],
    "ints": ["passing_interceptions", "interceptions"],
    "carries": ["carries"], "rush_yds": ["rushing_yards"], "rush_td": ["rushing_tds"],
    "targets": ["targets"], "receptions": ["receptions"], "rec_yds": ["receiving_yards"], "rec_td": ["receiving_tds"],
}
_SUMMED = {
    "fumbles_lost": ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"],
    "two_pt": ["passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"],
}
_TEXT = ("player_id", "name", "position", "team")
KEEP_POSITIONS = ("QB", "RB", "WR", "TE")
TEAM_WEEK_COLUMNS = ["pass_att", "pass_yds", "pass_td", "ints", "targets", "carries", "rush_yds", "rush_td"]


def _first(raw: pd.DataFrame, out_name: str, names: list[str]) -> pd.Series:
    for n in names:
        if n in raw.columns:
            return raw[n]
    raise KeyError(f"nflverse player stats have none of {names} (needed for '{out_name}'); "
                   f"available columns: {sorted(raw.columns)}")


def normalize_player_stats(raw: pd.DataFrame) -> pd.DataFrame:
    if "season_type" in raw.columns:
        raw = raw[raw["season_type"] == "REG"]
    raw = raw.reset_index(drop=True)
    out = pd.DataFrame({k: _first(raw, k, v) for k, v in _ALIASES.items()})
    for k, cols in _SUMMED.items():
        present = [c for c in cols if c in raw.columns]
        out[k] = raw[present].fillna(0).sum(axis=1) if present else 0
    num = [c for c in out.columns if c not in _TEXT]
    out[num] = out[num].apply(pd.to_numeric, errors="coerce").fillna(0)
    out["position"] = out["position"].replace({"FB": "RB"})
    out = out[out["position"].isin(KEEP_POSITIONS)].copy()
    out["team"] = out["team"].map(to_dk_team)
    out["dk_pts"] = offense_points(out.pass_yds, out.pass_td, out.ints, out.rush_yds, out.rush_td,
                                   out.receptions, out.rec_yds, out.rec_td, out.fumbles_lost, out.two_pt)
    return out.reset_index(drop=True)


def team_week_totals(player_weeks: pd.DataFrame) -> pd.DataFrame:
    return (player_weeks.groupby(["season", "week", "team"], as_index=False)[TEAM_WEEK_COLUMNS].sum())


def normalize_schedules(raw: pd.DataFrame) -> pd.DataFrame:
    """nflverse spread_line is positive when the HOME team is favored."""
    g = raw[(raw["game_type"] == "REG") & raw["total_line"].notna() & raw["spread_line"].notna()
            & raw["home_score"].notna()].copy()
    home, away = g["home_team"].map(to_dk_team), g["away_team"].map(to_dk_team)
    h = pd.DataFrame({"season": g.season, "week": g.week, "team": home, "opp": away, "is_home": True,
                      "implied_total": (g.total_line + g.spread_line) / 2, "exp_margin": g.spread_line,
                      "points": g.home_score})
    a = pd.DataFrame({"season": g.season, "week": g.week, "team": away, "opp": home, "is_home": False,
                      "implied_total": (g.total_line - g.spread_line) / 2, "exp_margin": -g.spread_line,
                      "points": g.away_score})
    return pd.concat([h, a], ignore_index=True)


def load_raw(seasons: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    import nflreadpy as nfl  # imported lazily: network + heavy dependency
    stats = nfl.load_player_stats(seasons, summary_level="week").to_pandas()
    sched = nfl.load_schedules(seasons).to_pandas()
    return stats, sched
```

- [ ] **Step 4: Implement `nfldfs/team_env.py`**

```python
"""Vegas implied total + expected margin → expected team passing/rushing volume and TDs."""
from __future__ import annotations

import numpy as np
import pandas as pd

TEAM_STATS = ("pass_att", "pass_yds", "pass_td", "ints", "carries", "rush_yds", "rush_td")
MIN_TRAINING_GAMES = 50


def build_training_frame(team_weeks: pd.DataFrame, schedule_rows: pd.DataFrame) -> pd.DataFrame:
    return team_weeks.merge(schedule_rows[["season", "week", "team", "implied_total", "exp_margin"]],
                            on=["season", "week", "team"], how="inner")


def fit_team_model(frame: pd.DataFrame) -> dict:
    if len(frame) < MIN_TRAINING_GAMES:
        raise ValueError(f"need at least {MIN_TRAINING_GAMES} team-games with Vegas lines to fit, got {len(frame)}")
    X = np.column_stack([np.ones(len(frame)), frame.implied_total, frame.exp_margin])
    coef = {s: np.linalg.lstsq(X, frame[s].to_numpy(float), rcond=None)[0].round(6).tolist() for s in TEAM_STATS}
    return {"coef": coef, "n_games": int(len(frame))}


def expected_team_stats(implied: pd.DataFrame, model: dict) -> pd.DataFrame:
    out = pd.DataFrame({"team": implied.team.to_numpy()})
    for s in TEAM_STATS:
        a, b, c = model["coef"][s]
        out[f"exp_{s}"] = np.clip(a + b * implied.implied_total.to_numpy() + c * implied.exp_margin.to_numpy(),
                                  0.01, None)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_nfl_stats.py tests/test_team_env.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Live schema check against real nflverse data**

```bash
./py -c "
from nfldfs import nfl_stats as n, team_env as t
raw, sched = n.load_raw([2025, 2026])
pw = n.normalize_player_stats(raw); tw = n.team_week_totals(pw); s = n.normalize_schedules(sched)
m = t.fit_team_model(t.build_training_frame(tw, s))
print(len(pw), pw.season.max(), pw[pw.season==2026].week.max()); print(m)
"
```
Expected: tens of thousands of player-weeks, latest 2026 week = last completed week, and a model whose `pass_yds` implied-total coefficient is positive (~4–8) and `rush_yds` margin coefficient positive (favorites run more). **If a `KeyError` names a missing column**, add the new nflverse column name to the front of that entry's alias list in `_ALIASES` and re-run Steps 5–6.

- [ ] **Step 7: Commit**

```bash
git add nfldfs/nfl_stats.py nfldfs/team_env.py tests/test_nfl_stats.py tests/test_team_env.py
git commit -m "Add nflverse stat normalization and Vegas-driven team environment model" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Player usage shares, name matching, injury redistribution

**Files:**
- Create: `nfldfs/shares.py`, `tests/test_shares.py`

**Interfaces:**
- Consumes: `teams.normalize_name`; player-week and team-week frames from Task 5.
- Produces: `SHARE_COLUMNS = ("tgt_share", "carry_share", "catch_rate", "ypt", "ypc")`; `compute_shares(player_weeks, team_weeks, *, n_games=6, half_life=3.0, k=2.0) -> DataFrame[player_id, name, position, team, games, n_eff, *SHARE_COLUMNS]`; `attach_shares(pool, shares) -> pool + SHARE_COLUMNS + matched(bool)`; `redistribute(pool) -> pool` (OUT players' shares moved to playable same-team same-position players; team totals capped at 0.97).

- [ ] **Step 1: Write the failing tests**

`tests/test_shares.py`:
```python
import numpy as np
import pandas as pd
import pytest

from nfldfs import shares


def _weeks(n=6, player_targets=10, team_targets=40):
    pw = pd.DataFrame({"player_id": "P1", "name": "Kenneth Walker", "position": "WR", "team": "KC",
                       "season": 2026, "week": range(1, n + 1), "targets": player_targets, "receptions": 6,
                       "rec_yds": 80.0, "carries": 0, "rush_yds": 0.0})
    tw = pd.DataFrame({"season": 2026, "week": range(1, n + 1), "team": "KC",
                       "targets": team_targets, "carries": 25})
    return pw, tw


def test_compute_shares_recency_weighted_and_shrunk():
    pw, tw = _weeks()
    s = shares.compute_shares(pw, tw).iloc[0]
    n_eff = sum(0.5 ** (age / 3.0) for age in range(6))
    expected = (n_eff * 0.25 + 2.0 * shares.POSITION_PRIORS["WR"]["tgt_share"]) / (n_eff + 2.0)
    assert s.tgt_share == pytest.approx(expected, rel=1e-6)
    assert s.games == 6 and s.n_eff == pytest.approx(n_eff)
    assert s.catch_rate == pytest.approx((36 + 10 * 0.64) / (60 + 10))


def test_compute_shares_uses_only_last_n_games():
    pw, tw = _weeks(n=10)
    pw.loc[pw.week <= 4, "targets"] = 0          # old weeks outside the window must not count
    s = shares.compute_shares(pw, tw, n_games=6).iloc[0]
    assert s.games == 6 and s.tgt_share > 0.2


def _pool(rows):
    base = dict(position="WR", team="KC", playable=True)
    return pd.DataFrame([{**base, **r} for r in rows])


def test_suffix_name_matches():
    pw, tw = _weeks()
    out = shares.attach_shares(_pool([{"name": "Kenneth Walker III"}]), shares.compute_shares(pw, tw))
    assert bool(out.matched.iloc[0]) and out.tgt_share.iloc[0] > 0.2


def test_unmatched_player_gets_fallback_shares():
    pw, tw = _weeks()
    out = shares.attach_shares(_pool([{"name": "Brand New Rookie"}, {"name": "Chiefs", "position": "DST"}]),
                               shares.compute_shares(pw, tw))
    rookie, dst = out.iloc[0], out.iloc[1]
    assert not bool(rookie.matched)
    assert rookie.tgt_share == shares.UNKNOWN_PLAYER_SHARE["WR"]["tgt_share"]
    assert rookie.ypt == shares.EFFICIENCY_PRIORS["ypt"]["WR"]
    assert bool(dst.matched) and dst.tgt_share == 0.0 and dst.carry_share == 0.0


def test_redistribute_moves_out_wr_targets_to_teammates():
    pool = _pool([{"name": "A", "tgt_share": 0.3, "carry_share": 0.0, "playable": False},
                  {"name": "B", "tgt_share": 0.2, "carry_share": 0.0},
                  {"name": "C", "tgt_share": 0.1, "carry_share": 0.0}])
    out = shares.redistribute(pool).set_index("name")
    assert out.loc["A", "tgt_share"] == 0.0
    assert out.loc["B", "tgt_share"] == pytest.approx(0.4)
    assert out.loc["C", "tgt_share"] == pytest.approx(0.2)


def test_redistribute_moves_out_qb_carries_to_backup():
    pool = _pool([{"name": "Starter", "position": "QB", "tgt_share": 0.0, "carry_share": 0.12, "playable": False},
                  {"name": "Backup", "position": "QB", "tgt_share": 0.0, "carry_share": 0.0}])
    out = shares.redistribute(pool).set_index("name")
    assert out.loc["Backup", "carry_share"] == pytest.approx(0.12) and out.loc["Starter", "carry_share"] == 0.0


def test_redistribute_caps_team_total():
    pool = _pool([{"name": n, "tgt_share": 0.4, "carry_share": 0.0} for n in "XYZ"])
    out = shares.redistribute(pool)
    assert out.tgt_share.sum() == pytest.approx(shares.MAX_TEAM_SHARE)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_shares.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/shares.py`**

```python
"""Per-player usage shares (targets, carries) and efficiency, matched onto the DraftKings pool."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .teams import normalize_name

SHARE_COLUMNS = ("tgt_share", "carry_share", "catch_rate", "ypt", "ypc")
POSITION_PRIORS = {
    "QB": {"tgt_share": 0.0, "carry_share": 0.10},
    "RB": {"tgt_share": 0.06, "carry_share": 0.25},
    "WR": {"tgt_share": 0.12, "carry_share": 0.01},
    "TE": {"tgt_share": 0.09, "carry_share": 0.0},
}
# Players DraftKings lists that have no nflverse history (rookies, call-ups): small, conservative roles.
UNKNOWN_PLAYER_SHARE = {
    "QB": {"tgt_share": 0.0, "carry_share": 0.05},
    "RB": {"tgt_share": 0.02, "carry_share": 0.05},
    "WR": {"tgt_share": 0.03, "carry_share": 0.0},
    "TE": {"tgt_share": 0.02, "carry_share": 0.0},
}
EFFICIENCY_PRIORS = {
    "catch_rate": {"QB": 0.0, "RB": 0.78, "WR": 0.64, "TE": 0.70},
    "ypt": {"QB": 0.0, "RB": 6.0, "WR": 8.3, "TE": 7.2},
    "ypc": {"QB": 5.0, "RB": 4.3, "WR": 7.0, "TE": 4.0},
}
MAX_TEAM_SHARE = 0.97


def compute_shares(player_weeks: pd.DataFrame, team_weeks: pd.DataFrame, *, n_games: int = 6,
                   half_life: float = 3.0, k: float = 2.0) -> pd.DataFrame:
    tw = team_weeks[["season", "week", "team", "targets", "carries"]].rename(
        columns={"targets": "team_targets", "carries": "team_carries"})
    df = player_weeks.merge(tw, on=["season", "week", "team"], how="left").fillna(
        {"team_targets": 0, "team_carries": 0})
    df = df.sort_values(["player_id", "season", "week"])
    df["age"] = df.groupby("player_id").cumcount(ascending=False)
    df = df[df.age < n_games].copy()
    df["w"] = 0.5 ** (df.age / half_life)
    for c in ("targets", "team_targets", "carries", "team_carries"):
        df[f"w_{c}"] = df.w * df[c]
    g = df.groupby("player_id").agg(
        name=("name", "last"), position=("position", "last"), team=("team", "last"),
        games=("w", "size"), n_eff=("w", "sum"),
        w_targets=("w_targets", "sum"), w_team_targets=("w_team_targets", "sum"),
        w_carries=("w_carries", "sum"), w_team_carries=("w_team_carries", "sum"),
        targets=("targets", "sum"), receptions=("receptions", "sum"), rec_yds=("rec_yds", "sum"),
        carries=("carries", "sum"), rush_yds=("rush_yds", "sum"),
    ).reset_index()
    prior = lambda key: g.position.map(lambda p: POSITION_PRIORS[p][key])
    eff = lambda key: g.position.map(EFFICIENCY_PRIORS[key])
    obs_t = np.where(g.w_team_targets > 0, g.w_targets / g.w_team_targets.where(g.w_team_targets > 0, 1), 0.0)
    obs_c = np.where(g.w_team_carries > 0, g.w_carries / g.w_team_carries.where(g.w_team_carries > 0, 1), 0.0)
    g["tgt_share"] = (g.n_eff * obs_t + k * prior("tgt_share")) / (g.n_eff + k)
    g["carry_share"] = (g.n_eff * obs_c + k * prior("carry_share")) / (g.n_eff + k)
    g["catch_rate"] = (g.receptions + 10 * eff("catch_rate")) / (g.targets + 10)
    g["ypt"] = (g.rec_yds + 20 * eff("ypt")) / (g.targets + 20)
    g["ypc"] = (g.rush_yds + 20 * eff("ypc")) / (g.carries + 20)
    return g[["player_id", "name", "position", "team", "games", "n_eff", *SHARE_COLUMNS]]


def attach_shares(pool: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """Match on (normalized name, team, position), then (normalized name, position)."""
    by_team, by_pos = {}, {}
    for r in shares.itertuples(index=False):
        key = normalize_name(r.name)
        vals = {c: getattr(r, c) for c in SHARE_COLUMNS}
        by_team.setdefault((key, r.team, r.position), vals)
        by_pos.setdefault((key, r.position), vals)
    rows = []
    for r in pool.itertuples(index=False):
        if r.position == "DST":
            rows.append({**{c: 0.0 for c in SHARE_COLUMNS}, "matched": True})
            continue
        key = normalize_name(r.name)
        vals = by_team.get((key, r.team, r.position)) or by_pos.get((key, r.position))
        if vals is None:
            vals = {**UNKNOWN_PLAYER_SHARE[r.position],
                    **{c: EFFICIENCY_PRIORS[c][r.position] for c in ("catch_rate", "ypt", "ypc")}}
            rows.append({**vals, "matched": False})
        else:
            rows.append({**vals, "matched": True})
    extra = pd.DataFrame(rows, index=pool.index)
    return pd.concat([pool.drop(columns=[c for c in (*SHARE_COLUMNS, "matched") if c in pool.columns]), extra],
                     axis=1)


def redistribute(pool: pd.DataFrame) -> pd.DataFrame:
    pool = pool.copy()
    for _, idx in pool.groupby("team").groups.items():
        sub = pool.loc[idx]
        for col in ("tgt_share", "carry_share"):
            for pos in ("QB", "RB", "WR", "TE"):
                m_pos = sub.position == pos
                out = m_pos & ~sub.playable
                lost = float(sub.loc[out, col].sum())
                recv = m_pos & sub.playable
                if lost > 0 and recv.any():
                    base = sub.loc[recv, col]
                    w = base / base.sum() if base.sum() > 0 else pd.Series(1.0 / len(base), index=base.index)
                    pool.loc[base.index, col] = base + lost * w
                pool.loc[sub.index[out.to_numpy()], col] = 0.0
            total = float(pool.loc[idx, col].sum())
            if total > MAX_TEAM_SHARE:
                pool.loc[idx, col] = pool.loc[idx, col] * (MAX_TEAM_SHARE / total)
    return pool
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_shares.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add nfldfs/shares.py tests/test_shares.py
git commit -m "Add player usage shares with shrinkage, name matching and injury redistribution" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Monte Carlo simulation

**Files:**
- Create: `nfldfs/simulate.py`, `tests/test_simulate.py`
- Modify: `tests/conftest.py` (add `team_exp` fixture)

**Interfaces:**
- Consumes: `dk_rules.offense_points`, `dk_rules.dst_points`; pool columns `dk_id, position, salary, team, opp, game_id, playable, tgt_share, carry_share, catch_rate, ypt, ypc`; `team_exp` DataFrame indexed by team with `exp_pass_att, exp_pass_yds, exp_pass_td, exp_ints, exp_carries, exp_rush_yds, exp_rush_td` (Task 5 output, `set_index("team")`).
- Produces: `simulate(pool, team_exp, n_sims, seed) -> np.ndarray float32 (n_sims, len(pool))` — column j is pool row j (pool must have a RangeIndex); `starting_qbs(pool) -> dict[team, row_index]`; `summarize(sims, pool) -> DataFrame[mean, floor, median, ceiling, boom_rate]` indexed like pool (floor = p20, ceiling = p85, boom = P(pts ≥ 3 × salary/1000)).

- [ ] **Step 1: Add the `team_exp` fixture to `tests/conftest.py`**

Append:
```python
@pytest.fixture
def team_exp() -> pd.DataFrame:
    return pd.DataFrame({
        "team": ["AAA", "BBB", "CCC", "DDD"],
        "exp_pass_att": 34.0, "exp_pass_yds": 240.0, "exp_pass_td": 1.6, "exp_ints": 0.8,
        "exp_carries": 26.0, "exp_rush_yds": 115.0, "exp_rush_td": 0.9,
    }).set_index("team")
```

- [ ] **Step 2: Write the failing tests**

`tests/test_simulate.py`:
```python
import numpy as np
import pytest

from nfldfs import simulate


def _col(pool, team, name):
    return int(pool.index[(pool.team == team) & (pool["name"] == f"{team} {name}")][0])


def test_shape_dtype_and_determinism(pool, team_exp):
    a = simulate.simulate(pool, team_exp, 500, seed=1)
    b = simulate.simulate(pool, team_exp, 500, seed=1)
    assert a.shape == (500, len(pool)) and a.dtype == np.float32
    assert np.array_equal(a, b) and np.isfinite(a).all()


def test_starter_qb_scores_and_correlates_with_own_receiver(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 4000, seed=2)
    qb1, qb2 = _col(pool, "AAA", "QB1"), _col(pool, "AAA", "QB2")
    wr1, other_wr1 = _col(pool, "AAA", "WR1"), _col(pool, "CCC", "WR1")
    assert 12 < sims[:, qb1].mean() < 30
    assert sims[:, qb2].min() == 0 and sims[:, qb2].max() == 0     # backup with no role scores exactly 0
    assert np.corrcoef(sims[:, qb1], sims[:, wr1])[0, 1] > 0.2
    assert abs(np.corrcoef(sims[:, qb1], sims[:, other_wr1])[0, 1]) < 0.1


def test_backup_qb_throws_when_starter_out(pool, team_exp):
    p = pool.copy()
    p.loc[_col(p, "AAA", "QB1"), "playable"] = False
    sims = simulate.simulate(p, team_exp, 2000, seed=3)
    assert sims[:, _col(p, "AAA", "QB1")].max() == 0
    assert sims[:, _col(p, "AAA", "QB2")].mean() > 10


def test_dst_scores_are_plausible(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 2000, seed=4)
    d = sims[:, _col(pool, "AAA", "DST1")]
    assert -4 <= d.min() and 3 < d.mean() < 12


def test_missing_team_expectations_raise(pool, team_exp):
    with pytest.raises(KeyError, match="DDD"):
        simulate.simulate(pool, team_exp.drop(index="DDD"), 10, seed=0)


def test_summarize_orders_percentiles(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 2000, seed=5)
    s = simulate.summarize(sims, pool)
    assert list(s.columns) == ["mean", "floor", "median", "ceiling", "boom_rate"]
    assert (s.floor <= s["median"]).all() and (s["median"] <= s.ceiling).all()
    assert s.boom_rate.between(0, 1).all()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `./py -m pytest tests/test_simulate.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 4: Implement `nfldfs/simulate.py`**

```python
"""Monte Carlo simulation of every slate game → DraftKings points per player per simulation.

Correlation comes from shared draws: a game-level pace factor (shootout vs slog) and a
team-level factor scale both offenses; a team's passing yards and TDs are split among its
pass-catchers, so a QB's big game is his receivers' big game."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .dk_rules import dst_points, offense_points

GAME_SIGMA = 0.18
TEAM_SIGMA = 0.20
PASS_YDS_CV = 0.20
RUSH_YDS_CV = 0.28
SHARE_CONCENTRATION = 35.0           # Dirichlet concentration: lower = more week-to-week role noise
TARGET_FRACTION_TO_POOL = 0.93       # some targets go to players outside the DK pool
TD_WEIGHT = {"QB": 0.6, "RB": 1.0, "WR": 1.0, "TE": 1.15}
FUMBLES_LOST_RATE = {"QB": 0.10, "RB": 0.05, "WR": 0.03, "TE": 0.03}
FG_PER_GAME = 1.6
SACKS_PER_GAME = 2.4
FUMBLE_RECOVERIES_PER_GAME = 0.6
DEF_TD_RATE = 0.07
SAFETY_RATE = 0.02
BLOCKED_KICK_RATE = 0.04
_STATS = ("pass_yds", "pass_td", "ints", "rush_yds", "rush_td", "receptions", "rec_yds", "rec_td")


def _factor(rng, sigma, n):
    return rng.lognormal(-sigma ** 2 / 2, sigma, n)   # mean 1


def _simulate_team(rng, e: pd.Series, game_factor: np.ndarray, n: int) -> dict:
    f = game_factor * _factor(rng, TEAM_SIGMA, n)
    pass_td = rng.poisson(e["exp_pass_td"] * f)
    rush_td = rng.poisson(e["exp_rush_td"] * f)
    fg = rng.poisson(FG_PER_GAME * np.sqrt(f))
    return {
        "pass_yds": np.maximum(0.0, rng.normal(e["exp_pass_yds"] * f, PASS_YDS_CV * e["exp_pass_yds"])),
        "rush_yds": np.maximum(0.0, rng.normal(e["exp_rush_yds"] * f, RUSH_YDS_CV * e["exp_rush_yds"])),
        "pass_td": pass_td, "rush_td": rush_td,
        "ints": rng.poisson(max(float(e["exp_ints"]), 0.01), n),
        "targets": e["exp_pass_att"] * f * TARGET_FRACTION_TO_POOL,
        "points": 7 * (pass_td + rush_td) + 3 * fg,
    }


def _draw_shares(rng, shares: np.ndarray, n: int):
    shares = np.clip(shares, 1e-4, None)
    rest = max(1e-3, 1.0 - shares.sum())
    draw = rng.dirichlet(np.append(shares, rest) * SHARE_CONCENTRATION, size=n)
    return draw[:, :-1], draw[:, -1]


def _allocate_tds(rng, team_tds, draw, rest, weights):
    w = draw * weights
    p = w / (w.sum(axis=1, keepdims=True) + rest[:, None])
    return rng.binomial(team_tds[:, None], np.clip(p, 0.0, 1.0))


def starting_qbs(pool: pd.DataFrame) -> dict:
    qbs = pool[(pool.position == "QB") & pool.playable]
    return {team: int(g.salary.idxmax()) for team, g in qbs.groupby("team")}


def simulate(pool: pd.DataFrame, team_exp: pd.DataFrame, n_sims: int, seed: int) -> np.ndarray:
    if not isinstance(pool.index, pd.RangeIndex) or pool.index.start != 0:
        raise ValueError("simulate() needs a pool with a 0-based RangeIndex (call reset_index first)")
    missing = sorted((set(pool.team) | set(pool.opp)) - set(team_exp.index))
    if missing:
        raise KeyError(f"No team expectations for: {', '.join(missing)}")
    rng = np.random.default_rng(seed)
    n = n_sims
    team_game = {}
    for r in pool[["team", "opp", "game_id"]].drop_duplicates().itertuples(index=False):
        team_game[r.team] = team_game[r.opp] = r.game_id
    game_f = {g: _factor(rng, GAME_SIGMA, n) for g in sorted(set(team_game.values()))}
    teams = {t: _simulate_team(rng, team_exp.loc[t], game_f[team_game[t]], n) for t in sorted(team_game)}
    qbs = starting_qbs(pool)
    out = np.zeros((n, len(pool)), dtype=np.float32)

    for team, rows in pool.groupby("team").groups.items():
        o = pool.loc[rows]
        o = o[o.position != "DST"]
        if o.empty:
            continue
        oidx = o.index.to_numpy()
        pos = o.position.to_numpy()
        live = o.playable.to_numpy()
        s = teams[team]
        st = {k: np.zeros((n, len(o))) for k in _STATS}

        rmask = np.isin(pos, ["RB", "WR", "TE"]) & (o.tgt_share.to_numpy() > 0) & live
        if rmask.any():
            sh = o.tgt_share.to_numpy()[rmask]
            draw, rest = _draw_shares(rng, sh, n)
            ypt = o.ypt.to_numpy()[rmask]
            ypt_rel = ypt / max(np.sum(sh * ypt) / sh.sum(), 1e-9)
            tgts = np.round(s["targets"][:, None] * draw).astype(np.int64)
            st["receptions"][:, rmask] = rng.binomial(tgts, o.catch_rate.to_numpy()[rmask])
            yds = s["pass_yds"][:, None] * draw * ypt_rel
            scale = np.minimum(1.0, s["pass_yds"] / np.maximum(yds.sum(axis=1), 1e-9))
            st["rec_yds"][:, rmask] = yds * scale[:, None]
            st["rec_td"][:, rmask] = _allocate_tds(rng, s["pass_td"], draw, rest,
                                                   np.array([TD_WEIGHT[p] for p in pos[rmask]]))

        cmask = (o.carry_share.to_numpy() > 0) & live
        if cmask.any():
            sh = o.carry_share.to_numpy()[cmask]
            draw, rest = _draw_shares(rng, sh, n)
            ypc = o.ypc.to_numpy()[cmask]
            ypc_rel = ypc / max(np.sum(sh * ypc) / sh.sum(), 1e-9)
            st["rush_yds"][:, cmask] = s["rush_yds"][:, None] * draw * ypc_rel
            st["rush_td"][:, cmask] = _allocate_tds(rng, s["rush_td"], draw, rest,
                                                    np.array([TD_WEIGHT[p] for p in pos[cmask]]))

        has_role = rmask | cmask
        qb = qbs.get(team)
        if qb is not None:
            j = int(np.where(oidx == qb)[0][0])
            st["pass_yds"][:, j], st["pass_td"][:, j], st["ints"][:, j] = s["pass_yds"], s["pass_td"], s["ints"]
            has_role[j] = True

        fumbles = rng.poisson(np.array([FUMBLES_LOST_RATE[p] for p in pos]), size=(n, len(o)))
        fumbles[:, ~has_role] = 0          # players with no touches can't fumble
        pts = offense_points(**st, fumbles_lost=fumbles)
        pts[:, ~live] = 0.0
        out[:, oidx] = pts

    for i in np.where((pool.position == "DST").to_numpy())[0]:
        opp = teams[pool.at[i, "opp"]]
        pts = dst_points(points_allowed=opp["points"], sacks=rng.poisson(SACKS_PER_GAME, n), ints=opp["ints"],
                         fumble_recoveries=rng.poisson(FUMBLE_RECOVERIES_PER_GAME, n),
                         def_tds=rng.binomial(1, DEF_TD_RATE, n), safeties=rng.binomial(1, SAFETY_RATE, n),
                         blocked_kicks=rng.binomial(1, BLOCKED_KICK_RATE, n))
        out[:, i] = pts if pool.at[i, "playable"] else 0.0
    return out


def summarize(sims: np.ndarray, pool: pd.DataFrame) -> pd.DataFrame:
    q = np.percentile(sims, [20, 50, 85], axis=0)
    boom = (sims >= 3 * pool.salary.to_numpy() / 1000).mean(axis=0)
    return pd.DataFrame({"mean": sims.mean(axis=0), "floor": q[0], "median": q[1], "ceiling": q[2],
                         "boom_rate": boom}, index=pool.index)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_simulate.py -v`
Expected: PASS (6 tests). If `test_starter_qb_scores_and_correlates_with_own_receiver` fails only on the `12 < mean < 30` bound, print the mean and report it — do not loosen the bound without checking that the scoring wiring is right.

- [ ] **Step 6: Commit**

```bash
git add nfldfs/simulate.py tests/test_simulate.py tests/conftest.py
git commit -m "Add correlated Monte Carlo slate simulation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Ownership estimate and tiers

**Files:**
- Create: `nfldfs/ownership.py`, `tests/test_ownership.py`

**Interfaces:**
- Consumes: pool columns `position, salary, playable, median, implied_total, opp_implied`; `config.OWNERSHIP_TIERS`.
- Produces: `SLOT_TOTALS: dict[str, float]` (sums to 900), `MAX_OWN = 60.0`, `estimate_ownership(pool) -> pd.Series` (percent, indexed like pool, 0 for unplayable), `ownership_tier(pct: float) -> str` (`"Chalk" | "Popular" | "Moderate" | "Contrarian"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_ownership.py`:
```python
import pytest

from nfldfs import ownership


def _projected(pool):
    p = pool.copy()
    p["median"] = p.salary / 1000 * 2.4
    return p


def test_position_totals_match_roster_slots_and_cap(pool):
    p = _projected(pool)
    own = ownership.estimate_ownership(p)
    sums = own.groupby(p.position).sum()
    for pos, total in ownership.SLOT_TOTALS.items():
        assert sums[pos] == pytest.approx(total, rel=1e-6)
    assert own.max() <= ownership.MAX_OWN + 1e-9
    assert sum(ownership.SLOT_TOTALS.values()) == pytest.approx(900)


def test_better_value_is_more_owned(pool):
    p = _projected(pool)
    a = p.index[(p.team == "AAA") & (p["name"] == "AAA WR3")][0]
    b = p.index[(p.team == "AAA") & (p["name"] == "AAA WR4")][0]
    p.loc[a, "median"] = p.loc[b, "median"] = 14.0      # same projection, a costs $1,000 more
    own = ownership.estimate_ownership(p)
    assert own[b] > own[a]


def test_unplayable_players_have_zero_ownership(pool):
    p = _projected(pool)
    p.loc[0, "playable"] = False
    assert ownership.estimate_ownership(p)[0] == 0.0


@pytest.mark.parametrize("pct,tier", [(60, "Chalk"), (25.0, "Chalk"), (24.9, "Popular"), (10.0, "Popular"),
                                      (9.99, "Moderate"), (5.0, "Moderate"), (4.99, "Contrarian"), (0.0, "Contrarian")])
def test_ownership_tiers(pct, tier):
    assert ownership.ownership_tier(pct) == tier
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_ownership.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/ownership.py`**

```python
"""Pre-lock ownership estimate (v1 heuristic; replaced by a fitted model once results are imported — Plan 2)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import OWNERSHIP_TIERS

# Expected total ownership per position across the field: 9 roster spots = 900%.
# FLEX (100%) split roughly RB 30 / WR 55 / TE 15.
SLOT_TOTALS = {"QB": 100.0, "RB": 230.0, "WR": 355.0, "TE": 115.0, "DST": 100.0}
MAX_OWN = 60.0
TEMPERATURE = 0.6
W_VALUE, W_MEDIAN, W_ENV = 1.0, 0.6, 0.3


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros_like(x)


def _cap(own: np.ndarray, cap: float) -> np.ndarray:
    own = own.copy()
    for _ in range(50):
        over = own > cap
        if not over.any():
            break
        excess = float((own[over] - cap).sum())
        own[over] = cap
        free = own < cap
        if not free.any() or own[free].sum() == 0:
            break
        own[free] += excess * own[free] / own[free].sum()
    return own


def estimate_ownership(pool: pd.DataFrame) -> pd.Series:
    own = pd.Series(0.0, index=pool.index)
    env = np.where(pool.position == "DST", -pool.opp_implied, pool.implied_total).astype(float)
    for pos, total in SLOT_TOTALS.items():
        m = ((pool.position == pos) & pool.playable).to_numpy()
        if not m.any():
            continue
        med = pool["median"].to_numpy(float)[m]
        value = med / (pool.salary.to_numpy(float)[m] / 1000)
        score = W_VALUE * _z(value) + W_MEDIAN * _z(med) + W_ENV * _z(env[m])
        w = np.exp(score / TEMPERATURE)
        own[pool.index[m]] = _cap(w / w.sum() * total, MAX_OWN)
    return own


def ownership_tier(pct: float) -> str:
    for cutoff, label in OWNERSHIP_TIERS:
        if pct >= cutoff:
            return label
    return OWNERSHIP_TIERS[-1][1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_ownership.py -v`
Expected: PASS (11 tests incl. parametrized).

- [ ] **Step 5: Commit**

```bash
git add nfldfs/ownership.py tests/test_ownership.py
git commit -m "Add heuristic ownership estimate and Chalk/Popular/Moderate/Contrarian tiers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Lineup optimizer (PuLP)

**Files:**
- Create: `nfldfs/optimizer.py`, `tests/test_optimizer.py`

**Interfaces:**
- Consumes: `dk_rules.ROSTER_SLOTS, POSITION_BOUNDS, validate_lineup`; `config.SALARY_CAP, MIN_SALARY_DEFAULT, MIN_UNIQUE_PLAYERS, QB_STACK_MIN`.
- Produces: `class InfeasibleError(RuntimeError)`; `solve_lineup(pool, objective: np.ndarray, *, min_salary=MIN_SALARY_DEFAULT, max_salary=SALARY_CAP, stack=False, stack_min=QB_STACK_MIN, locks=(), excludes=(), previous=(), min_unique=MIN_UNIQUE_PLAYERS) -> list[int]` — sorted **row positions** into `pool` (RangeIndex); `locks`/`excludes` are **dk_ids**; `previous` is a list of earlier results (row positions).

- [ ] **Step 1: Write the failing tests**

`tests/test_optimizer.py`:
```python
import numpy as np
import pytest

from nfldfs import dk_rules
from nfldfs.optimizer import InfeasibleError, solve_lineup


def _obj(pool):
    return (pool.salary / 1000 * 2.4).to_numpy(float)


def _check(pool, rows, min_salary=49_000):
    lu = pool.loc[rows]
    assert dk_rules.validate_lineup(lu) == []
    assert min_salary <= lu.salary.sum() <= 50_000
    return lu


def test_valid_lineup_within_cap(pool):
    _check(pool, solve_lineup(pool, _obj(pool)))


def test_takes_an_obviously_best_player(pool):
    obj = _obj(pool)
    star = int(pool.index[pool["name"] == "CCC WR6"][0])     # $3,000 receiver
    obj[star] = 1000.0
    assert star in solve_lineup(pool, obj)


def test_locks_and_excludes(pool):
    lock = int(pool.loc[pool["name"] == "DDD TE3", "dk_id"].iloc[0])
    excl = int(pool.loc[pool["name"] == "AAA WR1", "dk_id"].iloc[0])
    lu = _check(pool, solve_lineup(pool, _obj(pool), locks=[lock], excludes=[excl]))
    assert lock in lu.dk_id.tolist() and excl not in lu.dk_id.tolist()


def test_unplayable_never_selected(pool):
    p = pool.copy()
    best = int(np.argmax(_obj(p)))
    p.loc[best, "playable"] = False
    assert best not in solve_lineup(p, _obj(p))


def test_uniqueness_against_previous(pool):
    first = solve_lineup(pool, _obj(pool))
    second = solve_lineup(pool, _obj(pool), previous=[first], min_unique=3)
    assert len(set(first) - set(second)) >= 3


def test_tournament_stack_rules(pool):
    lu = _check(pool, solve_lineup(pool, _obj(pool), stack=True))
    qb = lu[lu.position == "QB"].iloc[0]
    assert ((lu.team == qb.team) & lu.position.isin(["WR", "TE"])).sum() >= 1
    assert ((lu.team == qb.opp) & lu.position.isin(["RB", "WR", "TE"])).sum() >= 1
    dst = lu[lu.position == "DST"].iloc[0]
    assert not ((lu.position != "DST") & (lu.team == dst.opp)).any()


def test_impossible_min_salary_raises(pool):
    with pytest.raises(InfeasibleError, match="No valid lineup"):
        solve_lineup(pool, _obj(pool), min_salary=50_001)


def test_lock_of_unplayable_player_raises(pool):
    p = pool.copy()
    p.loc[0, "playable"] = False
    with pytest.raises(InfeasibleError, match="not playable"):
        solve_lineup(p, _obj(p), locks=[int(p.dk_id.iloc[0])])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_optimizer.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/optimizer.py`**

```python
"""Integer-programming lineup solver. Salary cap and roster rules are hard constraints."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pulp

from .config import MIN_SALARY_DEFAULT, MIN_UNIQUE_PLAYERS, QB_STACK_MIN, SALARY_CAP
from .dk_rules import POSITION_BOUNDS, ROSTER_SLOTS

_SOLVER_NAME = None


class InfeasibleError(RuntimeError):
    pass


def _solver():
    global _SOLVER_NAME
    if _SOLVER_NAME is None:
        available = pulp.listSolvers(onlyAvailable=True)
        _SOLVER_NAME = "HiGHS" if "HiGHS" in available else "PULP_CBC_CMD"
    return pulp.getSolver(_SOLVER_NAME, msg=False)


def solve_lineup(pool: pd.DataFrame, objective: np.ndarray, *, min_salary: int = MIN_SALARY_DEFAULT,
                 max_salary: int = SALARY_CAP, stack: bool = False, stack_min: int = QB_STACK_MIN,
                 locks=(), excludes=(), previous=(), min_unique: int = MIN_UNIQUE_PLAYERS) -> list[int]:
    dkid = pool.dk_id.to_numpy()
    pos, team, opp = pool.position.to_numpy(), pool.team.to_numpy(), pool.opp.to_numpy()
    sal = pool.salary.to_numpy()
    excluded = set(int(d) for d in excludes)
    rows = [i for i in range(len(pool)) if bool(pool.playable.iat[i]) and int(dkid[i]) not in excluded]

    prob = pulp.LpProblem("lineup", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in rows}
    prob += pulp.lpSum(float(objective[i]) * x[i] for i in rows)
    prob += pulp.lpSum(int(sal[i]) * x[i] for i in rows) <= max_salary
    prob += pulp.lpSum(int(sal[i]) * x[i] for i in rows) >= min_salary
    prob += pulp.lpSum(x.values()) == len(ROSTER_SLOTS)
    for p, (lo, hi) in POSITION_BOUNDS.items():
        terms = [x[i] for i in rows if pos[i] == p]
        if len(terms) < lo:
            raise InfeasibleError(f"Not enough playable {p}s on this slate to build a lineup")
        prob += pulp.lpSum(terms) >= lo
        prob += pulp.lpSum(terms) <= hi
    for d in locks:
        match = [i for i in rows if int(dkid[i]) == int(d)]
        if not match:
            raise InfeasibleError(f"Locked player {d} is not playable on this slate (injured, excluded or not listed)")
        prob += x[match[0]] == 1
    for prev in previous:
        prob += pulp.lpSum(x[i] for i in prev if i in x) <= len(ROSTER_SLOTS) - min_unique
    if stack:
        for q in (i for i in rows if pos[i] == "QB"):
            mates = [x[i] for i in rows if team[i] == team[q] and pos[i] in ("WR", "TE")]
            bring_back = [x[i] for i in rows if team[i] == opp[q] and pos[i] in ("RB", "WR", "TE")]
            prob += pulp.lpSum(mates) >= stack_min * x[q]
            prob += pulp.lpSum(bring_back) >= x[q]
        for d in (i for i in rows if pos[i] == "DST"):
            for i in rows:
                if pos[i] != "DST" and team[i] == opp[d]:
                    prob += x[d] + x[i] <= 1

    status = pulp.LpStatus[prob.solve(_solver())]
    if status != "Optimal":
        raise InfeasibleError(f"No valid lineup exists under these rules (solver status: {status}). "
                              "Loosen locks, excludes or the minimum salary.")
    return sorted(i for i in rows if x[i].value() is not None and x[i].value() > 0.5)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./py -m pytest tests/test_optimizer.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add nfldfs/optimizer.py tests/test_optimizer.py
git commit -m "Add PuLP lineup optimizer with cap, roster, stacking, locks and uniqueness" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Simulated field, contest metrics, candidate picks, swaps

**Files:**
- Create: `nfldfs/sim_eval.py`, `nfldfs/lineups.py`, `tests/test_sim_eval.py`, `tests/test_lineups.py`

**Interfaces:**
- Consumes: `optimizer.solve_lineup, InfeasibleError`; `dk_rules.ROSTER_SLOTS, assign_slots, validate_lineup`; `config.*`; pool columns from Tasks 3/7/8 incl. `median, floor, ceiling, own_pct, tier, kickoff`.
- Produces (`sim_eval`): `sample_field(pool, n, rng, *, cap=SALARY_CAP, min_salary=FIELD_MIN_SALARY) -> np.ndarray int (n, 9)` row positions; `lineup_scores(sims, lineups) -> np.ndarray (n_sims, k)`; `contest_metric(cand_scores, field_scores, metric) -> np.ndarray (k,)` probabilities; `thresholds(field_scores, metric) -> np.ndarray (n_sims,)` (h2h → field median, top_pct → field quantile `1 - pct`).
- Produces (`lineups`): `objective_values(pool, weights) -> np.ndarray`; `generate_candidates(pool, sims, contest, n, rng, *, min_salary=MIN_SALARY_DEFAULT, locks=(), excludes=()) -> list[list[int]]`; `find_swaps(pool, sims, lineup, contest, field_scores, n=N_SWAPS) -> DataFrame[SWAP_COLUMNS]`; `build_all(pool, sims, *, contest_types=CONTEST_TYPES, n_candidates=N_CANDIDATES, field_size=FIELD_SIZE, seed=SEED, keep_top=3, min_salary=MIN_SALARY_DEFAULT) -> (lineups_df, swaps_df)`; `LINEUP_COLUMNS`, `SWAP_COLUMNS`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sim_eval.py`:
```python
import numpy as np
import pytest

from nfldfs import dk_rules, sim_eval


def _owned(pool):
    p = pool.copy()
    p["own_pct"] = np.where(p["name"].str.endswith("1"), 30.0, 3.0)
    return p


def test_sample_field_lineups_are_valid_and_follow_ownership(pool):
    p = _owned(pool)
    field = sim_eval.sample_field(p, 300, np.random.default_rng(0))
    assert field.shape == (300, 9)
    for lu in field[:50]:
        assert dk_rules.validate_lineup(p.loc[lu]) == []
        assert 45_000 <= p.salary.to_numpy()[lu].sum() <= 50_000
    counts = np.bincount(field.ravel(), minlength=len(p))
    assert counts[p["name"] == "AAA QB1"].sum() > counts[p["name"] == "AAA QB2"].sum()


def test_lineup_scores_sum_players():
    sims = np.arange(12, dtype=np.float32).reshape(3, 4)
    s = sim_eval.lineup_scores(sims, [[0, 1], [2, 3]])
    assert s.tolist() == [[1, 5], [9, 13], [17, 21]]


def test_contest_metric_h2h_and_top_pct():
    field = np.full((100, 50), 10.0, dtype=np.float32)
    cand = np.column_stack([np.full(100, 11.0), np.full(100, 9.0)])
    assert sim_eval.contest_metric(cand, field, {"kind": "h2h"}).tolist() == [1.0, 0.0]
    field = np.tile(np.arange(100, dtype=np.float32), (10, 1))
    cand = np.column_stack([np.full(10, 99.5), np.full(10, 50.0)])
    assert sim_eval.contest_metric(cand, field, {"kind": "top_pct", "pct": 0.01}).tolist() == [1.0, 0.0]
    assert sim_eval.contest_metric(cand, field, {"kind": "top_pct", "pct": 0.5}).tolist() == [1.0, 1.0]
```

`tests/test_lineups.py`:
```python
import numpy as np
import pytest

from nfldfs import config, dk_rules, lineups, ownership, simulate


@pytest.fixture
def projected(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 400, seed=7)
    p = pool.join(simulate.summarize(sims, pool))
    p["own_pct"] = ownership.estimate_ownership(p)
    p["tier"] = p.own_pct.map(ownership.ownership_tier)
    return p, sims


def test_objective_values(projected):
    p, _ = projected
    v = lineups.objective_values(p, {"ceiling": 1.0, "own_penalty": 0.3})
    assert np.allclose(v, p.ceiling - 0.3 * p.own_pct)


def test_candidates_are_distinct_and_valid(projected):
    p, sims = projected
    c = lineups.generate_candidates(p, sims, config.CONTEST_TYPES["tournament"], 4, np.random.default_rng(0))
    assert len(c) == 4
    for i, a in enumerate(c):
        assert dk_rules.validate_lineup(p.loc[a]) == []
        for b in c[:i]:
            assert len(set(a) - set(b)) >= config.MIN_UNIQUE_PLAYERS


def test_build_all_covers_every_contest_type(projected):
    p, sims = projected
    lus, swaps = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert list(lus.columns) == lineups.LINEUP_COLUMNS
    assert set(lus.contest_key) == set(config.CONTEST_TYPES)
    for key, g in lus[lus["rank"] == 0].groupby("contest_key"):
        assert len(g) == 9 and list(g.slot) == list(dk_rules.ROSTER_SLOTS)
        assert dk_rules.validate_lineup(g) == [] and g.total_salary.iloc[0] <= 50_000
        assert g.metric.between(0, 1).all()
        if config.CONTEST_TYPES[key]["stack"]:
            qb = g[g.position == "QB"].iloc[0]
            assert ((g.team == qb.team) & g.position.isin(["WR", "TE"])).any()
    assert list(swaps.columns) == ["contest_key"] + lineups.SWAP_COLUMNS


def test_swaps_respect_cap_position_and_ownership(projected):
    p, sims = projected
    lus, swaps = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert (swaps.remaining_salary >= 0).all()
    pos = dict(zip(p.dk_id, p.position))
    assert all(pos[a] == pos[b] for a, b in zip(swaps.out_dk_id, swaps.in_dk_id))
    for key, g in swaps.groupby("contest_key"):
        rec = set(lus[(lus.contest_key == key) & (lus["rank"] == 0)].dk_id)
        assert not set(g.in_dk_id) & rec and set(g.out_dk_id) <= rec
        assert len(g) <= config.N_SWAPS
        if config.CONTEST_TYPES[key]["group"] == "Tournament":
            assert (g.in_own_pct < config.SWAP_MAX_OWN_TOURNAMENT).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_sim_eval.py tests/test_lineups.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/sim_eval.py`**

```python
"""Simulated opponent field and contest-specific success probabilities."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FIELD_MIN_SALARY, SALARY_CAP


def sample_field(pool: pd.DataFrame, n: int, rng, *, cap: int = SALARY_CAP,
                 min_salary: int = FIELD_MIN_SALARY, max_tries_per_lineup: int = 200) -> np.ndarray:
    """Random valid lineups drawn in proportion to estimated ownership."""
    rows = np.where(pool.playable.to_numpy())[0]
    pos = pool.position.to_numpy()
    own = pool.own_pct.to_numpy(float) + 0.05
    sal = pool.salary.to_numpy()
    by = {p: rows[pos[rows] == p] for p in ("QB", "RB", "WR", "TE", "DST")}
    prob = {p: own[ix] / own[ix].sum() for p, ix in by.items()}
    flex_all = np.concatenate([by["RB"], by["WR"], by["TE"]])
    out = np.empty((n, 9), dtype=np.int64)
    made = tries = 0
    while made < n:
        tries += 1
        if tries > n * max_tries_per_lineup:
            raise RuntimeError("Could not sample a valid simulated field — check the ownership estimates")
        core = np.concatenate([rng.choice(by["QB"], 1, p=prob["QB"]),
                               rng.choice(by["RB"], 2, replace=False, p=prob["RB"]),
                               rng.choice(by["WR"], 3, replace=False, p=prob["WR"]),
                               rng.choice(by["TE"], 1, p=prob["TE"])])
        rest = flex_all[~np.isin(flex_all, core)]
        flex = rng.choice(rest, 1, p=own[rest] / own[rest].sum())
        lu = np.concatenate([core, flex, rng.choice(by["DST"], 1, p=prob["DST"])])
        if min_salary <= sal[lu].sum() <= cap:
            out[made] = lu
            made += 1
    return out


def lineup_scores(sims: np.ndarray, lineups) -> np.ndarray:
    m = np.zeros((sims.shape[1], len(lineups)), dtype=np.float32)
    for c, lu in enumerate(lineups):
        m[np.asarray(lu), c] = 1.0
    return sims @ m


def thresholds(field_scores: np.ndarray, metric: dict) -> np.ndarray:
    if metric["kind"] == "h2h":
        return np.median(field_scores, axis=1)
    return np.quantile(field_scores, 1 - metric["pct"], axis=1)


def contest_metric(cand_scores: np.ndarray, field_scores: np.ndarray, metric: dict) -> np.ndarray:
    if metric["kind"] == "h2h":     # P(beat one randomly drawn opponent); ties lose
        fs = np.sort(field_scores, axis=1)
        wins = np.zeros(cand_scores.shape[1])
        for s in range(fs.shape[0]):
            wins += np.searchsorted(fs[s], cand_scores[s], side="left")
        return wins / (fs.shape[0] * fs.shape[1])
    thr = thresholds(field_scores, metric)
    return (cand_scores >= thr[:, None]).mean(axis=0)
```

- [ ] **Step 4: Implement `nfldfs/lineups.py`**

```python
"""Per-contest-type candidate generation, simulation-based pick, and outlier swaps."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import (CANDIDATE_PERTURBATION, CONTEST_TYPES, FIELD_SIZE, MIN_SALARY_DEFAULT,
                     MIN_UNIQUE_PLAYERS, N_CANDIDATES, N_SWAPS, SALARY_CAP, SEED, SWAP_MAX_OWN_TOURNAMENT)
from .dk_rules import ROSTER_SLOTS, assign_slots
from .optimizer import InfeasibleError, solve_lineup
from .sim_eval import contest_metric, lineup_scores, sample_field, thresholds

LINEUP_COLUMNS = ["contest_key", "contest_label", "contest_group", "rank", "slot", "dk_id", "name", "position",
                  "team", "opp", "kickoff", "salary", "median", "floor", "ceiling", "own_pct", "tier",
                  "metric", "total_salary"]
SWAP_COLUMNS = ["out_dk_id", "out_name", "in_dk_id", "in_name", "position", "in_team", "salary_delta",
                "remaining_salary", "median_delta", "ceiling_delta", "in_own_pct", "in_tier", "metric_delta"]


def objective_values(pool: pd.DataFrame, weights: dict) -> np.ndarray:
    return (weights.get("floor", 0) * pool["floor"].to_numpy(float)
            + weights.get("median", 0) * pool["median"].to_numpy(float)
            + weights.get("ceiling", 0) * pool["ceiling"].to_numpy(float)
            - weights.get("own_penalty", 0) * pool["own_pct"].to_numpy(float))


def generate_candidates(pool, sims, contest: dict, n: int, rng, *, min_salary: int = MIN_SALARY_DEFAULT,
                        locks=(), excludes=()) -> list[list[int]]:
    base = objective_values(pool, contest["weights"])
    med = pool["median"].to_numpy(float)
    picks: list[list[int]] = []
    for k in range(n):
        obj = base if k == 0 else base + CANDIDATE_PERTURBATION * (sims[rng.integers(len(sims))] - med)
        try:
            picks.append(solve_lineup(pool, obj, min_salary=min_salary, stack=contest["stack"], locks=locks,
                                      excludes=excludes, previous=picks, min_unique=MIN_UNIQUE_PLAYERS))
        except InfeasibleError:
            if not picks:
                raise
            break
    return picks


def find_swaps(pool, sims, lineup: list[int], contest: dict, field_scores, n: int = N_SWAPS,
               per_slot: int = 15) -> pd.DataFrame:
    thr = thresholds(field_scores, contest["metric"])
    base = sims[:, lineup].sum(axis=1)
    base_metric = float((base >= thr).mean())
    sal, pos = pool.salary.to_numpy(), pool.position.to_numpy()
    own, playable = pool.own_pct.to_numpy(float), pool.playable.to_numpy()
    total = int(sal[lineup].sum())
    obj = objective_values(pool, contest["weights"])
    in_lineup = np.zeros(len(pool), dtype=bool)
    in_lineup[lineup] = True
    rows = []
    for o in lineup:
        ok = playable & ~in_lineup & (pos == pos[o]) & (total - sal[o] + sal <= SALARY_CAP)
        if contest["group"] == "Tournament":
            ok &= own < SWAP_MAX_OWN_TOURNAMENT
        cand = np.where(ok)[0]
        for j in cand[np.argsort(-obj[cand])][:per_slot]:
            new = base - sims[:, o] + sims[:, j]
            rows.append({
                "out_dk_id": int(pool.dk_id.iat[o]), "out_name": pool["name"].iat[o],
                "in_dk_id": int(pool.dk_id.iat[j]), "in_name": pool["name"].iat[j], "position": pos[j],
                "in_team": pool.team.iat[j], "salary_delta": int(sal[j] - sal[o]),
                "remaining_salary": int(SALARY_CAP - (total - sal[o] + sal[j])),
                "median_delta": float(pool["median"].iat[j] - pool["median"].iat[o]),
                "ceiling_delta": float(pool["ceiling"].iat[j] - pool["ceiling"].iat[o]),
                "in_own_pct": float(own[j]), "in_tier": pool["tier"].iat[j],
                "metric_delta": float((new >= thr).mean() - base_metric),
            })
    if not rows:
        return pd.DataFrame(columns=SWAP_COLUMNS)
    df = pd.DataFrame(rows).sort_values("metric_delta", ascending=False, kind="stable")
    return df.drop_duplicates("in_dk_id").head(n).reset_index(drop=True)[SWAP_COLUMNS]


def build_all(pool: pd.DataFrame, sims: np.ndarray, *, contest_types: dict = CONTEST_TYPES,
              n_candidates: int = N_CANDIDATES, field_size: int = FIELD_SIZE, seed: int = SEED,
              keep_top: int = 3, min_salary: int = MIN_SALARY_DEFAULT) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    field_scores = lineup_scores(sims, sample_field(pool, field_size, rng))
    cache: dict[str, list[list[int]]] = {}
    lineup_rows, swap_frames = [], []
    by_id = pool.set_index("dk_id")
    for key, contest in contest_types.items():
        ck = json.dumps({"w": contest["weights"], "s": contest["stack"]}, sort_keys=True)
        if ck not in cache:
            cache[ck] = generate_candidates(pool, sims, contest, n_candidates, rng, min_salary=min_salary)
        cands = cache[ck]
        metric = contest_metric(lineup_scores(sims, cands), field_scores, contest["metric"])
        for rank, c in enumerate(np.argsort(-metric, kind="stable")[:keep_top]):
            players = pool.loc[cands[c]]
            total = int(players.salary.sum())
            for slot, dk in zip(ROSTER_SLOTS, assign_slots(players)):
                r = by_id.loc[dk]
                lineup_rows.append({
                    "contest_key": key, "contest_label": contest["label"], "contest_group": contest["group"],
                    "rank": rank, "slot": slot, "dk_id": int(dk), "name": r["name"], "position": r.position,
                    "team": r.team, "opp": r.opp, "kickoff": r.kickoff, "salary": int(r.salary),
                    "median": float(r["median"]), "floor": float(r["floor"]), "ceiling": float(r["ceiling"]),
                    "own_pct": float(r.own_pct), "tier": r["tier"], "metric": float(metric[c]),
                    "total_salary": total,
                })
        best = cands[int(np.argmax(metric))]
        sw = find_swaps(pool, sims, best, contest, field_scores)
        sw.insert(0, "contest_key", key)
        swap_frames.append(sw)
    return (pd.DataFrame(lineup_rows, columns=LINEUP_COLUMNS),
            pd.concat(swap_frames, ignore_index=True))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./py -m pytest tests/test_sim_eval.py tests/test_lineups.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add nfldfs/sim_eval.py nfldfs/lineups.py tests/test_sim_eval.py tests/test_lineups.py
git commit -m "Add simulated field, contest metrics, candidate picks and outlier swaps" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Slate build orchestration and the pipeline runner

**Files:**
- Create: `nfldfs/build.py`, `run_pipeline.py`, `tests/test_build.py`, `tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: every module above.
- Produces: `build.assemble_team_expectations(pool_base, vegas_games, team_model) -> (pool, team_exp)`; `build.build_slate(pool_base, player_weeks, team_weeks, team_model, vegas_games, *, n_sims, seed, n_candidates, field_size) -> dict{pool, sims, lineups, swaps, match_rate, unmatched}`.
- Produces: `run_pipeline.STAGES: dict[str, list[str]]`, `run_pipeline.STEP_FUNCS: dict[str, Callable[[date, Namespace], str]]`, `run_pipeline.main(argv=None) -> int`. Files written (paths from `config`): `data/raw/dk_salaries.csv`; `data/processed/{pool_base.parquet, slate.json, player_weeks.parquet, team_weeks.parquet, team_model.json, vegas_games.parquet, odds_meta.json}`; `data/published/{player_pool.parquet, lineups.parquet, swaps.parquet, sims.npy, dk_upload_recommended.csv, build_meta.json, run_status.json}`. **Plan 2's app reads only `data/published/`.**

- [ ] **Step 1: Write the failing tests**

`tests/test_build.py`:
```python
import numpy as np
import pandas as pd
import pytest

from nfldfs import build, config, dk_rules
from nfldfs.nfl_stats import team_week_totals
from tests.conftest import make_pool

MODEL = {"n_games": 999, "coef": {
    "pass_att": [20, 0.5, 0], "pass_yds": [100, 5, 0], "pass_td": [0, 0.07, 0], "ints": [0.8, 0, 0],
    "carries": [15, 0.4, 0.3], "rush_yds": [60, 2.5, 1], "rush_td": [0, 0.04, 0]}}


def _inputs():
    full = make_pool()
    pool_base = full[["dk_id", "name", "position", "salary", "team", "opp", "game_id", "is_home",
                      "kickoff", "dk_avg", "status", "playable"]].copy()
    rows = []
    for r in full[full.position != "DST"].itertuples(index=False):
        for wk in range(1, 7):
            t, c = round(r.tgt_share * 36), round(r.carry_share * 26)
            qb1 = r.name.endswith("QB1")
            rows.append(dict(player_id=f"P{r.dk_id}", name=r.name, position=r.position, team=r.team,
                             season=2026, week=wk, pass_att=34 if qb1 else 0, pass_yds=240.0 if qb1 else 0.0,
                             pass_td=2 if qb1 else 0, ints=1 if qb1 else 0, carries=c, rush_yds=c * r.ypc,
                             rush_td=0, targets=t, receptions=round(t * r.catch_rate), rec_yds=t * r.ypt,
                             rec_td=0, fumbles_lost=0, two_pt=0, dk_pts=0.0))
    pw = pd.DataFrame(rows)
    games = pd.DataFrame({"game_id": ["AAA@BBB", "CCC@DDD", "XXX@YYY"], "home": ["BBB", "DDD", "YYY"],
                          "away": ["AAA", "CCC", "XXX"], "total": [45.0, 47.0, 40.0],
                          "home_spread": [-3.0, 2.0, 0.0], "n_books": 3, "commence_time": "2026-10-18T17:00:00Z"})
    return pool_base, pw, team_week_totals(pw), games


def test_missing_vegas_lines_names_teams():
    pool_base, pw, tw, games = _inputs()
    with pytest.raises(ValueError, match="CCC, DDD"):
        build.assemble_team_expectations(pool_base, games[games.game_id != "CCC@DDD"], MODEL)


def test_assemble_attaches_implied_totals_for_slate_games_only():
    pool_base, pw, tw, games = _inputs()
    pool, team_exp = build.assemble_team_expectations(pool_base, games, MODEL)
    assert sorted(team_exp.index) == ["AAA", "BBB", "CCC", "DDD"]
    bbb = pool[pool.team == "BBB"].iloc[0]
    assert bbb.implied_total == pytest.approx(24.0) and bbb.opp_implied == pytest.approx(21.0)


def test_build_slate_end_to_end():
    pool_base, pw, tw, games = _inputs()
    pool_base.loc[pool_base["name"] == "AAA WR1", ["status", "playable"]] = ["OUT", False]
    res = build.build_slate(pool_base, pw, tw, MODEL, games, n_sims=300, seed=1, n_candidates=3, field_size=150)
    assert res["match_rate"] == pytest.approx(1.0) and res["unmatched"] == []
    p = res["pool"]
    assert {"median", "floor", "ceiling", "boom_rate", "own_pct", "tier", "matched"} <= set(p.columns)
    assert res["sims"].shape == (300, len(p))
    out_wr = p[p["name"] == "AAA WR1"].iloc[0]
    assert out_wr.own_pct == 0 and out_wr["median"] == 0
    lus = res["lineups"]
    assert set(lus.contest_key) == set(config.CONTEST_TYPES)
    assert "AAA WR1" not in set(lus["name"])
    for _, g in lus[lus["rank"] == 0].groupby("contest_key"):
        assert dk_rules.validate_lineup(g) == []
```

`tests/test_run_pipeline.py`:
```python
import json

import run_pipeline
from nfldfs import config


def test_every_stage_step_exists():
    for steps in run_pipeline.STAGES.values():
        for s in steps:
            assert s in run_pipeline.STEP_FUNCS


def test_failure_stops_run_and_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PUBLISHED", tmp_path / "published")
    monkeypatch.setattr(config, "LOGS", tmp_path / "logs")
    calls = []

    def ok(today, args):
        calls.append("ok")
        return "fine"

    def boom(today, args):
        raise RuntimeError("DraftKings returned HTML")

    monkeypatch.setattr(run_pipeline, "STAGES", {"test": ["a", "b", "c"]})
    monkeypatch.setattr(run_pipeline, "STEP_FUNCS", {"a": ok, "b": boom, "c": ok})
    assert run_pipeline.main(["--stage", "test", "--today", "2026-10-15"]) == 1
    assert calls == ["ok"]
    status = json.loads((tmp_path / "published" / "run_status.json").read_text())
    assert status["ok"] is False and [s["name"] for s in status["steps"]] == ["a", "b"]
    assert status["steps"][0]["message"] == "fine" and "HTML" in status["steps"][1]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./py -m pytest tests/test_build.py tests/test_run_pipeline.py -v`
Expected: ERROR with `ImportError`.

- [ ] **Step 3: Implement `nfldfs/build.py`**

```python
"""Turn loaded inputs into a full slate build: projections, ownership, lineups, swaps."""
from __future__ import annotations

import pandas as pd

from . import lineups, ownership, shares, simulate, team_env
from .config import FIELD_SIZE, N_CANDIDATES, N_SIMS, SEED
from .vegas import implied_totals


def assemble_team_expectations(pool_base: pd.DataFrame, vegas_games: pd.DataFrame, team_model: dict):
    slate_games = set(pool_base.game_id)
    it = implied_totals(vegas_games[vegas_games.game_id.isin(slate_games)])
    slate_teams = set(pool_base.team) | set(pool_base.opp)
    missing = sorted(slate_teams - set(it.team))
    if missing:
        raise ValueError("No Vegas lines yet for: " + ", ".join(missing)
                         + ". Lines are usually posted early in the week; re-run once they are.")
    pool = pool_base.drop(columns=[c for c in ("implied_total", "opp_implied", "exp_margin")
                                   if c in pool_base.columns])
    pool = pool.merge(it[["team", "implied_total", "exp_margin"]], on="team", how="left")
    pool["opp_implied"] = pool.opp.map(it.set_index("team").implied_total)
    team_exp = team_env.expected_team_stats(it, team_model).set_index("team")
    return pool.reset_index(drop=True), team_exp


def build_slate(pool_base, player_weeks, team_weeks, team_model, vegas_games, *, n_sims: int = N_SIMS,
                seed: int = SEED, n_candidates: int = N_CANDIDATES, field_size: int = FIELD_SIZE) -> dict:
    pool, team_exp = assemble_team_expectations(pool_base, vegas_games, team_model)
    pool = shares.attach_shares(pool, shares.compute_shares(player_weeks, team_weeks))
    pool = shares.redistribute(pool).reset_index(drop=True)
    sims = simulate.simulate(pool, team_exp, n_sims, seed)
    pool = pool.join(simulate.summarize(sims, pool))
    pool["own_pct"] = ownership.estimate_ownership(pool)
    pool["tier"] = pool.own_pct.map(ownership.ownership_tier)
    lus, swaps = lineups.build_all(pool, sims, n_candidates=n_candidates, field_size=field_size, seed=seed)
    offense = pool[(pool.position != "DST") & pool.playable]
    return {"pool": pool, "sims": sims, "lineups": lus, "swaps": swaps,
            "match_rate": float(offense.matched.mean()) if len(offense) else 1.0,
            "unmatched": sorted(offense.loc[~offense.matched, "name"].tolist())}
```

- [ ] **Step 4: Implement `run_pipeline.py`**

```python
#!/usr/bin/env python3
"""Weekly pipeline runner.

  ./py run_pipeline.py --stage tuesday     salaries + nflverse stats
  ./py run_pipeline.py --stage thursday    (salaries/stats if missing) + Vegas + build
  ./py run_pipeline.py --stage sunday      fresh salaries/statuses + Vegas + build
  ./py run_pipeline.py --stage build       rebuild from what's already downloaded
  add --salary-csv PATH to use a manually downloaded DKSalaries.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from nfldfs import build, config, dk_rules, dk_salaries, nfl_stats, team_env, vegas
from nfldfs.status import RunStatus, atomic_save_npy, atomic_write_parquet, atomic_write_text

log = logging.getLogger("pipeline")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def step_salaries(today, args) -> str:
    if args.salary_csv:
        text = Path(args.salary_csv).read_text(encoding="utf-8-sig")
        slate = {"draft_group_id": None, "contest_type_id": None, "start": None, "source": "upload"}
    else:
        slate = dk_salaries.find_main_slate(dk_salaries.fetch_lobby(), today)
        text = dk_salaries.fetch_salary_csv(slate)
        slate["source"] = "draftkings"
    pool = dk_salaries.parse_salary_csv(text)
    slate.update(game_count=int(pool.game_id.nunique()), players=len(pool), fetched_at=_now())
    atomic_write_text(config.RAW / "dk_salaries.csv", text)
    atomic_write_parquet(pool, config.PROCESSED / "pool_base.parquet")
    atomic_write_text(config.PROCESSED / "slate.json", json.dumps(slate, indent=2))
    return f"{len(pool)} players, {slate['game_count']} games ({slate['source']})"


def _salaries_current(today) -> bool:
    p = config.PROCESSED / "pool_base.parquet"
    return p.exists() and pd.read_parquet(p).kickoff.max().date() >= today


def step_salaries_if_stale(today, args) -> str:
    if not args.salary_csv and _salaries_current(today):
        return "skipped: this week's salaries are already downloaded"
    return step_salaries(today, args)


def step_stats(today, args) -> str:
    season = config.season_for(today)
    raw, sched = nfl_stats.load_raw(list(range(season - config.STATS_SEASONS_BACK, season + 1)))
    pw = nfl_stats.normalize_player_stats(raw)
    tw = nfl_stats.team_week_totals(pw)
    model = team_env.fit_team_model(team_env.build_training_frame(tw, nfl_stats.normalize_schedules(sched)))
    atomic_write_parquet(pw, config.PROCESSED / "player_weeks.parquet")
    atomic_write_parquet(tw, config.PROCESSED / "team_weeks.parquet")
    atomic_write_text(config.PROCESSED / "team_model.json", json.dumps(model, indent=2))
    latest = pw[pw.season == pw.season.max()].week.max()
    return f"{len(pw)} player-weeks through {pw.season.max()} week {latest}; model fit on {model['n_games']} team-games"


def step_stats_if_missing(today, args) -> str:
    needed = [config.PROCESSED / f for f in ("player_weeks.parquet", "team_weeks.parquet", "team_model.json")]
    if all(p.exists() for p in needed):
        return "skipped: stats already built this week"
    return step_stats(today, args)


def step_vegas(today, args) -> str:
    events, remaining = vegas.fetch_odds(config.odds_api_key())
    games = vegas.parse_odds(events)
    atomic_write_parquet(games, config.PROCESSED / "vegas_games.parquet")
    atomic_write_text(config.PROCESSED / "odds_meta.json",
                      json.dumps({"fetched_at": _now(), "requests_remaining": remaining}, indent=2))
    return f"{len(games)} games with lines; Odds API requests remaining: {remaining}"


def step_build(today, args) -> str:
    P = config.PROCESSED
    res = build.build_slate(
        pd.read_parquet(P / "pool_base.parquet"), pd.read_parquet(P / "player_weeks.parquet"),
        pd.read_parquet(P / "team_weeks.parquet"), json.loads((P / "team_model.json").read_text()),
        pd.read_parquet(P / "vegas_games.parquet"), n_sims=config.N_SIMS, seed=config.SEED,
        n_candidates=config.N_CANDIDATES, field_size=config.FIELD_SIZE)
    out = config.PUBLISHED
    atomic_write_parquet(res["pool"], out / "player_pool.parquet")
    atomic_write_parquet(res["lineups"], out / "lineups.parquet")
    atomic_write_parquet(res["swaps"], out / "swaps.parquet")
    atomic_save_npy(res["sims"][: config.N_SIMS_PUBLISHED].astype(np.float16), out / "sims.npy")
    rec = res["lineups"][res["lineups"]["rank"] == 0]
    dk_rules.write_upload_csv([g for _, g in rec.groupby("contest_key", sort=False)],
                              out / "dk_upload_recommended.csv")
    slate = json.loads((P / "slate.json").read_text())
    odds = json.loads((P / "odds_meta.json").read_text()) if (P / "odds_meta.json").exists() else {}
    meta = {**slate, "built_at": _now(), "n_sims": config.N_SIMS, "match_rate": res["match_rate"],
            "unmatched": res["unmatched"], "vegas_fetched_at": odds.get("fetched_at"),
            "odds_requests_remaining": odds.get("requests_remaining")}
    atomic_write_text(out / "build_meta.json", json.dumps(meta, indent=2, default=str))
    return (f"{rec.contest_key.nunique()} contest types built; name match rate {res['match_rate']:.0%}"
            + (f"; unmatched: {', '.join(res['unmatched'][:10])}" if res["unmatched"] else ""))


STAGES = {
    "tuesday": ["salaries", "stats"],
    "thursday": ["salaries_if_stale", "stats_if_missing", "vegas", "build"],
    "sunday": ["salaries", "stats_if_missing", "vegas", "build"],
    "build": ["build"],
}
STEP_FUNCS = {
    "salaries": step_salaries, "salaries_if_stale": step_salaries_if_stale,
    "stats": step_stats, "stats_if_missing": step_stats_if_missing,
    "vegas": step_vegas, "build": step_build,
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--salary-csv", help="use a manually downloaded DKSalaries.csv")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for testing")
    args = ap.parse_args(argv)
    if args.stage not in STAGES:
        ap.error(f"--stage must be one of {sorted(STAGES)}")
    config.LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True,
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(config.LOGS / "pipeline.log")])
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    status = RunStatus(config.PUBLISHED / "run_status.json", args.stage)
    ok = True
    for name in STAGES[args.stage]:
        log.info("── %s ──", name)
        try:
            with status.step(name) as rec:
                rec["message"] = STEP_FUNCS[name](today, args) or ""
            log.info("%s ok: %s", name, rec["message"])
        except Exception:
            log.exception("%s failed — stopping this run", name)
            ok = False
            break
    status.finish(ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the new tests, then the whole suite**

Run: `./py -m pytest tests/test_build.py tests/test_run_pipeline.py -v && ./py -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add nfldfs/build.py run_pipeline.py tests/test_build.py tests/test_run_pipeline.py
git commit -m "Add slate build orchestration and staged pipeline runner" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Live dry run on this week's real slate + project docs

**Files:**
- Create: `README.md`, `claude-context.txt`, `claude-prompts.txt`, `env.txt` (git-ignored, never committed)

**Interfaces:**
- Consumes: the full pipeline. Produces no new code interfaces — this task is verification against real data plus the documentation convention `MLB_Pipeline` uses.

- [ ] **Step 1: Provide the Odds API key (Nathan)**

Nathan reuses the same The Odds API key as `MLB_Pipeline` (note: they share the 500-request monthly quota; this project uses ~2 requests per run, ~6–8 per week). Nathan runs, or explicitly approves running:
```bash
cd ~/Desktop/Nathan/Claude/NFL_DFS && grep '^ODDS_API_KEY=' ~/Desktop/Nathan/Claude/MLB_Pipeline/env.txt > env.txt && git check-ignore env.txt
```
Expected: prints `env.txt` (confirming it is ignored). The key value is never printed or committed.

- [ ] **Step 2: Run the Tuesday stage live**

```bash
caffeinate -i ./py run_pipeline.py --stage tuesday
```
Expected: exit 0; log shows the main slate (~400–550 players, 10+ games) and the stats/model line. If the salaries step fails with the "something other than the salary CSV" message, download `DKSalaries.csv` from any main-slate contest on draftkings.com and re-run with `--salary-csv ~/Downloads/DKSalaries.csv`.

- [ ] **Step 3: Run the Thursday stage live, timed**

```bash
time caffeinate -i ./py run_pipeline.py --stage thursday
```
Expected: exit 0; `salaries_if_stale` and `stats_if_missing` report "skipped"; Vegas shows every slate game; build reports 9 contest types and a name match rate. Record wall time (target < 10 min). If any slate team is missing Vegas lines, the error names it — that's expected early in the week; re-run later.

- [ ] **Step 4: Sanity-review the outputs**

```bash
./py -c "
import json, pandas as pd
from nfldfs import dk_rules
P='data/published/'
meta=json.load(open(P+'build_meta.json')); print({k: meta[k] for k in ('draft_group_id','game_count','match_rate','built_at')}); print('unmatched:', meta['unmatched'][:20])
pool=pd.read_parquet(P+'player_pool.parquet')
print(pool[pool.playable].sort_values('median', ascending=False).groupby('position').head(3)[['name','position','team','salary','median','floor','ceiling','own_pct','tier']].to_string())
lus=pd.read_parquet(P+'lineups.parquet')
for key, g in lus[lus['rank']==0].groupby('contest_key', sort=False):
    assert dk_rules.validate_lineup(g)==[], key
    print(f\"\n{g.contest_label.iloc[0]}  metric={g.metric.iloc[0]:.3f}  salary=\${g.total_salary.iloc[0]:,}\")
    print(g[['slot','name','team','salary','median','ceiling','own_pct','tier']].to_string(index=False))
print(pd.read_parquet(P+'swaps.parquet').groupby('contest_key').size().to_dict())
print(open(P+'dk_upload_recommended.csv').read())
"
```
Review against these checks, and write down any that fail rather than tuning anything:
- Name match rate ≥ 90%; the unmatched list is mostly rookies/backups, not starters.
- Top QB medians roughly 17–25, top RB/WR roughly 15–22, DST medians roughly 5–9.
- Ownership: per-position totals match `SLOT_TOTALS`; obvious cheap starters land in Chalk/Popular.
- Cash lineups are higher-floor, chalkier; Large-Field Tournament has more Contrarian players and a QB stack.
- Every recommended lineup is ≤ $50,000 and validates; the upload CSV has a header plus 9 rows.

- [ ] **Step 5: Show Nathan the results**

Summarize the Step 4 output for Nathan: the slate, each contest type's recommended lineup, the swaps, the runtime, the match rate, and any failed sanity checks. The exact DraftKings upload-template format (spec §14 item 3) is confirmed when Nathan first uploads this CSV. **Nathan decides whether any tuning is needed before Plan 2.**

- [ ] **Step 6: Write the project docs (MLB convention)**

`README.md`:
```markdown
# NFL DFS Lineup Optimizer

Builds DraftKings NFL Sunday main-slate lineups for every DraftKings contest type
(Head-to-Head, 50/50, Double Up, Multipliers, Single Entry / 3-Max, Tournament,
Large-Field Tournament) from free data: DraftKings' own salary CSV, nflverse stats
and Vegas lines (The Odds API). Personal use; never logs in to DraftKings or enters contests.

## Setup
1. `./py -m pip install -r requirements.txt` (`./py` = system Python 3.14)
2. Copy `env.txt.example` to `env.txt` and add `ODDS_API_KEY`
3. `./py -m pytest -q`

## Weekly use (manual until Plan 2 adds scheduling and the app)
- Tuesday: `./py run_pipeline.py --stage tuesday`
- Thursday: `./py run_pipeline.py --stage thursday`
- Sunday morning: `./py run_pipeline.py --stage sunday`
- If DraftKings blocks the automatic download: add `--salary-csv ~/Downloads/DKSalaries.csv`

Outputs land in `data/published/` (lineups, swaps, player pool, upload CSV, run status).

## How it works
Spec: `docs/superpowers/specs/2026-10-11-nfl-dfs-optimizer-design.md`.
Vegas implied totals → expected team volume → player shares → 10,000 correlated game
simulations → floor/median/ceiling + estimated ownership → integer-programming optimizer
builds ~150 candidates per strategy → each contest type picks the candidate with the best
simulated result against an ownership-weighted field.
```

`claude-context.txt`: a dated (2026-10-12) project briefing — purpose, links to spec/plan, module map (copy the File Structure section), data sources with the verified DK URLs and the "draftables JSON is 403" finding, the deliberate deviations from the spec, the dry-run results from Step 4 (runtime, match rate, any failed sanity checks), and an OUTSTANDING list: Plan 2 (app, publish, LaunchAgents, results import, sidebar guide, USER_MANUAL), ownership regression after 3 imported weeks, red-zone shares, option C (Sleeper blend).

`claude-prompts.txt`: a dated session-log entry for 2026-10-11/12 summarizing the brainstorming decisions (NFL over NBA, Approach A, DraftKings contest-type names, no DK login automation) and this build.

- [ ] **Step 7: Confirm nothing sensitive is staged, then commit**

```bash
git status --short
git add README.md claude-context.txt claude-prompts.txt
git diff --cached --name-only | grep -E 'env\.txt$|^data/' && echo "STOP: secret or data staged" || git commit -m "Add project docs and record live dry-run results" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: commit succeeds; `env.txt` and `data/` never appear.

---

## Self-Review Notes

- **Spec coverage (Plan 1 scope):** §3 constraints → Global Constraints + Tasks 2/3/9; §6 sources → Tasks 3/4/5; §7.1 → Task 5; §7.2 → Task 6 (red-zone deviation recorded); §7.3 → Task 7; §7.4 cold-start heuristic → Task 8; §8.1 contest types/objectives/constraints → Tasks 1/9; §8.2 candidates/field/picks → Task 10; §8.3 swaps → Task 10; §11 error handling (status file, atomic writes, stop on failure, missing-lines message) → Tasks 1/11; §12 unit tests + live dry run → every task + Task 12; §14 verification items 1, 4, 5, 6 → Tasks 3/2/5/1, item 3 → Task 12 Step 5. **Deferred to Plan 2 by design:** §5 scheduling, §9 app incl. sidebar import guide, hosted/local split, publish/commit/push, results import + report card, ownership regression, USER_MANUAL, §12 historical backtest, §14 item 2 (DK export click-path screenshots) and item 7 (RotoGuru).
- **Placeholder scan:** none — every code step has full code; Task 12 Step 6's two .txt files are described by required content because they record live results that don't exist until Step 4 runs.
- **Type consistency:** `solve_lineup` returns row positions and takes dk_id locks/excludes everywhere it's used (Tasks 9, 10); `team_exp` is indexed by team in Tasks 7 and 11; contest dict keys (`label, group, weights, stack, metric`) are defined in Task 1 and used unchanged in Tasks 9–11; `LINEUP_COLUMNS`/`SWAP_COLUMNS` defined once in Task 10.
