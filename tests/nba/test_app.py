"""🏀 NBA page: slate picker, published-data loading, regenerated sims, page rendering, Tweak & Rebuild."""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from nbadfs import build as B
from nbadfs import vegas
from nbadfs.stats import player_rates
from nfldfs_app.ui import EASTERN

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
PAGE = str(ROOT / "nba_page.py")
SLATES = [{"draft_group_id": 901, "name": "Main", "start": "2026-10-23T19:00:00", "games": 4, "published": True},
          {"draft_group_id": 902, "name": "Night", "start": "2026-10-23T21:30:00", "games": 3, "published": True},
          {"draft_group_id": 903, "name": "Late Night", "start": "2026-10-23T22:00:00", "games": 2,
           "published": False}]


def _inputs():
    text = (FIX / "nba_salaries_sample.csv").read_text()
    lines = vegas.team_lines(json.loads((FIX / "nba_odds_sample.json").read_text()), dt.date(2026, 10, 23))
    s = pd.read_parquet(FIX / "nba_espn_season_sample.parquet")
    return text, lines, player_rates(s[s.season == 2026]), player_rates(s[s.season == 2027])


@pytest.fixture(scope="module")
def nba_pub(tmp_path_factory):
    """A published/ folder whose nba/ subfolder holds two built slates (same build, different metadata)."""
    res = B.build_slate(*_inputs(), n_sims=300, seed=11, field_size=100, n_candidates=3)
    pub = tmp_path_factory.mktemp("published")
    for s in SLATES[:2]:
        r = {**res, "meta": {**res["meta"], "draft_group_id": s["draft_group_id"], "name": s["name"],
                             "start": s["start"], "games": s["games"], "odds_remaining": "463"}}
        B.write_published(r, pub / "nba" / str(s["draft_group_id"]))
    (pub / "nba" / "slates.json").write_text(json.dumps(SLATES))
    (pub / "nba" / "run_status.json").write_text(json.dumps({"stage": "nba", "ok": True, "steps": []}))
    return pub, res


def _app(monkeypatch, pub, hosted):
    monkeypatch.setenv("NFLDFS_PUBLISHED", str(pub))
    monkeypatch.setenv("NFLDFS_FORCE_HOSTED", hosted)
    monkeypatch.setenv("NFLDFS_NO_COMPONENT", "1")
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    return at


def _et(h, m):
    return dt.datetime(2026, 10, 23, h, m, tzinfo=EASTERN)


def test_published_dir_follows_env(monkeypatch, tmp_path):
    from nbadfs_app import data
    monkeypatch.setenv("NFLDFS_PUBLISHED", str(tmp_path))
    assert data.published_dir() == tmp_path / "nba"
    monkeypatch.delenv("NFLDFS_PUBLISHED")
    from nfldfs import config
    assert data.published_dir() == config.PUBLISHED / "nba"


def test_default_slate():
    from nbadfs_app.data import default_slate
    assert default_slate(SLATES, _et(12, 0)) == 0           # Main still to come
    assert default_slate(SLATES, _et(19, 5)) == 1           # Main has started -> Night
    assert default_slate(SLATES, _et(21, 45)) == 1          # Late Night isn't published -> last published
    assert default_slate(SLATES, _et(22, 30)) == 1          # everything started -> last published


def test_slate_label():
    from nbadfs_app.data import slate_label
    assert slate_label(SLATES[1]) == "Night · 9:30 PM ET · 3 games"


def test_load_slates_and_slate(nba_pub):
    from nbadfs_app import data
    pub, res = nba_pub
    slates = data.load_slates(pub / "nba")
    assert [s["draft_group_id"] for s in slates] == [901, 902, 903]
    sd = data.load_slate(pub / "nba", 902)
    assert sd.meta["name"] == "Night" and len(sd.pool) == len(res["pool"])
    assert {"name", "salary", "median", "own_pct", "tier"} <= set(sd.lineups.columns)
    assert data.load_slates(pub / "missing") is None


