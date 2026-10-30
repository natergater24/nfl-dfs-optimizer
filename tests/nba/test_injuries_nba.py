"""NBA injury rules: statuses, lean-out never suggested, sitting in sims, slot-aware backups."""
import numpy as np
import pandas as pd
import pytest

from nbadfs import dk
from nbadfs import lineups as L
from nbadfs import project as P
from nbadfs import simulate as S
from nbadfs.config import MIN_GAMES, NBA_CONTEST_TYPES, SALARY_CAP
from nbadfs.ownership import sample_field
from nbadfs.rules import ROSTER_SLOTS, validate_lineup
from nfldfs import config as nfl_config
from nfldfs.injuries import classify
from nfldfs.lineups import BACKUP_COLUMNS, NO_BACKUP
from nfldfs.sim_eval import lineup_scores

from .slate_fixture import ready_pool, slate_pool

HEADER = "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame,Status,Starting\n"


def _csv(statuses):
    rows = []
    for i, st in enumerate(statuses):
        rows.append(f"PG,P{i} ({100 + i}),P{i},{100 + i},PG/G/UTIL,5000,AAA@BBB 10/23/2026 07:00PM ET,"
                    f"{'AAA' if i % 2 else 'BBB'},20.0,{st},")
    return HEADER + "\n".join(rows) + "\n"


def test_nba_status_classes():
    statuses = ["", "GTD", "Q", "D", "O", "OUT", "IR", "DTD", "P"]
    df = classify(dk.parse_salaries(_csv(statuses)))
    by = dict(zip(statuses, df.itertuples()))
    for s in ("D", "O", "OUT", "IR"):
        assert not by[s].playable and by[s].inj_class == "excluded" and not by[s].recommendable
    for s in ("GTD", "Q", "DTD"):
        assert by[s].playable and by[s].inj_class == "questionable"
        assert by[s].play_prob == nfl_config.Q_PLAY_PROB
    for s in ("", "P"):
        assert by[s].playable and by[s].inj_class == "healthy" and by[s].play_prob == 1.0
    assert by["O"].status == "O" and by["O"].inj_tag == "OUT" and by["OUT"].inj_tag == "OUT"
    assert by["DTD"].inj_tag == "GTD" and by["D"].inj_tag == "D" and by["IR"].inj_tag == "IR"


def _prow(i, name, slots, playable=True, **kw):
    r = dict(dk_id=i, name=name, team="AAA", opp="BBB", game="AAA@BBB", tip="2026-10-24T19:00:00",
             positions="/".join(s for s in slots if s != "UTIL"), slots=slots, salary=6000,
             status="" if playable else "O", dk_avg=30.0, playable=playable, games_cur=20.0, min_cur=30.0,
             rate_cur=1.0, games_last=20.0, min_last=30.0, rate_last=1.0)
    r.update(kw)
    return r


def test_lean_out_minutes_redistributed_like_out():
    g = ["PG", "G", "UTIL"]
    m = pd.DataFrame([_prow(1, "LeanOut", g, status="Q"), _prow(2, "B", g, min_cur=20.0, min_last=20.0),
                      _prow(3, "Big", ["C", "UTIL"])])
    m["lean"] = ["out", "", ""]
    lines = pd.DataFrame({"team": ["AAA", "BBB"], "opp": ["BBB", "AAA"], "total": [220.0] * 2,
                          "spread": [0.0, 0.0], "implied_total": [110.0, 110.0], "opp_implied": [110.0, 110.0]})
    plain = P.project(m[P.BASE_COLUMNS], lines, m)
    assert plain.loc[1, "minutes"] == pytest.approx(20.0)                # no injury columns: unchanged
    out = P.project(classify(m), lines, m)
    assert out.loc[0, "median"] == 0 and out.loc[0, "minutes"] == 0
    assert out.loc[1, "minutes"] == pytest.approx(40.0) and out.loc[2, "minutes"] == pytest.approx(30.0)
    assert {"inj_tag", "inj_class", "lean", "recommendable", "play_prob"} <= set(out.columns)
    assert out.loc[0, "inj_tag"] == "Q" and not out.loc[0, "recommendable"]


def test_simulate_sits_questionable_players_deterministically():
    pool = slate_pool(n_games=2, per_team=4)
    pool["lean"] = ""
    pool.loc[0, "status"] = "Q"
    pool.loc[1, ["status", "lean"]] = ["Q", "out"]
    pool = classify(pool)
    raw = S.simulate(pool, 4000, 3, sit=False)
    sims = S.simulate(pool, 4000, 3)
    assert np.array_equal(sims, S.simulate(pool, 4000, 3))
    assert 0.11 < (sims[:, 0] == 0).mean() < 0.19 and (raw[:, 0] == 0).mean() < 0.02
    assert (sims[:, 1] == 0).all() and (raw[:, 1] == 0).all()           # lean-out never plays
    assert np.array_equal(sims[:, 2:], raw[:, 2:])
    # pools without injury columns: the old draws, untouched
    plain = pool.drop(columns=["inj_tag", "inj_class", "lean", "recommendable", "play_prob"])
    assert np.array_equal(S.simulate(plain, 4000, 3)[:, 2:], raw[:, 2:])


