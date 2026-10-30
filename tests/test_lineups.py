import numpy as np
import pandas as pd
import pytest

from nfldfs import config, dk_rules, lineups, ownership, simulate


@pytest.fixture
def projected(pool, team_exp):
    sims = simulate.simulate(pool, team_exp, 400, seed=7)
    p = pool.join(simulate.summarize(sims, pool))
    p["own_pct"] = ownership.estimate_ownership(p)
    p["tier"] = p.own_pct.map(ownership.ownership_tier)
    return p, sims


def test_objective_values(projected):
    p, _ = projected
    v = lineups.objective_values(p, {"ceiling": 1.0, "own_penalty": 0.3})
    assert np.allclose(v, p.ceiling - 0.3 * p.own_pct)


def test_candidates_are_distinct_and_valid(projected):
    p, sims = projected
    c = lineups.generate_candidates(p, sims, config.CONTEST_TYPES["tournament"], 4, np.random.default_rng(0))
    assert len(c) == 4
    for i, a in enumerate(c):
        assert dk_rules.validate_lineup(p.loc[a]) == []
        for b in c[:i]:
            assert len(set(a) - set(b)) >= config.MIN_UNIQUE_PLAYERS


def test_build_all_covers_every_contest_type(projected):
    p, sims = projected
    lus, swaps, field = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert list(lus.columns) == lineups.LINEUP_COLUMNS
    assert set(lus.contest_key) == set(config.CONTEST_TYPES)
    for key, g in lus[lus["rank"] == 0].groupby("contest_key"):
        assert len(g) == 9 and list(g.slot) == list(dk_rules.ROSTER_SLOTS)
        assert dk_rules.validate_lineup(g) == [] and g.total_salary.iloc[0] <= 50_000
        assert g.metric.between(0, 1).all()
        if config.CONTEST_TYPES[key]["stack"]:
            qb = g[g.position == "QB"].iloc[0]
            assert ((g.team == qb.team) & g.position.isin(["WR", "TE"])).any()
    assert list(swaps.columns) == ["contest_key"] + lineups.SWAP_COLUMNS


def test_swaps_respect_cap_position_and_ownership(projected):
    p, sims = projected
    lus, swaps, field = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert (swaps.remaining_salary >= 0).all()
    pos = dict(zip(p.dk_id, p.position))
    assert all(pos[a] == pos[b] for a, b in zip(swaps.out_dk_id, swaps.in_dk_id))
    for key, g in swaps.groupby("contest_key"):
        rec = set(lus[(lus.contest_key == key) & (lus["rank"] == 0)].dk_id)
        assert not set(g.in_dk_id) & rec and set(g.out_dk_id) <= rec
        assert len(g) <= config.N_SWAPS
        if config.CONTEST_TYPES[key]["group"] == "Tournament":
            assert (g.in_own_pct < config.SWAP_MAX_OWN_TOURNAMENT).all()


def test_build_all_returns_field(projected):
    p, sims = projected
    _, _, field = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert field.shape == (150, 9)


def test_swaps_spread_across_positions(projected):
    p, sims = projected
    _, swaps, _ = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    assert swaps.groupby(["contest_key", "position"]).size().max() <= config.MAX_SWAPS_PER_POSITION


def test_best_lineup_respects_locks_and_excludes(projected):
    from nfldfs.sim_eval import sample_field
    p, sims = projected
    field = sample_field(p, 100, np.random.default_rng(0))
    lock = int(p.loc[p["name"] == "CCC TE3", "dk_id"].iloc[0])
    excl = int(p.loc[p["name"] == "AAA WR1", "dk_id"].iloc[0])
    rows, metric = lineups.best_lineup(p, sims, field, config.CONTEST_TYPES["tournament"],
                                       locks=[lock], excludes=[excl], n_candidates=4)
    lu = p.loc[rows]
    assert dk_rules.validate_lineup(lu) == [] and 0.0 <= metric <= 1.0
    assert lock in lu.dk_id.tolist() and excl not in lu.dk_id.tolist()


# ---------------------------------------------------------------- injuries

from nfldfs import injuries, sim_eval  # noqa: E402


def _tagged(p, tags: dict):
    """Pool with injury columns: tags = {name: tag or (tag, lean)} (no network: the news lean is set directly)."""
    p = p.copy()
    p["status"], p["lean"] = "", ""
    for name, t in tags.items():
        tag, ln = t if isinstance(t, tuple) else (t, "")
        m = p["name"] == name
        p.loc[m, "status"], p.loc[m, "lean"] = tag, ln
        if tag in ("D", "OUT", "IR"):
            p.loc[m, "playable"] = False          # DraftKings' PLAYABLE_STATUSES
    return injuries.classify(p)


def _id(p, name):
    return int(p.loc[p["name"] == name, "dk_id"].iloc[0])


def _row(p, name):
    return int(p.index[p["name"] == name][0])


def _field_scores(p, sims, n=150, seed=0):
    return sim_eval.lineup_scores(sims, sim_eval.sample_field(p, n, np.random.default_rng(seed)))