def test_sims_regenerated_match_build(nba_pub):
    from nbadfs_app import data
    pub, res = nba_pub
    sd = data.load_slate(pub / "nba", 901)
    sims = data.sims_for(sd)
    assert sims.shape == res["sims"].shape
    assert float(np.abs(sims - res["sims"]).max()) < 1e-5


def test_page_renders_hosted_and_local(monkeypatch, nba_pub):
    pub, _ = nba_pub
    hosted = _app(monkeypatch, pub, "1")
    assert not hosted.exception
    assert [t.value for t in hosted.title] == ["NBA DFS Lineups"]
    assert len(hosted.dataframe) >= 1
    labels = [b.label for b in hosted.sidebar.button]
    assert any("Get latest" in b for b in labels) and not any("Refresh NBA now" in b for b in labels)
    assert any("NBA results arrive in phase 3" in c.value for c in hosted.caption)
    local = _app(monkeypatch, pub, "0")
    assert not local.exception
    labels = [b.label for b in local.sidebar.button]
    assert any("Refresh NBA now" in b for b in labels) and not any("Get latest" in b for b in labels)
    radio = local.radio(key="nba_slate")
    assert list(radio.options) == ["Main · 7:00 PM ET · 4 games", "Night · 9:30 PM ET · 3 games"]


def test_page_switches_slate_and_contest(monkeypatch, nba_pub):
    pub, _ = nba_pub
    at = _app(monkeypatch, pub, "1")
    at.radio(key="nba_slate").set_value("Night · 9:30 PM ET · 3 games").run()
    from nbadfs.config import NBA_CONTEST_TYPES
    at.selectbox(key="nba_contest_label").set_value(NBA_CONTEST_TYPES["large_tournament"]["label"]).run()
    assert not at.exception and len(at.dataframe) >= 1


def test_page_no_slate_message(monkeypatch, tmp_path):
    (tmp_path / "nba").mkdir()
    (tmp_path / "nba" / "slates.json").write_text("[]")
    at = _app(monkeypatch, tmp_path, "1")
    assert not at.exception
    assert any("No NBA slate today" in i.value for i in at.info)


def test_page_not_built_message(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, "1")              # no nba/ folder at all
    assert not at.exception
    msgs = [w.value for w in at.warning]
    assert any("No NBA lineups built yet" in m and "2:00 PM and 6:30 PM ET" in m for m in msgs)
    local = _app(monkeypatch, tmp_path, "0")
    assert any("No NBA lineups built yet" in w.value for w in local.warning)
    assert any("Refresh NBA now" in b.label for b in local.sidebar.button)


def test_tweak_rebuild_excludes_player(monkeypatch, nba_pub):
    from nbadfs_app import data, views
    monkeypatch.setattr(views, "REBUILD_CANDIDATES", 3)
    pub, _ = nba_pub
    at = _app(monkeypatch, pub, "1")
    key = at.session_state["nba_contest_key"]
    dg = at.session_state["nba_dg"]
    sd = data.load_slate(pub / "nba", dg)
    rec = sd.lineups[(sd.lineups.contest_key == key) & (sd.lineups["rank"] == 0)]
    gone = int(rec.dk_id.iloc[0])
    label = views.player_label(sd.pool.set_index("dk_id").loc[gone], gone)
    at.multiselect(key="nba_excludes").set_value([label]).run()
    at.button(key="nba_rebuild").click().run()
    assert not at.exception
    rb = at.session_state["nba_rebuilt"]
    assert len(rb["ids"]) == 8 and gone not in rb["ids"] and rb["dg"] == dg
    at.button(key="nba_send").click().run()
    assert at.session_state["nba_my_ids"] == rb["ids"]