def _tag(pool, statuses: dict, leans: dict | None = None):
    p = pool.drop(columns=[c for c in ("own_pct", "tier", "floor", "ceiling") if c in pool.columns]).copy()
    p["floor"] = np.nan
    p["ceiling"] = np.nan
    p["lean"] = ""
    for d, st in statuses.items():
        p.loc[p.dk_id == d, "status"] = st
    for d, lv in (leans or {}).items():
        p.loc[p.dk_id == d, "lean"] = lv
    return ready_pool(classify(p), n_sims=800)


@pytest.fixture(scope="module")
def plain_slate():
    pool, sims = ready_pool(slate_pool(), n_sims=800)
    field = sample_field(pool, 300, np.random.default_rng(5))
    lus, _ = L.build_all(pool, sims, field, n_candidates=3)
    rec = lus[lus["rank"] == 0]
    counts = rec["dk_id"].value_counts()
    return pool, field, rec, [int(d) for d in counts.index[:2]]


def test_lean_out_excluded_everywhere_nba(plain_slate):
    pool, field, rec, (fav, second) = plain_slate
    # fav: Q but the news says "ruled out"; second: Q with unclear news (stays suggestable, discounted).
    # second gets a big projection so he is surely in rank-0 lineups even at play_prob 0.85
    pool = pool.copy()
    m = pool.dk_id == second
    pool.loc[m, "median"] = pool.loc[m, "median"] * 1.6
    pool.loc[m, "sd"] = 0.3 * pool.loc[m, "median"] + 2
    tagged, sims = _tag(pool, {fav: "Q", second: "Q"}, {fav: "out", second: "unclear"})
    lus, swaps = L.build_all(tagged, sims, field, n_candidates=3)
    assert fav not in set(lus.dk_id) and fav not in set(swaps.in_id)
    contest = NBA_CONTEST_TYPES["tournament"]
    ids, _ = L.best_lineup(tagged, sims, field, contest, n_candidates=2)
    assert fav not in ids
    # backups for every rank-0 lineup holding the questionable player never bring in the lean-out one
    fs = lineup_scores(sims, field)
    r0 = lus[lus["rank"] == 0]
    keys = [k for k, g in r0.groupby("contest_key") if second in set(g.dk_id)]
    assert keys                                                          # not vacuous
    for k in keys:
        lineup = r0[r0.contest_key == k].dk_id.tolist()
        bk = L.injury_backups(tagged, sims, fs, lineup, NBA_CONTEST_TYPES[k])
        assert len(bk) == 1 and bk.tagged_dk_id.iat[0] == second
        assert fav not in {int(i) for ids_ in bk.in_dk_ids for i in ids_}
    # the user's lock still wins, with a warning
    ids, _ = L.best_lineup(tagged, sims, field, contest, locks=[fav], n_candidates=1)
    assert fav in ids
    name = tagged.set_index("dk_id").at[fav, "name"]
    assert L.out_lock_warnings(tagged, [fav]) == [f"⚠ {name}: news leans out"]


def _slot_order(pool, ids):
    from nbadfs.optimizer import assign_slots
    by = pool.set_index("dk_id")
    order = assign_slots([list(by.at[d, "slots"]) for d in ids])
    assert order is not None
    return [ids[k] for k in order]


def _legal(pool, ids):
    players = pool.set_index("dk_id").loc[list(ids)].reset_index()
    return validate_lineup(players, list(ROSTER_SLOTS)) == []


def _first(df, positions):
    return int(df[df.positions == positions].sort_values("salary").dk_id.iat[0])


def _make_all_slots(pool, d, **vals):
    m = pool.dk_id == d
    for k, v in vals.items():
        pool.loc[m, k] = v
    pool.loc[m, "slots"] = pd.Series([list(ROSTER_SLOTS) if vals.get("positions") == "PG/SG/SF/PF/C"
                                      else [s for s in ROSTER_SLOTS if s in ("C", "UTIL")]] * int(m.sum()),
                                     index=pool.index[m])


