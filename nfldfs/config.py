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
HISTORY = DATA / "history"
SLATES = PROCESSED / "slates"
DOWNLOADS = Path(os.environ.get("NFLDFS_DOWNLOADS", str(Path.home() / "Downloads")))
VEGAS_REUSE_HOURS = 4              # Sunday 11:45 reuses the 9:00 lines
VEGAS_FALLBACK_HOURS = 48          # if the odds fetch fails, reuse lines up to this old (loud warning)

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
MAX_SWAPS_PER_POSITION = 2         # outlier list is spread across positions
REBUILD_CANDIDATES = 30            # candidates per "Rebuild with my locks" in the app
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
