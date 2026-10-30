"""Contest metrics for any lineup against the published simulations and field."""
from __future__ import annotations

from nfldfs.config import CONTEST_TYPES
from nfldfs.sim_eval import contest_metric, lineup_scores


def published_metric(d, ids, contest_key: str, field_scores) -> float:
    rows = [d.row_of[int(i)] for i in ids]
    scores = lineup_scores(d.sims, [rows])
    return float(contest_metric(scores, field_scores, CONTEST_TYPES[contest_key]["metric"])[0])


def device_backups(d, ids, contest_key: str, field_scores):
    """nfldfs.lineups.injury_backups for any lineup (dk_ids in ROSTER_SLOTS order), computed on this device."""
    import pandas as pd

    from nfldfs.lineups import BACKUP_COLUMNS, injury_backups
    picked = [int(i) for i in ids if i is not None]
    if len(picked) != 9 or len(set(picked)) != 9 or any(i not in d.row_of for i in picked):
        return pd.DataFrame(columns=BACKUP_COLUMNS)
    from nfldfs_app.ui import remembered
    stamp = ("nfl", str(d.meta.get("built_at_utc") or d.meta.get("built_at")), len(d.pool), contest_key, tuple(picked))
    return remembered(stamp, lambda: injury_backups(d.pool, d.sims, field_scores, [d.row_of[i] for i in picked],
                                                    CONTEST_TYPES[contest_key]))
