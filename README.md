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

`data/published/dk_upload_recommended.csv` has one row per contest type, in this order: Head-to-Head,
50/50, Double Up, Multiplier 3x, 5x, 10x, Single Entry / 3-Max, Tournament, Large-Field Tournament.
Upload only the row(s) you want (plus the header) to DraftKings.

## How it works
Spec: `docs/superpowers/specs/2026-10-11-nfl-dfs-optimizer-design.md`.
Vegas implied totals → expected team volume → player shares → 10,000 correlated game
simulations → floor/median/ceiling + estimated ownership → integer-programming optimizer
builds ~150 candidates per strategy → each contest type picks the candidate with the best
simulated result against an ownership-weighted field.
