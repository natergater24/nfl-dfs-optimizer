import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nfldfs import config, injuries

FIX = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 10, 29, 22, 0, tzinfo=dt.timezone.utc)
RECENT = NOW - dt.timedelta(hours=2)


def test_tags_and_classes():
    for raw, tag in [("", ""), (None, ""), (float("nan"), ""), ("q", "Q"), ("P", "P"), ("D", "D"),
                     ("OUT", "OUT"), ("O", "OUT"), ("IR", "IR"), ("GTD", "GTD"), (" Q ", "Q")]:
        assert injuries.normalize_tag(raw) == tag
    assert injuries.tag_class("") == "healthy"
    assert injuries.tag_class("P") == "healthy"
    assert injuries.tag_class("Q") == "questionable"
    assert injuries.tag_class("GTD") == "questionable"
    for t in ("D", "OUT", "IR"):
        assert injuries.tag_class(t) == "excluded"


@pytest.mark.parametrize("text,expected", [
    ("He has been ruled out for Sunday.", "out"),
    ("He will not play this week.", "out"),
    ("He won't play Sunday.", "out"),
    ("Not expected to play against Buffalo.", "out"),
    ("He is unlikely to play.", "out"),
    ("He will miss the game.", "out"),
    ("He is expected to miss two weeks.", "out"),
    ("He is out for the week.", "out"),
    ("He is listed as doubtful.", "out"),
    ("He is doubtful to play.", "out"),
    ("He is expected to play Sunday.", "in"),
    ("He will play.", "in"),
    ("He is on track to play.", "in"),
    ("He has been cleared to play.", "in"),
    ("He was upgraded to questionable... upgraded.", "in"),
    ("He was removed from the injury report.", "in"),
    ("He is probable for Sunday.", "in"),
    ("He has no injury designation.", "in"),
    ("He did not practice Wednesday but is expected to play Sunday.", "in"),
    ("He did not practice Wednesday.", "unclear"),
    ("DNP on Wednesday.", "unclear"),
    ("Limited in practice.", "unclear"),
    ("Full participant Thursday.", "unclear"),
    ("A veteran rest day for him.", "unclear"),
    ("Maintenance day.", "unclear"),
    ("He isn't expected to play Sunday.", "out"),
    ("He is no longer expected to miss time.", "in"),
    ("He is ruled out. Later, he is expected to play.", "in"),
    ("He was expected to play, but is now ruled out.", "out"),
    ("He did not practice, then is ruled out.", "out"),
    ("Nothing relevant here.", "unclear"),
    ("He is ruled out for Sunday, but is expected to play next week.", "out"),
    ("He is out Sunday against the Bills.", "out"),
    ("He is doubtful for Sunday.", "out"),
    ("He was held out of practice Wednesday.", "unclear"),
    ("He is out of practice Wednesday.", "unclear"),
    ("He is expected to play Sunday after missing practice.", "in"),
    ("He will return next week.", "unclear"),
    ("He is expected to play in Week 9.", "unclear"),
])
def test_lean_rules(text, expected):
    assert injuries.lean(text, RECENT, NOW) == expected


def test_lean_none_cases():
    assert injuries.lean(None, RECENT, NOW) is None
    assert injuries.lean("", RECENT, NOW) is None
    assert injuries.lean("ruled out", NOW - dt.timedelta(hours=73), NOW) is None
    assert injuries.lean("ruled out", NOW - dt.timedelta(hours=71), NOW) == "out"
    assert injuries.lean("ruled out", None, NOW) is None


def test_lean_real_lamar_blurb():
    o = json.loads((FIX / "espn_overview_sample.json").read_text())["nfl"]["rotowire"]
    assert injuries.lean(o["headline"] + " " + o["story"], RECENT, NOW) == "in"