def test_rebuild_lock_on_out_player_warns(nba_pub):
    from nbadfs_app import data, views
    pub, _ = nba_pub
    sd = data.load_slate(pub / "nba", 901)
    out = sd.pool[~sd.pool.playable.astype(bool)]
    assert len(out)
    ids, metric, warnings = views.rebuild(sd, "single_entry", [int(out.dk_id.iloc[0])], [], n_candidates=2)
    assert int(out.dk_id.iloc[0]) in ids and len(ids) == 8
    assert warnings == [f"⚠ {out.name.iloc[0]} is listed Out"]


def test_my_lineup_status(nba_pub):
    from nbadfs_app import data, views
    pub, _ = nba_pub
    sd = data.load_slate(pub / "nba", 901)
    rec = sd.lineups[(sd.lineups.contest_key == "single_entry") & (sd.lineups["rank"] == 0)]
    ids = rec.dk_id.astype(int).tolist()
    ok = views.lineup_status(ids, sd.pool)
    assert ok["valid"] and ok["messages"] == []
    empty = views.lineup_status([None] * 8, sd.pool)
    assert not empty["valid"] and "8 slot(s) still empty." in empty["messages"]
    swapped = views.lineup_status([ids[1], ids[0]] + ids[2:], sd.pool)      # PG and SG swapped
    pos = sd.pool.set_index("dk_id")["slots"]
    if "PG" not in list(pos[ids[1]]) or "SG" not in list(pos[ids[0]]):
        assert not swapped["valid"] and any("cannot play" in m for m in swapped["messages"])


def test_swap_text_keeps_sign():
    from nbadfs_app import views
    assert views.delta_text(0.031) == "+3.1 pts"
    assert views.delta_text(-0.0058) == "−0.6 pts"


def test_swap_text_tiny_negative_is_not_signed_zero():
    from nbadfs_app import views
    assert views.delta_text(-0.0004) == "0.0 pts" and views.delta_text(0.0004) == "0.0 pts"
    assert views.delta_text(0) == "0.0 pts"


def test_sims_fingerprint_written_and_matches(nba_pub):
    from nbadfs_app import data
    pub, res = nba_pub
    assert len(res["meta"]["sims_fingerprint"]) == 64
    sd = data.load_slate(pub / "nba", 901)
    assert sd.meta["sims_fingerprint"] == res["meta"]["sims_fingerprint"]
    assert data.sims_mismatch(sd) is False


def test_tampered_fingerprint_flags_mismatch(nba_pub):
    from nbadfs_app import data
    pub, _ = nba_pub
    sd = data.load_slate(pub / "nba", 902)
    sd.meta = {**sd.meta, "sims_fingerprint": "0" * 64}
    assert data.sims_mismatch(sd) is True


def test_mismatch_shows_caption(nba_pub, monkeypatch):
    from nbadfs_app import data, views
    pub, _ = nba_pub
    monkeypatch.setattr(data, "sims_mismatch", lambda sd: True)
    at = _app(monkeypatch, pub, "1")
    assert any(views.SIMS_DIFFER in c.value for c in at.caption)
    monkeypatch.setattr(data, "sims_mismatch", lambda sd: False)
    at = _app(monkeypatch, pub, "1")
    assert not any(views.SIMS_DIFFER in c.value for c in at.caption)


def test_builder_records_nba_slots(nba_pub):
    from nbadfs_app import data, views
    pub, _ = nba_pub
    sd = data.load_slate(pub / "nba", 901)
    recs = views.builder_records(sd.pool, {"median": 1.0})
    r = next(x for x in recs if "/" in x["position"]) if any("/" in x for x in sd.pool.positions) else recs[0]
    row = sd.pool.set_index("dk_id").loc[r["dk_id"]]
    assert r["slots"] == list(row["slots"]) and isinstance(r["slots"], list)
    assert len(recs) == int(sd.pool.playable.sum())


# ── injury tags on the 🏀 page ──────────────────────────────────────────────────────────────────────────

NBA_HEADLINE = "Listed questionable with knee soreness"


