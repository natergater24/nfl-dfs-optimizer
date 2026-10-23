import numpy as np
import pandas as pd
import pytest

from nbadfs import rules
from nbadfs.dk import parse_salaries
from pathlib import Path

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _pool():
    return parse_salaries((FIX / "nba_salaries_sample.csv").read_text())


def _lineup(pool):
    names = ["Braden Smith", "Grayson Allen", "Sam Hauser", "Trey Lyles", "Ivica Zubac",
             "Isaiah Evans", "Royce O'Neale", "Giannis Antetokounmpo"]
    df = pool.set_index("name").loc[names].reset_index()
    return df, ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"]


def test_eligible_slots():
    assert rules.eligible_slots("SG/SF") == ["SG", "SF", "G", "F", "UTIL"]
    assert rules.eligible_slots("C") == ["C", "UTIL"]
    assert rules.eligible_slots("PF/C") == ["PF", "C", "F", "UTIL"]


def test_dk_points_bonuses():
    assert rules.dk_points(20, 2, 10, 5, 1, 0, 3) == pytest.approx(43.0)
    # triple double: 12 pts, 10 reb, 10 ast -> +3 only
    assert rules.dk_points(12, 0, 10, 10, 0, 0, 0) == pytest.approx(12 + 12.5 + 15 + 3)
    # no bonus
    assert rules.dk_points(9, 0, 9, 9, 0, 0, 0) == pytest.approx(9 + 11.25 + 13.5)
    arr = rules.dk_points(np.array([20, 12]), np.array([2, 0]), np.array([10, 10]),
                          np.array([5, 10]), np.array([1, 0]), np.array([0, 0]), np.array([3, 0]))
    assert arr == pytest.approx([43.0, 42.5])


def test_validate_lineup():
    df, slots = _lineup(_pool())
    assert rules.validate_lineup(df, slots) == []
    one_game = df.assign(game="AAA@BBB")
    assert any("2 games" in e for e in rules.validate_lineup(one_game, slots))
    pricey = df.assign(salary=df["salary"] + 3000)
    assert any("$50,000" in e for e in rules.validate_lineup(pricey, slots))
    bad_slots = ["C"] + slots[1:]
    assert rules.validate_lineup(df, bad_slots)
    assert rules.validate_lineup(df.iloc[:7], slots[:7])


def test_upload_csv_text():
    text = rules.upload_csv_text([[1, 2, 3, 4, 5, 6, 7, 8]])
    lines = text.strip().splitlines()
    assert lines[0] == "PG,SG,SF,PF,C,G,F,UTIL"
    assert lines[1] == "1,2,3,4,5,6,7,8"
