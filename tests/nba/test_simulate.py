import numpy as np
import pandas as pd

from nbadfs import simulate as S


def _pool():
    rows = []
    for i, (team, game) in enumerate([("AAA", "AAA@BBB"), ("AAA", "AAA@BBB"), ("BBB", "AAA@BBB"),
                                      ("CCC", "CCC@DDD"), ("AAA", "AAA@BBB")]):
        rows.append(dict(dk_id=i, team=team, game=game, median=40.0 + i, sd=0.3 * (40.0 + i) + 2,
                         playable=i != 4))
    return pd.DataFrame(rows)


def test_simulate_deterministic_and_unbiased():
    p = _pool()
    a = S.simulate(p, 10_000, 7)
    assert a.dtype == np.float32 and a.shape == (10_000, 5)
    assert np.array_equal(a, S.simulate(p, 10_000, 7))
    assert not np.array_equal(a, S.simulate(p, 10_000, 8))
    for j in range(4):
        assert abs(a[:, j].mean() / p["median"][j] - 1) < 0.03
    assert (a[:, 4] == 0).all()
    assert np.corrcoef(a[:, 0], a[:, 1])[0, 1] > 0.015         # same team and game
    assert np.corrcoef(a[:, 0], a[:, 2])[0, 1] > 0.0            # same game
    assert abs(np.corrcoef(a[:, 0], a[:, 3])[0, 1]) < 0.05    # different game


def test_summarize_fills_floor_ceiling_keeps_median():
    p = _pool()
    out = S.summarize(S.simulate(p, 2000, 1), p)
    assert (out["floor"] <= out["ceiling"]).all() and (out["median"] == p["median"]).all()
    assert "floor" not in p