@pytest.fixture(scope="module")
def nba_injured(nba_pub, tmp_path_factory):
    """nba_pub with a Q player (news) in each slate's single-entry rank-0 lineup and a Doubtful player outside it;
    pool, backups and meta rewritten so the app regenerates matching sims."""
    import shutil

    from nbadfs import lineups as L
    from nbadfs.simulate import simulate
    from nfldfs.injuries import classify
    src, _ = nba_pub
    pub = tmp_path_factory.mktemp("nba_inj")
    shutil.copytree(src, pub, dirs_exist_ok=True)
    ids = {}
    for s in SLATES[:2]:
        folder = pub / "nba" / str(s["draft_group_id"])
        pool = pd.read_parquet(folder / "pool.parquet")
        lus = pd.read_parquet(folder / "lineups.parquet")
        rec = lus[(lus.contest_key == "single_entry") & (lus["rank"] == 0)]
        q = int(rec.dk_id.iloc[2])
        used = set(lus.dk_id.astype(int))
        d = int(pool[pool.playable & ~pool.dk_id.isin(used)].sort_values("salary").dk_id.iloc[-1])
        published = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=25)).isoformat()
        by = pool.dk_id.astype(int)
        pool.loc[by == q, ["status", "body_part", "news_headline", "news_story", "news_published"]] = [
            "Q", "Knee", NBA_HEADLINE, "Coach said he will test it in warmups.", published]
        pool.loc[by == d, ["status", "playable"]] = ["D", False]
        pool = classify(pool)
        pool.to_parquet(folder / "pool.parquet")
        meta = json.loads((folder / "build_meta.json").read_text())
        meta["built_at_utc"] = "2026-10-23T17:00:00+00:00"            # a fresh cache key for the regenerated sims
        meta.pop("sims_fingerprint", None)
        (folder / "build_meta.json").write_text(json.dumps(meta))
        sims = simulate(pool, int(meta["n_sims"]), int(meta["seed"]))
        field = np.load(folder / "field.npy").astype(np.int64)
        L.rank0_backups(pool, sims, field, lus).to_parquet(folder / "injury_backups.parquet")
        ids[s["draft_group_id"]] = {"q": q, "d": d}
    return pub, ids


def test_nba_recommended_shows_injury_watch_and_apply(monkeypatch, nba_injured):
    from nbadfs_app import data
    pub, ids = nba_injured
    at = _app(monkeypatch, pub, "1")
    assert not at.exception
    dg = at.session_state["nba_dg"]
    q = ids[dg]["q"]
    sd = data.load_slate(pub / "nba", dg)
    q_name = sd.pool.set_index("dk_id").at[q, "name"]
    watch = [e for e in at.expander if e.label == "🩹 Injury watch"]
    assert watch and watch[0].proto.expanded
    text = "\n".join(m.value for m in at.markdown)
    assert NBA_HEADLINE in text and "25 min ago" in text and "Knee" in text and "#f2c94c" in text
    assert f"If **{q_name}** sits:" in text and "→" in text
    assert f'title="🟡 Q · Knee&#10;{NBA_HEADLINE}' in text                  # hover tooltip on the lineup names
    bk = sd.backups[(sd.backups.contest_key == "single_entry") & (sd.backups.tagged_dk_id == q)].iloc[0]
    assert bk["kind"] != "none"
    at.button(key=f"nba_rec_single_entry_backup_{q}").click().run()
    assert not at.exception
    mine = at.session_state["nba_my_ids"]
    assert q not in mine and all(int(i) in mine for i in bk["in_dk_ids"]) and len(mine) == 8