def _favourite(p, sims):
    """The non-QB/DST player the untagged build uses most (so excluding him is a real test)."""
    lus, _, _ = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    lus = lus[~lus.position.isin(["QB", "DST"])]
    return lus["name"].value_counts().index[0]


def _all_suggested_ids(p, sims):
    lus, swaps, field = lineups.build_all(p, sims, n_candidates=3, field_size=150, seed=1)
    fs = sim_eval.lineup_scores(sims, field)
    row_of = {int(d): i for i, d in enumerate(p.dk_id)}
    backups = []
    for key, g in lus[lus["rank"] == 0].groupby("contest_key"):
        rows = [row_of[int(d)] for d in g.dk_id]
        backups.append(lineups.injury_backups(p, sims, fs, rows, config.CONTEST_TYPES[key]))
    bk = pd.concat(backups, ignore_index=True)
    ins = {int(d) for ids in bk.in_dk_ids for d in ids}
    return set(lus.dk_id.astype(int)), set(swaps.in_dk_id.astype(int)), ins, field


def test_lean_out_excluded_everywhere_nfl(projected):
    p, sims = projected
    fav = _favourite(p, sims)
    # fav: DK says Q but the blurb says "ruled out"; a Q (unclear) teammate keeps backups busy
    q_name = "AAA QB1" if fav != "AAA QB1" else "CCC QB1"
    t = _tagged(p, {fav: ("Q", "out"), q_name: "Q"})
    assert not t.loc[t["name"] == fav, "recommendable"].iloc[0]
    tsims = injuries.apply_play_prob(sims, t, 7)
    lu_ids, swap_ids, backup_ids, field = _all_suggested_ids(t, tsims)
    bad = _id(t, fav)
    assert bad not in lu_ids and bad not in swap_ids and bad not in backup_ids
    rows, _ = lineups.best_lineup(t, tsims, field, config.CONTEST_TYPES["tournament"], n_candidates=3)
    assert bad not in set(t.dk_id.iloc[rows])
    # a backup for a lineup that holds a Q player never brings him in either
    fs = sim_eval.lineup_scores(tsims, field)
    lu = lineups.generate_candidates(t, tsims, config.CONTEST_TYPES["double_up"], 1, np.random.default_rng(0),
                                     locks=[_id(t, q_name)])[0]
    bk = lineups.injury_backups(t, tsims, fs, lu, config.CONTEST_TYPES["tournament"])
    assert len(bk) == 1 and bk.tagged_dk_id.iloc[0] == _id(t, q_name)
    assert bad not in {int(d) for ids in bk.in_dk_ids for d in ids}


def test_doubtful_never_suggested(projected):
    p, sims = projected
    fav = _favourite(p, sims)
    t = _tagged(p, {fav: "D", "AAA QB1": "Q"})
    tsims = injuries.apply_play_prob(sims, t, 7)
    lu_ids, swap_ids, backup_ids, _ = _all_suggested_ids(t, tsims)
    bad = _id(t, fav)
    assert bad not in lu_ids | swap_ids | backup_ids
    assert (tsims[:, _row(t, fav)] == 0).all()


def test_questionable_objective_is_discounted(projected):
    p, _ = projected
    t = _tagged(p, {"AAA WR1": "Q", "AAA WR2": "P"})
    w = config.CONTEST_TYPES["tournament"]["weights"]
    base, disc = lineups.objective_values(p, w), lineups.objective_values(t, w)
    i, j = _row(t, "AAA WR1"), _row(t, "AAA WR2")
    own = w.get("own_penalty", 0) * p.own_pct.iat[i]
    assert disc[i] == pytest.approx((base[i] + own) * config.Q_PLAY_PROB - own)
    assert disc[j] == pytest.approx(base[j])


def test_lock_wins_for_excluded(projected):
    p, sims = projected
    t = _tagged(p, {"CCC WR2": ("Q", "out"), "DDD RB2": "OUT"})
    tsims = injuries.apply_play_prob(sims, t, 7)
    field = sim_eval.sample_field(t, 100, np.random.default_rng(0))
    locks = [_id(t, "CCC WR2"), _id(t, "DDD RB2")]
    rows, _ = lineups.best_lineup(t, tsims, field, config.CONTEST_TYPES["tournament"], locks=locks, n_candidates=2)
    lu = t.iloc[rows]
    assert set(locks) <= set(lu.dk_id) and dk_rules.validate_lineup(lu) == []
    others = set(lu.dk_id) - set(locks)
    assert t.set_index("dk_id").loc[list(others), "recommendable"].all()
    fs = sim_eval.lineup_scores(tsims, field)
    bk = lineups.injury_backups(t, tsims, fs, rows, config.CONTEST_TYPES["tournament"])
    assert set(bk.tagged_dk_id) == set(locks)                     # user-forced picks still get a backup


