"""DraftKings NBA Classic: roster slots, eligibility, scoring, lineup validation, upload CSV."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import MIN_GAMES, SALARY_CAP

ROSTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL")
SLOT_POSITIONS = {"PG": {"PG"}, "SG": {"SG"}, "SF": {"SF"}, "PF": {"PF"}, "C": {"C"},
                  "G": {"PG", "SG"}, "F": {"SF", "PF"}, "UTIL": {"PG", "SG", "SF", "PF", "C"}}


def eligible_slots(positions: str) -> list[str]:
    """DK `Position` such as "SG/SF" -> the roster slots that player may fill, in ROSTER_SLOTS order."""
    pos = {p.strip() for p in positions.split("/") if p.strip()}
    return [s for s in ROSTER_SLOTS if SLOT_POSITIONS[s] & pos]


def dk_points(pts, fg3m, reb, ast, stl, blk, tov):
    """DraftKings NBA fantasy points; works on scalars or numpy arrays."""
    pts, fg3m, reb, ast, stl, blk, tov = (np.asarray(x, dtype=float) for x in (pts, fg3m, reb, ast, stl, blk, tov))
    base = pts + 0.5 * fg3m + 1.25 * reb + 1.5 * ast + 2.0 * stl + 2.0 * blk - 0.5 * tov
    tens = sum((x >= 10).astype(int) for x in (pts, reb, ast, stl, blk))
    total = base + np.where(tens >= 3, 3.0, np.where(tens >= 2, 1.5, 0.0))
    return float(total) if total.ndim == 0 else total


def validate_lineup(players: pd.DataFrame, slots: list[str]) -> list[str]:
    """Problems with a lineup (empty list = legal). Row i of `players` fills slots[i]."""
    errors: list[str] = []
    if len(players) != len(ROSTER_SLOTS) or len(slots) != len(ROSTER_SLOTS):
        return [f"Lineup needs exactly {len(ROSTER_SLOTS)} players (has {len(players)})"]
    if sorted(slots) != sorted(ROSTER_SLOTS):
        errors.append(f"Slots must be exactly {', '.join(ROSTER_SLOTS)}")
    if players["dk_id"].duplicated().any():
        errors.append("A player appears more than once")
    total = int(players["salary"].sum())
    if total > SALARY_CAP:
        errors.append(f"Salary ${total:,} is over the ${SALARY_CAP:,} cap")
    for (_, p), slot in zip(players.iterrows(), slots):
        if slot not in p["slots"]:
            errors.append(f"{p['name']} cannot play {slot}")
    if players["game"].nunique() < MIN_GAMES:
        errors.append(f"Players must come from at least {MIN_GAMES} games")
    return errors


def upload_csv_text(slotted: list[list[int]]) -> str:
    """DraftKings bulk-upload CSV: one row of dk_ids per lineup, in ROSTER_SLOTS order."""
    lines = [",".join(ROSTER_SLOTS)]
    lines += [",".join(str(int(i)) for i in row) for row in slotted]
    return "\n".join(lines) + "\n"