def test_nba_my_lineup_backup_for_user_pick(monkeypatch, nba_injured):
    from nbadfs_app import data, views
    pub, ids = nba_injured
    at = _app(monkeypatch, pub, "1")
    dg = at.session_state["nba_dg"]
    sd = data.load_slate(pub / "nba", dg)
    d = ids[dg]["d"]
    rec = sd.lineups[(sd.lineups.contest_key == "single_entry") & (sd.lineups["rank"] == 0)]
    mine = rec.dk_id.astype(int).tolist()
    d_slots = list(sd.pool.set_index("dk_id").at[d, "slots"])
    slot = next(k for k, s in enumerate(views.ROSTER_SLOTS) if s in d_slots and mine[k] != ids[dg]["q"])
    mine[slot] = d                                                            # Nathan adds a Doubtful player
    d_name = sd.pool.set_index("dk_id").at[d, "name"]
    status = views.lineup_status(mine, sd.pool)
    assert status["valid"]                                                    # his pick wins…
    assert any(m.startswith(f"⚠ {d_name} is listed Doubtful") for m in status["messages"])   # …with a ⚠
    at.session_state["nba_my_ids"] = mine
    at.run()
    assert not at.exception
    assert any(f"{d_name} is listed Doubtful" in e.value for e in at.error)
    assert f"If **{d_name}** sits:" in "\n".join(m.value for m in at.markdown)
    at.button(key=f"nba_mine_backup_{d}").click().run()
    assert not at.exception and d not in at.session_state["nba_my_ids"]
    labels = at.multiselect(key="nba_locks").options
    assert any(o.startswith(f"{d_name} ·") and o.endswith("🟠 D") for o in labels)
    assert not any(o.startswith(f"{d_name} ·") for o in at.multiselect(key="nba_excludes").options)


def test_nba_pool_filter_injured_only(monkeypatch, nba_injured):
    from nbadfs_app import data, views
    pub, ids = nba_injured
    sd = data.load_slate(pub / "nba", 901)
    hurt = views.pool_view(sd.pool, views.POSITIONS, list(ui_tiers()), "Median", injured_only=True)
    assert len(hurt) and (hurt.inj_tag != "").all() and {ids[901]["q"], ids[901]["d"]} <= set(hurt.dk_id)
    shown = views.pool_table(hurt).data
    assert "News" in shown.columns and any(NBA_HEADLINE in n for n in shown["News"])
    assert any("🔴 OUT" in n for n in shown["Player"])                       # the sample's Out players, chipped
    at = _app(monkeypatch, pub, "1")
    at.checkbox(key="nba_pool_injured").check().run()
    assert not at.exception
    assert len(at.dataframe[-1].value) == len(views.pool_view(
        data.load_slate(pub / "nba", at.session_state["nba_dg"]).pool, views.POSITIONS, list(ui_tiers()), "Median",
        injured_only=True))


def ui_tiers():
    from nfldfs_app import ui
    return ui.TIER_ICON


def test_nba_page_loads_without_injury_data(monkeypatch, nba_pub, tmp_path):
    import shutil

    from nbadfs_app import data, views
    from nfldfs_app import ui
    src, _ = nba_pub
    pub = tmp_path / "old"
    shutil.copytree(src, pub)
    for s in SLATES[:2]:
        folder = pub / "nba" / str(s["draft_group_id"])
        (folder / "injury_backups.parquet").unlink(missing_ok=True)
        pool = pd.read_parquet(folder / "pool.parquet")
        pool.drop(columns=[c for c in (*ui.INJURY_COLUMNS, "injury_updated", "espn_id") if c in pool.columns]) \
            .to_parquet(folder / "pool.parquet")
        meta = json.loads((folder / "build_meta.json").read_text())
        meta["built_at_utc"] = "2026-10-23T16:00:00+00:00"
        (folder / "build_meta.json").write_text(json.dumps(meta))
    sd = data.load_slate(pub / "nba", 901)
    assert sd.backups.empty and not ui.has_injury_data(sd.pool)
    at = _app(monkeypatch, pub, "1")
    assert not at.exception
    assert not any(e.label == "🩹 Injury watch" for e in at.expander)
    assert not any(c.key == "nba_pool_injured" for c in at.checkbox)
    out = sd.pool[~sd.pool.playable.astype(bool)].iloc[0]
    assert views.player_label(out).endswith(" · OUT")                       # old builds keep the old label
    assert all(r["inj"] == "" for r in views.builder_records(sd.pool, {"median": 1.0}))
