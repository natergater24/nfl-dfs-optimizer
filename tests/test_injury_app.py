"""App side of the injury tags: chips, news tooltips, 🩹 Injury watch with backups, the injured-only filter,
and old builds (no injury columns / files) still loading. NFL here; the 🏀 page's tests are in tests/nba/test_app.py."""
import datetime as dt
import shutil

import numpy as np
import pandas as pd
import pytest

from nfldfs import build, injuries
from nfldfs_app import data, ui, view_builder, view_pool

NOW = dt.datetime(2026, 10, 29, 18, 0, tzinfo=dt.timezone.utc)
HEADLINE = "Questionable with an ankle injury"


def _published_news(hours_ago: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()


@pytest.fixture(scope="module")
def injured_pub(published_dir, tmp_path_factory):
    """The synthetic build with injury columns: a Q player (with news) in the default contest's rank-0 lineup,
    a Doubtful RB and an OUT WR outside it; injury_backups.parquet rebuilt for those tags."""
    pub = tmp_path_factory.mktemp("injpub")
    shutil.copytree(published_dir, pub, dirs_exist_ok=True)
    pool = pd.read_parquet(pub / "player_pool.parquet")
    lus = pd.read_parquet(pub / "lineups.parquet")
    rec = lus[(lus.contest_key == "single_entry") & (lus["rank"] == 0)]
    q_id = int(rec[rec.slot == "WR"].dk_id.iloc[0])
    used = set(lus.dk_id.astype(int))
    d_id = int(pool[(pool.position == "RB") & ~pool.dk_id.isin(used)].sort_values("salary").dk_id.iloc[-1])
    out_id = int(pool[(pool.position == "WR") & ~pool.dk_id.isin(used | {q_id})].dk_id.iloc[0])
    for col in ("lean", "body_part", "news_headline", "news_story", "news_published"):
        pool[col] = ""
    by = pool.dk_id.astype(int)
    pool.loc[by == q_id, ["status", "body_part", "news_headline", "news_story", "news_published"]] = [
        "Q", "Ankle", HEADLINE, "He was limited Thursday and is a game-time call.", _published_news(2)]
    pool.loc[by == d_id, ["status", "playable", "body_part"]] = ["D", False, "Hamstring"]
    pool.loc[by == out_id, ["status", "playable", "news_headline", "news_published"]] = [
        "O", False, "Ruled out for Sunday", _published_news(30)]
    pool = injuries.classify(pool)
    pool.to_parquet(pub / "player_pool.parquet")
    sims = np.load(pub / "sims.npy").astype(np.float32)
    field = np.load(pub / "field.npy").astype(np.int64)
    build.rank0_backups(pool, sims, field, lus).to_parquet(pub / "injury_backups.parquet")
    return pub, {"q": q_id, "d": d_id, "out": out_id}


# ── shared helpers ───────────────────────────────────────────────────────────────────────────────────────

def test_injury_chip_colors():
    assert ui.injury_chip("") == "" and ui.injury_chip(None) == "" and ui.injury_chip(float("nan")) == ""
    for tag in ("Q", "GTD"):
        assert "#f2c94c" in ui.injury_chip(tag) and f">{tag}<" in ui.injury_chip(tag)          # yellow
    assert "#f2994a" in ui.injury_chip("D")                                                    # orange
    assert "#eb5757" in ui.injury_chip("OUT") and "#eb5757" in ui.injury_chip("IR")            # red
    assert "#9e9e9e" in ui.injury_chip("P")                                                    # gray
    assert "📰 leans out" in ui.injury_chip("Q", "out") and "📰 leans in" in ui.injury_chip("GTD", "in")
    assert "leans" not in ui.injury_chip("Q", "unclear") and "leans" not in ui.injury_chip("OUT", "out")
    assert ui.chip_text("Q", "out") == "🟡 Q · 📰 leans out" and ui.chip_text("IR") == "🔴 IR"
    assert ui.chip_text("D") == "🟠 D" and ui.chip_text("P") == "⚪ P" and ui.chip_text("") == ""


def test_news_age():
    ago = lambda **kw: (NOW - dt.timedelta(**kw)).isoformat()            # noqa: E731
    assert ui.news_age(ago(seconds=20), NOW) == "just now"
    assert ui.news_age(ago(minutes=7), NOW) == "7 min ago"
    assert ui.news_age(ago(hours=2, minutes=50), NOW) == "2 h ago"
    assert ui.news_age(ago(days=3, hours=1), NOW) == "3 d ago"
    assert ui.news_age("", NOW) == "" and ui.news_age("garbage", NOW) == ""


def test_lineup_news_tooltip(injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    rec = d.lineups[(d.lineups.contest_key == "single_entry") & (d.lineups["rank"] == 0)]
    row = rec[rec.dk_id == ids["q"]].iloc[0]
    tip = ui.news_tooltip(row)
    assert HEADLINE in tip and "2 h ago" in tip and "game-time call" in tip and "🟡 Q · Ankle" in tip
    html = ui.hover_names_html(rec)
    assert f'title="🟡 Q · Ankle&#10;{HEADLINE} (2 h ago)&#10;' in html and "\n" not in html
    assert f">{row['name']}</span>" in html
    tag_only = ui.news_tooltip(pd.Series({"inj_tag": "D", "body_part": "Hamstring", "news_headline": ""}))
    assert tag_only == "🟠 D · Hamstring"                                 # no news: the tag only
    assert ui.news_tooltip(pd.Series({"inj_tag": "", "news_headline": ""})) == ""


def test_backup_line_and_apply():
    names = {1: "Al", 2: "Bo", 3: "Cy", 4: "Di"}
    one = {"tagged_dk_id": 1, "kind": "1:1", "out_dk_ids": np.array([1]), "in_dk_ids": np.array([3]),
           "remaining_salary": 1200, "metric_before": 0.31, "metric_after": 0.29, "message": "x"}
    assert ui.backup_line(one, names) == "If **Al** sits: **Cy** — \\$1,200 left, 31% → 29%"
    two = {**one, "kind": "two-player", "out_dk_ids": [1, 2], "in_dk_ids": [3, 4]}
    assert "**Cy**, **Di** (also moves out Bo)" in ui.backup_line(two, names)
    none = {**one, "kind": "none", "in_dk_ids": [], "message": "No healthy replacement fits under the cap."}
    assert ui.backup_line(none, names) == "If **Al** sits: No healthy replacement fits under the cap."
    assert ui.apply_backup([5, 1, 2], [1], [3]) == ([5, 3, 2], 1)
    assert ui.apply_backup([5, 1, 2], [1, 2], [3, 4]) == ([5, 3, 4], 1)


def test_pick_backups_published_or_device():
    pub = pd.DataFrame({"contest_key": ["se", "se"], "tagged_dk_id": [1, 2], "kind": ["1:1", "1:1"]})
    calls = []
    device = lambda: calls.append(1) or pd.DataFrame({"tagged_dk_id": [9]})     # noqa: E731
    assert ui.pick_backups(pub, "se", [1], device)["tagged_dk_id"].tolist() == [1] and not calls
    assert ui.pick_backups(pub, "se", [1, 7], device)["tagged_dk_id"].tolist() == [9] and calls
    assert ui.pick_backups(pd.DataFrame(), "se", [1], device)["tagged_dk_id"].tolist() == [9]


# ── 🏈 page ───────────────────────────────────────────────────────────────────────────────────────────────

def _md(at) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_recommended_shows_injury_watch_and_apply(make_app, injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    q_name = d.pool.set_index("dk_id").at[ids["q"], "name"]
    at = make_app(pub)
    assert not at.exception
    watch = [e for e in at.expander if e.label == "🩹 Injury watch"]
    assert watch and watch[0].proto.expanded                                 # open: a tagged player is in it
    text = _md(at)
    assert HEADLINE in text and "2 h ago" in text and "Ankle" in text and "#f2c94c" in text
    assert f"If **{q_name}** sits:" in text and "left," in text and "→" in text
    assert f'title="🟡 Q · Ankle' in text                                    # hover tooltip on the lineup names
    bk = d.backups[(d.backups.contest_key == "single_entry") & (d.backups.tagged_dk_id == ids["q"])].iloc[0]
    at.button(key=f"rec_single_entry_backup_{ids['q']}").click().run()
    assert not at.exception
    mine = at.session_state["my_ids"]
    assert ids["q"] not in mine and int(bk["in_dk_ids"][0]) in mine and len(mine) == 9
    assert all(int(i) in mine for i in bk["in_dk_ids"])                       # a two-player rework swaps both
    assert isinstance(at.session_state["focus_slot"], int)


def test_recommended_uses_device_backups_when_not_published(make_app, injured_pub, tmp_path):
    src, ids = injured_pub
    pub = tmp_path / "pub"
    shutil.copytree(src, pub)
    (pub / "injury_backups.parquet").unlink()
    at = make_app(pub)
    assert not at.exception
    assert "sits:" in _md(at)
    assert any(b.key == f"rec_single_entry_backup_{ids['q']}" for b in at.button)


def test_my_lineup_backup_for_user_pick(make_app, injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    rec = d.lineups[(d.lineups.contest_key == "single_entry") & (d.lineups["rank"] == 0)]
    mine = rec.dk_id.astype(int).tolist()
    rb_slot = rec.slot.tolist().index("RB")
    mine[rb_slot] = ids["d"]                                                   # Nathan adds a Doubtful RB
    d_name = d.pool.set_index("dk_id").at[ids["d"], "name"]
    status = view_builder.lineup_status(mine, d.pool)
    assert status["valid"]                                                     # his pick wins…
    assert any(m.startswith(f"⚠ {d_name} is listed Doubtful") for m in status["messages"])   # …with a ⚠
    at = make_app(pub)
    at.session_state["my_ids"] = mine
    at.run()
    assert not at.exception
    assert any(f"{d_name} is listed Doubtful" in e.value for e in at.error)     # st.error shows ⚠ as its icon
    assert f"If **{d_name}** sits:" in _md(at)
    at.button(key=f"mine_backup_{ids['d']}").click().run()
    assert not at.exception and ids["d"] not in at.session_state["my_ids"]


def test_tweak_lock_any_player_with_warning(make_app, injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    opts = view_pool.lock_options(d.pool)
    assert ids["out"] in opts.values() and ids["d"] in opts.values()            # every player can be locked
    d_label = next(k for k, v in opts.items() if v == ids["d"])
    assert d_label.endswith("· 🟠 D")
    at = make_app(pub)
    excl = at.multiselect(key="pool_excludes").options
    assert not any(o.endswith("🟠 D") or o.endswith("🔴 OUT") for o in excl)  # exclude list: playable only
    at.multiselect(key="pool_locks").select(d_label).run()
    at.button(key="pool_rebuild").click().run()
    assert not at.exception
    assert ids["d"] in at.session_state["rebuilt"]["ids"]
    assert any("is listed Doubtful" in w.value for w in at.warning)
    assert any(b.key == f"rebuilt_backup_{ids['d']}" for b in at.button)


def test_pool_filter_injured_only(make_app, injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    pos, tiers = view_pool.POSITIONS, list(ui.TIER_ICON)
    hurt = view_pool.pool_view(d.pool, pos, tiers, "Median", injured_only=True)
    assert set(hurt.dk_id.astype(int)) == {ids["q"], ids["d"], ids["out"]}
    assert ids["out"] not in set(view_pool.pool_view(d.pool, pos, tiers, "Median").dk_id)
    shown = ui.styled_pool(hurt).data
    assert "News" in shown.columns and any("Ruled out for Sunday (" in n for n in shown["News"])
    at = make_app(pub)
    at.checkbox(key="pool_injured").check().run()
    assert not at.exception
    assert len(at.dataframe[-1].value) == 3


def test_builder_cards_carry_tags(injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    recs = {r["dk_id"]: r for r in view_builder.builder_records(d.pool, {"median": 1.0}, [ids["d"]])}
    assert recs[ids["q"]]["inj"] == "🟡 Q" and recs[ids["q"]]["inj_color"] == "#f2c94c"
    assert HEADLINE in recs[ids["q"]]["inj_title"]
    assert recs[ids["d"]]["inj"] == "🟠 D" and recs[ids["d"]]["out"] is True
    healthy = next(r for r in recs.values() if r["dk_id"] not in ids.values())
    assert healthy["inj"] == "" and healthy["inj_title"] == ""
    from nfldfs_app import builder_component as bc
    assert "p.inj_color" in bc.JS and "p.inj_title" in bc.JS


def test_pages_load_without_injury_data(make_app, published_dir, tmp_path):
    """Builds made before the injury feature: no injury columns, no injury_backups.parquet."""
    pub = tmp_path / "old"
    shutil.copytree(published_dir, pub)
    (pub / "injury_backups.parquet").unlink(missing_ok=True)
    pool = pd.read_parquet(pub / "player_pool.parquet")
    pool = pool.drop(columns=[c for c in ui.INJURY_COLUMNS if c in pool.columns])
    pool.to_parquet(pub / "player_pool.parquet")
    d = data.load(pub)
    assert d.backups.empty and not ui.has_injury_data(d.pool)
    at = make_app(pub)
    assert not at.exception
    assert not any(e.label == "🩹 Injury watch" for e in at.expander)
    assert not any("pool_injured" == c.key for c in at.checkbox)
    assert "Hover a name" not in _md(at)
    recs = view_builder.builder_records(d.pool, {"median": 1.0})
    assert all(r["inj"] == "" for r in recs)


# ── fix round 1 ──────────────────────────────────────────────────────────────────────────────────────────

def _copy_with(src, tmp_path, name, edit):
    pub = tmp_path / name
    shutil.copytree(src, pub)
    pool = edit(pd.read_parquet(pub / "player_pool.parquet"))
    pool = injuries.classify(pool)
    pool.to_parquet(pub / "player_pool.parquet")
    lus = pd.read_parquet(pub / "lineups.parquet")
    sims = np.load(pub / "sims.npy").astype(np.float32)
    build.rank0_backups(pool, sims, np.load(pub / "field.npy").astype(np.int64), lus) \
        .to_parquet(pub / "injury_backups.parquet")
    return pub, lus


def test_probable_player_uses_published_backups(make_app, injured_pub, tmp_path, monkeypatch):
    """P is healthy: the engine publishes no backup for him, so the app must not recompute on the device or say
    "No backup computed"; P alone does not open the expander, but his news still shows."""
    src, ids = injured_pub
    rec = pd.read_parquet(src / "lineups.parquet").query("contest_key == 'single_entry' and rank == 0")
    p_id = int(rec[rec.dk_id != ids["q"]].dk_id.iloc[0])

    def tag_p(pool):
        pool.loc[pool.dk_id == p_id, ["status", "news_headline"]] = ["P", "Probable, expected to play"]
        return pool
    pub, _ = _copy_with(src, tmp_path, "withp", tag_p)
    from nfldfs_app import view_recommended

    def no_device(*a, **k):
        raise AssertionError("published backups should cover the rank-0 lineup")
    monkeypatch.setattr(view_recommended, "device_backups", no_device)
    at = make_app(pub)
    assert not at.exception
    assert not any("No backup computed" in c.value for c in at.caption)
    text = _md(at)
    assert "Probable, expected to play" in text and f"_backup_{p_id}" not in " ".join(b.key or "" for b in at.button)
    assert ui.tagged_ids(data.load(pub).pool, rec.dk_id) == [ids["q"]]

    def only_p(pool):                                                         # Q player healthy again: only P
        pool = tag_p(pool)
        pool.loc[pool.dk_id == ids["q"], "status"] = ""
        return pool
    pub2, _ = _copy_with(src, tmp_path, "onlyp", only_p)
    at = make_app(pub2)
    watch = [e for e in at.expander if e.label == "🩹 Injury watch"]
    assert watch and not watch[0].proto.expanded and "Probable, expected to play" in _md(at)


HOSTILE = {"name": 'Ja<b>"X"</b> *Star*', "inj_tag": "Q", "lean": "", "body_part": "Knee_[x](y)",
           "news_headline": '<script>alert(1)</script> paid $5 to win $10 *now* [x](http://e.vil)',
           "news_story": "Line one\n\nLine `two` with \\ and $3 _under_", "news_published": ""}


def test_feed_text_is_escaped():
    blurb = ui.watch_blurb(pd.Series(HOSTILE))
    hover = ui.hover_names_html(pd.DataFrame([HOSTILE]))
    for out in (blurb, hover):
        assert "<script>" not in out and "<b>" not in out and "&lt;script&gt;" in out
        for raw in ("$5", "$10", "*now*", "[x](", "*Star*", "`two`", "_under_"):
            assert raw not in out, raw
        assert "&#36;5" in out and "&#42;now&#42;" in out and "&#91;x&#93;" in out
    assert "\n" not in hover and "\n\n" not in blurb
    line = ui.backup_line({"tagged_dk_id": 1, "kind": "1:1", "out_dk_ids": [1], "in_dk_ids": [2],
                           "remaining_salary": 0, "metric_before": 0.1, "metric_after": 0.1, "message": ""},
                          {1: "A*b*", 2: "C_d_"})
    assert "*b*" not in line and "_d_" not in line


def test_non_injury_unplayable_still_blocks_export(injured_pub):
    pub, ids = injured_pub
    d = data.load(pub)
    rec = d.lineups[(d.lineups.contest_key == "single_entry") & (d.lineups["rank"] == 0)]
    mine = rec.dk_id.astype(int).tolist()
    pool = d.pool.copy()
    other = next(i for i in mine if i != ids["q"])
    pool.loc[pool.dk_id == other, "playable"] = False                          # unplayable, but not injured
    st_ = view_builder.lineup_status(mine, pool)
    assert not st_["valid"] and any("ruled out" in m for m in st_["messages"])
