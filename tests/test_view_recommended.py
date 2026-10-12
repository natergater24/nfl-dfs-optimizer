import pandas as pd

from nfldfs_app import data, scoring, view_recommended


def _lu(rows):
    return pd.DataFrame(rows, columns=["name", "position", "team", "opp"])


def test_stack_summary():
    lu = _lu([("QB A", "QB", "BUF", "LV"), ("WR B", "WR", "BUF", "LV"), ("WR C", "WR", "LV", "BUF"),
              ("RB D", "RB", "KC", "LAC")])
    assert view_recommended.stack_summary(lu) == "Stack: QB A + WR B · bring-back: WR C"
    assert view_recommended.stack_summary(_lu([("QB A", "QB", "BUF", "LV")])) == "No QB stack (QB A alone)"


def test_apply_swap():
    ids, slot = view_recommended.apply_swap([1, 2, 3, 4, 5, 6, 7, 8, 9], 4, 40)
    assert ids == [1, 2, 3, 40, 5, 6, 7, 8, 9] and slot == 3


def test_published_metric_in_range(published_dir):
    from nfldfs.sim_eval import lineup_scores
    d = data.load(published_dir)
    rec = d.lineups[(d.lineups.contest_key == "fifty_fifty") & (d.lineups["rank"] == 0)]
    m = scoring.published_metric(d, rec.dk_id.tolist(), "fifty_fifty", lineup_scores(d.sims, d.field))
    assert 0.0 <= m <= 1.0


def test_recommended_tab_renders_and_apply_copies(make_app, published_dir):
    at = make_app(published_dir)
    at.selectbox(key="contest_label").set_value("50/50").run()
    assert not at.exception
    assert len(at.dataframe) >= 1
    apply = [b for b in at.button if b.key and b.key.startswith("apply_fifty_fifty_")]
    assert apply, "expected at least one outlier swap for 50/50 on the synthetic slate"
    apply[0].click().run()
    assert len(at.session_state["my_ids"]) == 9 and isinstance(at.session_state["focus_slot"], int)