def _manual_lineup(p):
    names = ["AAA QB1", "AAA RB1", "BBB RB2", "AAA WR1", "BBB WR2", "CCC WR5", "AAA TE3", "DDD WR6", "DDD DST1"]
    rows = [_row(p, n) for n in names]
    assert dk_rules.validate_lineup(p.iloc[rows]) == []
    return rows


def test_backup_one_to_one(projected):
    p, sims = projected
    t = _tagged(p, {"AAA TE3": "Q", "BBB WR2": "P"})
    tsims = injuries.apply_play_prob(sims, t, 7)
    fs = _field_scores(t, tsims)
    rows = _manual_lineup(t)
    contest = config.CONTEST_TYPES["tournament"]
    bk = lineups.injury_backups(t, tsims, fs, rows, contest)
    assert list(bk.columns) == lineups.BACKUP_COLUMNS
    assert len(bk) == 1                                             # P is healthy: no backup row
    b = bk.iloc[0]
    assert b.tagged_dk_id == _id(t, "AAA TE3") and b.kind == "1:1"
    assert list(b.out_dk_ids) == [_id(t, "AAA TE3")] and len(b.in_dk_ids) == 1
    in_id = int(b.in_dk_ids[0])
    new = t.set_index("dk_id").loc[in_id]
    assert new.position == "TE" and new.inj_tag in ("", "P") and in_id not in t.dk_id.iloc[rows].tolist()
    total = int(t.salary.iloc[rows].sum()) - int(t.salary.iat[_row(t, "AAA TE3")]) + int(new.salary)
    assert b.remaining_salary == config.SALARY_CAP - total >= 0
    before = sim_eval.contest_metric(sim_eval.lineup_scores(tsims, [rows]), fs, contest["metric"])[0]
    assert b.metric_before == pytest.approx(before) and 0 <= b.metric_after <= 1


def test_backup_flex_slot_takes_any_flex_position(projected):
    p, sims = projected
    rows = _manual_lineup(p)
    in_lu = set(p["name"].iloc[rows])
    other_wrs = [n for n in p.loc[p.position == "WR", "name"] if n not in in_lu]
    t = _tagged(p, {"DDD WR6": "Q", **{n: "OUT" for n in other_wrs}})   # DDD WR6 sits in FLEX
    fs = _field_scores(t, sims)
    bk = lineups.injury_backups(t, sims, fs, rows, config.CONTEST_TYPES["tournament"])
    assert bk.kind.iloc[0] == "1:1"
    assert t.set_index("dk_id").loc[int(bk.in_dk_ids.iloc[0][0]), "position"] in ("RB", "TE")


def test_backup_falls_back_to_two_player(projected):
    p, sims = projected
    t = _tagged(p, {"AAA TE3": "Q"})
    rows = _manual_lineup(t)
    left = config.SALARY_CAP - int(t.salary.iloc[rows].sum())
    te = (t.position == "TE") & (t["name"] != "AAA TE3")
    t.loc[te, "salary"] = int(t.salary.iat[_row(t, "AAA TE3")]) + left + 500   # no TE fits 1:1 ...
    fs = _field_scores(t, sims)
    bk = lineups.injury_backups(t, sims, fs, rows, config.CONTEST_TYPES["tournament"])
    b = bk.iloc[0]
    assert b.kind == "two-player" and len(b.out_dk_ids) == 2 and len(b.in_dk_ids) == 2
    assert _id(t, "AAA TE3") in list(b.out_dk_ids)
    by = t.set_index("dk_id")
    new_ids = [i for i in t.dk_id.iloc[rows] if i not in set(b.out_dk_ids)] + [int(i) for i in b.in_dk_ids]
    new = by.loc[new_ids]
    assert dk_rules.validate_lineup(new.reset_index()) == [] and b.remaining_salary >= 0
    assert (new.loc[[int(i) for i in b.in_dk_ids], "inj_tag"].isin(["", "P"])).all()
    assert "TE" in set(by.loc[[int(i) for i in b.in_dk_ids], "position"])


def test_backup_none_message(projected):
    p, sims = projected
    others = [n for n in p.loc[p.position == "TE", "name"] if n != "AAA TE3"]
    t = _tagged(p, {"AAA TE3": "Q", **{n: "OUT" for n in others}})
    fs = _field_scores(t, sims)
    bk = lineups.injury_backups(t, sims, fs, _manual_lineup(t), config.CONTEST_TYPES["tournament"])
    b = bk.iloc[0]
    assert b.kind == "none" and b.message == "No healthy replacement fits under the cap."
    assert list(b.in_dk_ids) == [] and b.metric_after == pytest.approx(b.metric_before)


def test_backups_without_injury_columns_use_status(projected):
    p, sims = projected
    fs = _field_scores(p, sims)
    assert lineups.injury_backups(p, sims, fs, _manual_lineup(p), config.CONTEST_TYPES["tournament"]).empty
    q = p.copy()
    q.loc[q["name"] == "AAA TE3", "status"] = "Q"
    assert len(lineups.injury_backups(q, sims, fs, _manual_lineup(q), config.CONTEST_TYPES["tournament"])) == 1
