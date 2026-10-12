"""Synthetic 2-game slate shared by the optimizer/simulation/lineup tests."""
import json
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from nfldfs.nfl_stats import team_week_totals

GAMES = [("AAA", "BBB"), ("CCC", "DDD")]  # (away, home)
SALARIES = {
    "QB": [7000, 4500],
    "RB": [8000, 6000, 5000, 4000],
    "WR": [8500, 7000, 6000, 5000, 4000, 3000],
    "TE": [6000, 4000, 2500],
    "DST": [3000],
}
TGT = {"RB": [0.10, 0.06, 0.04, 0.02], "WR": [0.26, 0.20, 0.14, 0.08, 0.04, 0.02], "TE": [0.15, 0.05, 0.02]}
CAR = {"QB": [0.10, 0.0], "RB": [0.55, 0.20, 0.10, 0.03]}
CATCH = {"RB": 0.78, "WR": 0.64, "TE": 0.70}
YPT = {"RB": 6.0, "WR": 8.3, "TE": 7.2}
YPC = {"QB": 5.0, "RB": 4.3}
IMPLIED = {"AAA": 21.0, "BBB": 24.0, "CCC": 24.5, "DDD": 22.5}


def make_pool() -> pd.DataFrame:
    rows, dk = [], 1000
    for away, home in GAMES:
        kickoff = pd.Timestamp("2026-10-18 13:00") if away == "AAA" else pd.Timestamp("2026-10-18 16:25")
        for team, opp in ((away, home), (home, away)):
            for pos, sals in SALARIES.items():
                for r, sal in enumerate(sals):
                    dk += 1
                    rows.append(dict(
                        dk_id=dk, name=f"{team} {pos}{r + 1}", position=pos, salary=sal,
                        team=team, opp=opp, game_id=f"{away}@{home}", is_home=team == home,
                        kickoff=kickoff, status="", playable=True, dk_avg=sal / 500,
                        tgt_share=TGT[pos][r] if pos in TGT else 0.0,
                        carry_share=CAR[pos][r] if pos in CAR else 0.0,
                        catch_rate=CATCH.get(pos, 0.0), ypt=YPT.get(pos, 0.0), ypc=YPC.get(pos, 0.0),
                        implied_total=IMPLIED[team], opp_implied=IMPLIED[opp],
                    ))
    return pd.DataFrame(rows)


@pytest.fixture
def pool() -> pd.DataFrame:
    return make_pool()


@pytest.fixture
def team_exp() -> pd.DataFrame:
    return pd.DataFrame({
        "team": ["AAA", "BBB", "CCC", "DDD"],
        "exp_pass_att": 34.0, "exp_pass_yds": 240.0, "exp_pass_td": 1.6, "exp_ints": 0.8,
        "exp_carries": 26.0, "exp_rush_yds": 115.0, "exp_rush_td": 0.9,
    }).set_index("team")


SYNTH_MODEL = {"n_games": 999, "coef": {
    "pass_att": [20, 0.5, 0], "pass_yds": [100, 5, 0], "pass_td": [0, 0.07, 0], "ints": [0.8, 0, 0],
    "carries": [15, 0.4, 0.3], "rush_yds": [60, 2.5, 1], "rush_td": [0, 0.04, 0]}}


def synthetic_inputs():
    full = make_pool()
    pool_base = full[["dk_id", "name", "position", "salary", "team", "opp", "game_id", "is_home",
                      "kickoff", "dk_avg", "status", "playable"]].copy()
    rows = []
    for r in full[full.position != "DST"].itertuples(index=False):
        for wk in range(1, 7):
            t, c = round(r.tgt_share * 36), round(r.carry_share * 26)
            qb1 = r.name.endswith("QB1")
            rows.append(dict(player_id=f"P{r.dk_id}", name=r.name, position=r.position, team=r.team,
                             season=2026, week=wk, pass_att=34 if qb1 else 0, pass_yds=240.0 if qb1 else 0.0,
                             pass_td=2 if qb1 else 0, ints=1 if qb1 else 0, carries=c, rush_yds=c * r.ypc,
                             rush_td=0, targets=t, receptions=round(t * r.catch_rate), rec_yds=t * r.ypt,
                             rec_td=0, fumbles_lost=0, two_pt=0, dk_pts=0.0))
    pw = pd.DataFrame(rows)
    games = pd.DataFrame({"game_id": ["AAA@BBB", "CCC@DDD", "XXX@YYY"], "home": ["BBB", "DDD", "YYY"],
                          "away": ["AAA", "CCC", "XXX"], "total": [45.0, 47.0, 40.0],
                          "home_spread": [-3.0, 2.0, 0.0], "n_books": 3, "commence_time": "2026-10-18T17:00:00Z"})
    return pool_base, pw, team_week_totals(pw), games


APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(scope="session")
def published_dir(tmp_path_factory):
    from nfldfs import build
    pool_base, pw, tw, games = synthetic_inputs()
    res = build.build_slate(pool_base, pw, tw, SYNTH_MODEL, games, n_sims=300, seed=1, n_candidates=3,
                            field_size=150)
    out = tmp_path_factory.mktemp("published")
    meta = {"game_count": 2, "draft_group_id": 1, "slate_date": "2026-10-18", "built_at": "2026-10-15T09:00:00",
            "built_at_utc": "2026-10-15T13:00:00+00:00", "n_sims": 300, "match_rate": 1.0,
            "odds_requests_remaining": "490"}
    build.write_published(res, out, meta)
    (out / "run_status.json").write_text(json.dumps({"stage": "thursday", "ok": True, "steps": []}))
    return out


@pytest.fixture
def make_app(monkeypatch):
    def _make(pub, hosted="1"):
        monkeypatch.setenv("NFLDFS_PUBLISHED", str(pub))
        monkeypatch.setenv("NFLDFS_FORCE_HOSTED", hosted)
        monkeypatch.setenv("NFLDFS_NO_COMPONENT", "1")
        at = AppTest.from_file(APP, default_timeout=90)
        at.run()
        return at
    return _make