def test_parse_published():
    p = injuries.parse_published
    assert p("Thu Oct 29 13:55:49 PDT 2026") == dt.datetime(2026, 10, 29, 20, 55, 49, tzinfo=dt.timezone.utc)
    assert p("Thu Dec 10 13:00:00 PST 2026") == dt.datetime(2026, 12, 10, 21, 0, tzinfo=dt.timezone.utc)
    assert p("Thu Oct 29 13:00:00 EDT 2026") == dt.datetime(2026, 10, 29, 17, 0, tzinfo=dt.timezone.utc)
    assert p("Thu Dec 10 13:00:00 EST 2026") == dt.datetime(2026, 12, 10, 18, 0, tzinfo=dt.timezone.utc)
    assert p("2026-10-29T20:55:49+00:00") == dt.datetime(2026, 10, 29, 20, 55, 49, tzinfo=dt.timezone.utc)
    assert p("garbage") is None
    assert p(None) is None


def _sleeper(*rows):
    return {str(i): {"full_name": n, "team": t, "position": "WR", "injury_status": "Questionable",
                     "injury_body_part": "Knee", "news_updated": 1793318105543, "espn_id": e, "active": True}
            for i, (n, t, e) in enumerate(rows)}


def test_sleeper_match_aliases():
    sl = _sleeper(("Marvin Harrison Jr.", "ARI", "1"), ("Luka Dončić", "DAL", "2"),
                  ("Trevor Lawrence", "JAX", "3"), ("Cooper Kupp", "LA", "4"),
                  ("Devin Booker", "PHX", "5"), ("Terry McLaurin", "WSH", "6"),
                  ("Zion Williamson", "NO", "7"), ("Stephen Curry", "GS", "8"),
                  ("Victor Wembanyama", "SA", "9"), ("Jalen Brunson", "NY", "10"),
                  ("Lauri Markkanen", "UTAH", "11"), ("Mystery Man", "CHI", "12"))
    pool = pd.DataFrame({
        "name": ["Marvin Harrison", "Luka Doncic", "Trevor Lawrence", "Cooper Kupp", "Devin Booker",
                 "Terry McLaurin", "Zion Williamson", "Stephen Curry", "Victor Wembanyama", "Jalen Brunson",
                 "Lauri Markkanen", "Mystery Man", "Nobody Here"],
        "team": ["ARI", "DAL", "JAC", "LAR", "PHO", "WAS", "NOP", "GSW", "SAS", "NYK", "UTA", "MIA", "MIA"]})
    out = injuries.attach_sleeper(pool, sl, "nba")
    assert list(out["espn_id"][:11]) == [str(i) for i in range(1, 12)]
    assert out["body_part"][0] == "Knee"
    assert out["injury_updated"][0].startswith("2026-")  # UTC ISO
    assert out["injury_updated"][0].endswith("+00:00")
    # name-only fallback when the name is unique even though the team differs
    assert out["espn_id"][11] == "12"
    # no match -> tag kept, extras blank
    assert out["espn_id"][12] == "" and out["body_part"][12] == "" and out["injury_updated"][12] == ""


def test_sleeper_ambiguous_name_not_guessed():
    sl = _sleeper(("Josh Allen", "BUF", "1"), ("Josh Allen", "JAX", "2"))
    pool = pd.DataFrame({"name": ["Josh Allen"], "team": ["NYJ"]})
    assert injuries.attach_sleeper(pool, sl, "nfl")["espn_id"][0] == ""
    pool = pd.DataFrame({"name": ["Josh Allen"], "team": ["JAC"]})
    assert injuries.attach_sleeper(pool, sl, "nfl")["espn_id"][0] == "2"


