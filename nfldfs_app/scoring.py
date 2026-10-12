"""Contest metrics for any lineup against the published simulations and field."""
from __future__ import annotations

from nfldfs.config import CONTEST_TYPES
from nfldfs.sim_eval import contest_metric, lineup_scores


def published_metric(d, ids, contest_key: str, field_scores) -> float:
    rows = [d.row_of[int(i)] for i in ids]
    scores = lineup_scores(d.sims, [rows])
    return float(contest_metric(scores, field_scores, CONTEST_TYPES[contest_key]["metric"])[0])