def test_nba_backup_respects_slots_and_two_games():
    pool, _ = ready_pool(slate_pool(n_games=3))
    pool = pool.drop(columns=["own_pct", "tier"])
    g0 = pool[pool.game == pool.game.iat[0]]
    g1 = pool[pool.game != pool.game.iat[0]]
    # 7 players from game 0 plus a PG from another game, tagged GTD
    seven = [_first(g0, p) for p in ("SG", "SF", "PF", "C", "PG/SG", "SF/PF", "PF/C")]
    one = _first(g1, "PG")
    ids = _slot_order(pool, seven + [one])
    pool.loc[pool.dk_id.isin(ids), "salary"] = 5000                    # room under the cap for any 1:1
    # a superstar from game 0 eligible everywhere: he would win any slot, but would leave one game only
    star = int(g0[~g0.dk_id.isin(ids)].dk_id.iat[0])
    _make_all_slots(pool, star, positions="PG/SG/SF/PF/C", median=90.0, sd=0.3 * 90 + 2, salary=3000)
    tagged, sims = _tag(pool, {one: "GTD"})
    field = sample_field(tagged, 200, np.random.default_rng(2))
    fs = lineup_scores(sims, field)
    bk = L.injury_backups(tagged, sims, fs, ids, NBA_CONTEST_TYPES["double_up"])
    assert list(bk.columns) == BACKUP_COLUMNS and len(bk) == 1
    r = bk.iloc[0]
    assert r.tagged_dk_id == one and r.kind == "1:1" and star not in list(r.in_dk_ids)
    j = int(r.in_dk_ids[0])
    new = [j if d == one else d for d in ids]
    by = tagged.set_index("dk_id")
    assert ROSTER_SLOTS[ids.index(one)] in list(by.at[j, "slots"])        # same slot
    assert by.loc[new, "game"].nunique() >= MIN_GAMES and _legal(tagged, new)
    assert by.at[j, "inj_class"] == "healthy"
    assert r.remaining_salary == SALARY_CAP - int(by.loc[new, "salary"].sum())
    assert r.metric_before == pytest.approx(float(bk.metric_before.iat[0]))
    # once the lineup spans two games without the tagged player, the star is the pick
    ids2 = _slot_order(pool, seven[:6] + [_first(g1, "C"), one])
    bk2 = L.injury_backups(tagged, sims, fs, ids2, NBA_CONTEST_TYPES["double_up"])
    assert [int(i) for i in bk2.in_dk_ids.iat[0]] == [star]


def test_nba_backup_two_player_then_none():
    pool, sims = ready_pool(slate_pool(n_games=3))
    field = sample_field(pool, 100, np.random.default_rng(1))
    ids, _ = L.best_lineup(pool, sims, field, NBA_CONTEST_TYPES["double_up"], n_candidates=1)
    t = ids[0]                                                             # the PG slot
    pool = pool.drop(columns=["own_pct", "tier"])
    pool.loc[pool.dk_id.isin(ids), "salary"] = SALARY_CAP // 8              # exactly at the cap
    pool.loc[~pool.dk_id.isin(ids), "salary"] = 6400                        # every 1:1 goes over
    cheap = int(pool[~pool.dk_id.isin(ids)].dk_id.iat[0])
    _make_all_slots(pool, cheap, positions="C", salary=3000)               # fits C/UTIL only, not PG
    tagged, sims = _tag(pool, {t: "Q"})
    fs = lineup_scores(sims, sample_field(tagged, 100, np.random.default_rng(1)))
    bk = L.injury_backups(tagged, sims, fs, ids, NBA_CONTEST_TYPES["double_up"])
    r = bk.iloc[0]
    assert r.kind == "two-player" and int(r.out_dk_ids[0]) == t and len(r.in_dk_ids) == 2
    assert cheap in [int(i) for i in r.in_dk_ids]
    new = [d for d in ids if d not in list(r.out_dk_ids)] + [int(i) for i in r.in_dk_ids]
    by = tagged.set_index("dk_id")
    assert r.remaining_salary == SALARY_CAP - int(by.loc[new, "salary"].sum()) >= 0
    assert by.loc[new, "game"].nunique() >= MIN_GAMES and r.message.startswith("If ")
    # nothing healthy fits at all
    tagged2 = tagged.copy()
    tagged2.loc[~tagged2.dk_id.isin(ids), "salary"] = 20_000
    bk2 = L.injury_backups(tagged2, sims, fs, ids, NBA_CONTEST_TYPES["double_up"])
    assert bk2.kind.iat[0] == "none" and bk2.message.iat[0] == NO_BACKUP and list(bk2.in_dk_ids.iat[0]) == []


def test_nba_backups_empty_when_lineup_healthy(plain_slate):
    pool, field, rec, _ = plain_slate
    p = classify(pool.assign(lean=""))
    sims = S.simulate(p, 200, 1)
    lineup = rec[rec.contest_key == rec.contest_key.iat[0]].dk_id.tolist()
    bk = L.injury_backups(p, sims, lineup_scores(sims, field), lineup, NBA_CONTEST_TYPES["double_up"])
    assert len(bk) == 0 and list(bk.columns) == BACKUP_COLUMNS
