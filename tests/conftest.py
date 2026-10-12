"""Synthetic 2-game slate shared by the optimizer/simulation/lineup tests."""
import pandas as pd
import pytest

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
