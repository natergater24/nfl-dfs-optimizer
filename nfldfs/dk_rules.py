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
