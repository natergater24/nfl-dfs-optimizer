"""NBA settings. Shared plumbing (paths, contest weights) comes from nfldfs.config; NBA tunables live here."""
from __future__ import annotations

import copy

from nfldfs import config as _nfl

SALARY_CAP = 50_000
MIN_GAMES = 2                      # lineup needs players from at least this many different games
N_SIMS = 10_000
SEED = 20261023
FIELD_SIZE = 2_000
MIN_SALARY_DEFAULT = 49_000
MIN_UNIQUE_PLAYERS = 3
ODDS_MAX_AGE_MIN = 60              # skip the Odds API call when NBA lines are fresher than this

_LABELS = {
    "single_entry": "Single Entry / 3-Max Tournament (e.g. Splash)",
    "tournament": "Tournament (e.g. Fadeaway, Box Out)",
    "large_tournament": "Large-Field Tournament (e.g. Mega 8's)",
}


def _nba_contest_types() -> dict:
    types = copy.deepcopy(_nfl.CONTEST_TYPES)
    for key, spec in types.items():
        spec["stack"] = False
        if key in _LABELS:
            spec["label"] = _LABELS[key]
    return types


NBA_CONTEST_TYPES = _nba_contest_types()

PUBLISHED_NBA = _nfl.PUBLISHED / "nba"
PROCESSED_NBA = _nfl.PROCESSED / "nba"
RAW_NBA = _nfl.RAW / "nba"