def test_sleeper_fixtures_match_real_players():
    for sport in ("nfl", "nba"):
        sl = json.loads((FIX / f"sleeper_{sport}_sample.json").read_text())
        rows = list(sl.values())
        pool = pd.DataFrame({"name": [r["full_name"] for r in rows], "team": [r["team"] for r in rows]})
        out = injuries.attach_sleeper(pool, sl, sport)
        assert (out["body_part"] != "").sum() > 5


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, sleeper=None, espn=None, sleeper_exc=None, espn_exc=None):
        self.sleeper, self.espn = sleeper or {}, espn or {}
        self.sleeper_exc, self.espn_exc = sleeper_exc, espn_exc
        self.calls = []

    def get(self, url, timeout=None, **kw):
        self.calls.append(url)
        assert timeout == 10
        if "sleeper" in url:
            if self.sleeper_exc:
                raise self.sleeper_exc
            return Resp(self.sleeper)
        if self.espn_exc:
            raise self.espn_exc
        eid = url.split("/athletes/")[1].split("/")[0]
        if eid not in self.espn:
            return Resp({}, 404)
        return Resp(self.espn[eid])


def blurb(text, published="Thu Oct 29 13:55:49 PDT 2026"):
    return {"rotowire": {"headline": text, "story": "", "description": text, "published": published}}


def test_fetch_urls_and_news():
    s = FakeSession(sleeper={"1": {}}, espn={"7": blurb("Jones will play.")})
    assert injuries.fetch_sleeper("nba", s) == {"1": {}}
    assert s.calls[0] == "https://api.sleeper.app/v1/players/nba"
    n = injuries.fetch_news("7", "nfl", s)
    assert s.calls[1] == ("https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/7/overview")
    assert n == {"headline": "Jones will play.", "story": "", "published": "2026-10-29T20:55:49+00:00"}
    injuries.fetch_news("7", "nba", s)
    assert "basketball/nba/athletes/7" in s.calls[-1]
    assert injuries.fetch_news("999", "nfl", s) is None  # 404 -> no news
    s2 = FakeSession(espn={"8": {"nothing": 1}})
    assert injuries.fetch_news("8", "nfl", s2) is None


def _pool():
    return pd.DataFrame({
        "dk_id": [1, 2, 3, 4, 5],
        "name": ["Healthy Guy", "Out Guy", "Unclear Guy", "Probable Guy", "Dead Guy"],
        "team": ["AAA"] * 5,
        "status": ["", "Q", "Q", "P", "IR"],
        "playable": [True, True, True, True, False],
    })


def _fake_sources():
    sl = _sleeper(("Healthy Guy", "AAA", "10"), ("Out Guy", "AAA", "20"), ("Unclear Guy", "AAA", "30"),
                  ("Probable Guy", "AAA", "40"), ("Dead Guy", "AAA", "50"))
    espn = {"10": blurb("Healthy will play."), "20": blurb("Out Guy has been ruled out for Sunday."),
            "30": blurb("Unclear Guy did not practice Wednesday."), "40": blurb("Probable Guy is probable."),
            "50": blurb("Dead Guy is on IR.")}
    return FakeSession(sleeper=sl, espn=espn)


def test_add_injury_columns():
    s = _fake_sources()
    naps = []
    pool, warn = injuries.add_injury_columns(_pool(), "nfl", now=NOW.replace(hour=21), session=s,
                                             sleep=naps.append)
    assert warn == ""
    p = pool.set_index("dk_id")
    assert list(p["inj_tag"]) == ["", "Q", "Q", "P", "IR"]
    assert list(p["inj_class"]) == ["healthy", "questionable", "questionable", "healthy", "excluded"]
    assert p.loc[2, "lean"] == "out" and not p.loc[2, "recommendable"] and p.loc[2, "play_prob"] == 0
    assert p.loc[3, "lean"] == "unclear" and p.loc[3, "recommendable"] and p.loc[3, "play_prob"] == config.Q_PLAY_PROB
    assert p.loc[1, "play_prob"] == 1.0 and p.loc[1, "recommendable"]
    assert p.loc[4, "play_prob"] == 1.0
    assert not p.loc[5, "recommendable"] and p.loc[5, "play_prob"] == 0
    assert p.loc[2, "news_headline"].startswith("Out Guy") and p.loc[2, "news_published"].endswith("+00:00")
    assert p.loc[2, "body_part"] == "Knee"
    # healthy player with no news requested stays blank, no ESPN call for him
    assert p.loc[1, "news_headline"] == "" and p.loc[1, "lean"] == ""
    assert sum("athletes/10/" in c for c in s.calls) == 0
    assert len(naps) == 3 and all(n == config.NEWS_DELAY_S for n in naps)  # 4 tagged players -> 3 pauses
    assert pool["recommendable"].dtype == bool
    assert list(injuries.recommendable(pool)) == [True, False, True, True, False]


