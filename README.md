# NFL DFS Lineup Optimizer

Builds DraftKings Classic NFL Sunday main-slate lineups for every DraftKings contest type
(Head-to-Head, 50/50, Double Up, Triple Up (3x), Quintuple Up (5x), 10x Multiplier, Single Entry / 3-Max,
Tournament, Large-Field Tournament (e.g. Millionaire Maker)); Showdown and other styles are not supported yet from free data: DraftKings' own salary CSV, nflverse stats
and Vegas lines (The Odds API). Personal use; never logs in to DraftKings or enters contests.

## Setup
1. `./py -m pip install -r requirements.txt` (`./py` = system Python 3.14)
2. Copy `env.txt.example` to `env.txt` and add `ODDS_API_KEY`
3. `./py -m pytest -q`

## Weekly use
Everything runs on a schedule; see `USER_MANUAL.md` for the plain-language weekly guide.
- Hosted copy (phone): https://nfl-dfs-optimizer.streamlit.app/
- Local app: `bash launch.sh` then open http://localhost:8502 (or the Desktop launcher once created)
- Stages, each runnable with `./py run_pipeline.py --stage <name>`: `tuesday`, `thursday`, `sunday`,
  `sunday_late`, `refresh`, `results`, `build`
- If DraftKings blocks the automatic download: add `--salary-csv ~/Downloads/DKSalaries.csv`

Outputs land in `data/published/` (lineups, swaps, player pool, upload CSV, run status).

`data/published/dk_upload_recommended.csv` has one row per contest type, in this order: Head-to-Head,
50/50, Double Up, Triple Up (3x), Quintuple Up (5x), 10x Multiplier, Single Entry / 3-Max, Tournament, Large-Field Tournament (e.g. Millionaire Maker).
Upload only the row(s) you want (plus the header) to DraftKings.

My Results tab: your contest entries (place, points, winnings, which app lineup) filled from exported standings
plus fees and winnings from DraftKings' entry-history download (typing is the fallback), and per-player history. Needs `DK_USERNAME` in `env.txt`; usernames are never published.
Every build of a slate is archived in `data/processed/slate_lineups/`, so entries from any build are recognized.
The `tuesday` stage fills nflverse actual points and publishes them. Season filter = NFL season (January slates
belong to the prior season). Unknown contest types show "Type not set". Spec:
`docs/superpowers/specs/2026-10-16-my-results-design.md`.

## How it works
Spec: `docs/superpowers/specs/2026-10-11-nfl-dfs-optimizer-design.md`.
Vegas implied totals → expected team volume → player shares → 10,000 correlated game
simulations → floor/median/ceiling + estimated ownership → integer-programming optimizer
builds ~150 candidates per strategy → each contest type picks the candidate with the best
simulated result against an ownership-weighted field.
