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
    with path.open() as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
    assert len(rows) == 3 and sorted(map(int, rows[1])) == sorted(good.dk_id.tolist())


def test_write_upload_csv_refuses_invalid_lineup(pool, tmp_path):
    bad = _lineup(pool, _valid_ids(pool)).iloc[:8]
    with pytest.raises(ValueError):
        dk_rules.write_upload_csv([bad], tmp_path / "upload.csv")


def test_upload_csv_text_matches_file(pool, tmp_path):
    good = _lineup(pool, _valid_ids(pool))
    text = dk_rules.upload_csv_text([good])
    dk_rules.write_upload_csv([good], tmp_path / "u.csv")
    assert text == (tmp_path / "u.csv").read_text() and text.startswith("QB,RB,RB,WR,WR,WR,TE,FLEX,DST\n")