def test_news_for_fetches_extra_healthy_player():
    s = _fake_sources()
    pool, _ = injuries.add_injury_columns(_pool(), "nfl", now=NOW.replace(hour=21), session=s,
                                          news_for={1}, sleep=lambda _: None)
    p = pool.set_index("dk_id")
    assert p.loc[1, "news_headline"] == "Healthy will play."
    assert p.loc[1, "lean"] == "" and p.loc[1, "recommendable"]  # lean only read for questionable


def test_old_news_gives_no_lean():
    s = _fake_sources()
    pool, _ = injuries.add_injury_columns(_pool(), "nfl", now=NOW + dt.timedelta(days=5), session=s,
                                          sleep=lambda _: None)
    p = pool.set_index("dk_id")
    assert p.loc[2, "lean"] == "" and p.loc[2, "recommendable"] and p.loc[2, "play_prob"] == config.Q_PLAY_PROB


def test_nba_o_becomes_out():
    pool = pd.DataFrame({"dk_id": [1, 2], "name": ["A B", "C D"], "team": ["X", "X"],
                         "status": ["O", "GTD"], "playable": [False, True]})
    out, _ = injuries.add_injury_columns(pool, "nba", now=NOW, session=FakeSession(), sleep=lambda _: None)
    assert list(out["inj_tag"]) == ["OUT", "GTD"]
    assert list(out["recommendable"]) == [False, True]


@pytest.mark.parametrize("which", ["sleeper", "espn", "both"])
def test_sources_down_keep_tags(which):
    base = _fake_sources()
    s = FakeSession(
        sleeper=base.sleeper, espn=base.espn,
        sleeper_exc=ConnectionError("boom") if which in ("sleeper", "both") else None,
        espn_exc=TimeoutError("slow") if which in ("espn", "both") else None)
    pool, warn = injuries.add_injury_columns(_pool(), "nfl", now=NOW, session=s, sleep=lambda _: None)
    assert warn.startswith("; WARNING: injury news unavailable (")
    assert list(pool["inj_tag"]) == ["", "Q", "Q", "P", "IR"]
    assert list(pool["inj_class"]) == ["healthy", "questionable", "questionable", "healthy", "excluded"]
    for col in ("news_headline", "news_story", "news_published", "lean"):
        assert (pool[col] == "").all()
    assert list(pool["recommendable"]) == [True, True, True, True, False]
    assert list(pool["play_prob"]) == [1.0, config.Q_PLAY_PROB, config.Q_PLAY_PROB, 1.0, 0.0]


def test_sources_change_shape_never_raise():
    s = FakeSession(sleeper=["not", "a", "dict"], espn={})
    pool, warn = injuries.add_injury_columns(_pool(), "nfl", now=NOW, session=s, sleep=lambda _: None)
    assert "WARNING" in warn and list(pool["inj_tag"])[1] == "Q"
    s = FakeSession(sleeper={"1": "junk"}, espn={})
    pool, warn = injuries.add_injury_columns(_pool(), "nfl", now=NOW, session=s, sleep=lambda _: None)
    assert list(pool["inj_tag"])[1] == "Q"


def test_recommendable_falls_back_to_playable():
    df = pd.DataFrame({"playable": [True, False]})
    assert list(injuries.recommendable(df)) == [True, False]
    assert isinstance(injuries.recommendable(df), np.ndarray)
