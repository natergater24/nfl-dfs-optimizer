import numpy as np
import pandas as pd
import pytest

from nfldfs import team_env


def _frame(n=300, seed=0):
    rng = np.random.default_rng(seed)
    it = rng.uniform(14, 32, n)
    m = rng.uniform(-10, 10, n)
    f = pd.DataFrame({"implied_total": it, "exp_margin": m})
    f["pass_att"] = 20 + 0.5 * it - 0.3 * m
    f["pass_yds"] = 100 + 5 * it - 2 * m
    f["pass_td"] = 0.07 * it
    f["ints"] = 0.8 + 0 * it
    f["carries"] = 15 + 0.4 * it + 0.3 * m
    f["rush_yds"] = 60 + 2.5 * it + 1 * m
    f["rush_td"] = 0.04 * it
    return f


def test_fit_recovers_exact_linear_relationships():
    model = team_env.fit_team_model(_frame())
    assert model["n_games"] == 300
    assert np.allclose(model["coef"]["pass_yds"], [100, 5, -2], atol=1e-6)
    assert np.allclose(model["coef"]["carries"], [15, 0.4, 0.3], atol=1e-6)


def test_fit_refuses_tiny_samples():
    with pytest.raises(ValueError, match="at least 50"):
        team_env.fit_team_model(_frame(n=10))


def test_expected_team_stats_clips_and_names_columns():
    model = team_env.fit_team_model(_frame())
    out = team_env.expected_team_stats(pd.DataFrame({"team": ["LAR", "XXX"], "implied_total": [25.0, 0.0],
                                                     "exp_margin": [3.0, -40.0]}), model)
    assert list(out.columns) == ["team"] + [f"exp_{s}" for s in team_env.TEAM_STATS]
    assert out.iloc[0].exp_pass_yds == pytest.approx(100 + 5 * 25 - 2 * 3)
    assert (out.drop(columns="team") > 0).all().all()


def test_build_training_frame_joins_on_team_week():
    tw = pd.DataFrame({"season": [2026], "week": [5], "team": ["LAR"], "pass_att": [35], "pass_yds": [310],
                       "pass_td": [2], "ints": [1], "targets": [33], "carries": [25], "rush_yds": [110], "rush_td": [1]})
    sched = pd.DataFrame({"season": [2026, 2026], "week": [5, 5], "team": ["LAR", "ARI"], "opp": ["ARI", "LAR"],
                          "is_home": [True, False], "implied_total": [25.0, 22.0], "exp_margin": [3.0, -3.0],
                          "points": [27, 20]})
    f = team_env.build_training_frame(tw, sched)
    assert len(f) == 1 and f.iloc[0].implied_total == 25.0
