import numpy as np
import pandas as pd
import pytest

from nbadfs import project as P


def _row(i, name, team, slots, salary=6000, playable=True, dk_avg=30.0, **kw):
    r = dict(dk_id=i, name=name, team=team, opp="BBB" if team == "AAA" else "AAA",
             game="AAA@BBB", tip="2026-10-24T19:00:00", positions="/".join(s for s in slots if s != "UTIL"),
             slots=slots, salary=salary, status="" if playable else "O", dk_avg=dk_avg, playable=playable,
             games_last=np.nan, min_last=np.nan, rate_last=np.nan, games_cur=np.nan, min_cur=np.nan,
             rate_cur=np.nan)
    r.update(kw)
    return r


def _lines(a=110.0, b=110.0):
    return pd.DataFrame({"team": ["AAA", "BBB"], "opp": ["BBB", "AAA"], "total": [a + b] * 2,
                         "spread": [0.0, 0.0], "implied_total": [a, b], "opp_implied": [b, a]})


def _go(rows, lines=None):
    m = pd.DataFrame(rows)
    return P.project(m[P.BASE_COLUMNS], _lines() if lines is None else lines, m)


def test_blend_weights():
    kw = dict(games_last=60.0, min_last=30.0, rate_last=1.0, min_cur=20.0, rate_cur=2.0)
    out = _go([_row(1, "A", "AAA", ["PG", "G", "UTIL"], games_cur=0.0, **kw),
               _row(2, "B", "AAA", ["PG", "G", "UTIL"], games_cur=8.0, **kw)])
    assert out.loc[0, "minutes"] == pytest.approx(30.0) and out.loc[0, "rate"] == pytest.approx(1.0)
    assert out.loc[1, "minutes"] == pytest.approx(25.0) and out.loc[1, "rate"] == pytest.approx(1.5)
    assert out.loc[1, "median"] == pytest.approx(37.5)
    assert out.loc[0, "sd"] == pytest.approx(0.3 * 30 + 2)


def test_out_minutes_redistributed():
    g = ["PG", "G", "UTIL"]
    base = dict(games_cur=20.0, min_cur=30.0, rate_cur=1.0, games_last=20.0, min_last=30.0, rate_last=1.0)
    rows = [_row(1, "Out", "AAA", g, playable=False, **base),
            _row(2, "B", "AAA", ["SG", "G", "UTIL"], **{**base, "min_cur": 30.0, "min_last": 30.0}),
            _row(3, "C", "AAA", ["PG", "G", "UTIL"], **{**base, "min_cur": 20.0, "min_last": 20.0}),
            _row(4, "Big", "AAA", ["C", "UTIL"], **base)]
    out = _go(rows)
    assert out.loc[0, "median"] == 0 and out.loc[0, "minutes"] == 0
    assert out.loc[1, "minutes"] <= 40 and out.loc[2, "minutes"] <= 40
    assert out.loc[1, "minutes"] + out.loc[2, "minutes"] == pytest.approx(30 + 20 + 30)
    assert out.loc[3, "minutes"] == pytest.approx(30.0)
    assert out.loc[1, "median"] > 30.0 * 1.0 - 1e-9


def test_missing_line_uses_league_average_and_flags():
    base = dict(games_cur=20.0, min_cur=30.0, rate_cur=1.0)
    rows = [_row(1, "A", "AAA", ["PG"], **base), _row(2, "X", "ZZZ", ["PG"], opp="YYY", game="ZZZ@YYY", **base)]
    out = _go(rows, _lines(120.0, 100.0))   # league avg 110; AAA scale 1.0909
    assert not out.loc[0, "line_missing"] and out.loc[1, "line_missing"]
    assert out.loc[1, "implied_total"] == pytest.approx(110.0)
    assert out.loc[1, "median"] == pytest.approx(30.0)
    assert out.loc[0, "median"] == pytest.approx(30.0 * 120 / 110)


def test_rookie_and_unmatched_baselines():
    out = _go([_row(1, "Rookie", "AAA", ["PG"], salary=4000, dk_avg=0.0),
               _row(2, "Vet", "AAA", ["PG"], salary=4000, dk_avg=25.0)])
    assert out.loc[0, "median"] == pytest.approx(18.0) and out.loc[0, "minutes"] == 0
    assert out.loc[1, "median"] == pytest.approx(25.0)
    assert list(out.columns) == P.POOL_COLUMNS


def test_no_lines_at_all_uses_default():
    base = dict(games_cur=20.0, min_cur=30.0, rate_cur=1.0)
    empty = pd.DataFrame(columns=["team", "opp", "total", "spread", "implied_total", "opp_implied"])
    out = _go([_row(1, "A", "AAA", ["PG"], **base), _row(2, "B", "BBB", ["PG"], **base)], empty)
    assert P.DEFAULT_IMPLIED == 112.0
    assert (out["implied_total"] == 112.0).all() and (out["opp_implied"] == 112.0).all()
    assert out["line_missing"].all()
    assert out.loc[0, "median"] == pytest.approx(30.0)
