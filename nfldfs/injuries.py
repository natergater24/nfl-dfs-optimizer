"""Shared injury core: DraftKings tags, Sleeper/ESPN extras, and a game-level reading of the news.

Tags come from DraftKings' Status column (the source of truth). Sleeper adds body part, update time
and the ESPN id; ESPN's overview endpoint adds the latest Rotowire blurb. Only game-level statements in
a blurb decide a "lean" - practice notes alone never make a player "out". Every source failure leaves
the tags in place and is reported as a warning; nothing here may fail a build.
"""
from __future__ import annotations

import datetime as dt
import re
import time

import numpy as np
import pandas as pd

from . import config
from .teams import normalize_name

SLEEPER_URL = "https://api.sleeper.app/v1/players/{sport}"
ESPN_URL = "https://site.web.api.espn.com/apis/common/v3/sports/{path}/athletes/{espn_id}/overview"
ESPN_PATH = {"nfl": "football/nfl", "nba": "basketball/nba"}
TIMEOUT_S = 10

# ---------------------------------------------------------------- tags

_TAG_ALIASES = {"O": "OUT", "DTD": "GTD"}
_HEALTHY = {"", "P"}
_QUESTIONABLE = {"Q", "GTD"}


def normalize_tag(status) -> str:
    if status is None or (isinstance(status, float) and np.isnan(status)):
        return ""
    t = str(status).strip().upper()
    if t in ("NAN", "NONE"):
        return ""
    return _TAG_ALIASES.get(t, t)


def tag_class(tag) -> str:
    t = normalize_tag(tag)
    if t in _HEALTHY:
        return "healthy"
    if t in _QUESTIONABLE:
        return "questionable"
    return "excluded"  # D, OUT, IR, and anything unfamiliar (suspended, etc.): never suggested


# ---------------------------------------------------------------- reading the news

_OUT = ["ruled out", "will not play", "won't play", "not expected to play", "unlikely to play",
        "will miss", "expected to miss", "out for", "listed as doubtful", "doubtful to play",
        "is out", "is doubtful", "doubtful for"]
_IN = ["expected to play", "will play", "on track to play", "on track to return to action",
       "cleared to play", "upgraded", "removed from the injury report", "probable",
       "no injury designation"]
# Practice-only notes ("did not practice", "dnp", "limited", "full participant", "full practice",
# "rest day", "veteran rest", "maintenance") are deliberately not matched: they are neutral.

_PHRASES = [(p, "out") for p in _OUT] + [(p, "in") for p in _IN]
_RAW = {"is out": r"is\s+out(?!\s+of\s+practice)"}  # "out of practice" is practice-only
_PHRASE_RE = re.compile("|".join(r"(?P<p%d>%s)" % (i, _RAW.get(p) or re.escape(p).replace(r"\ ", r"\s+"))
                                 for i, (p, _) in enumerate(_PHRASES)))
# A game-in phrase that points at a later game ("expected to play next week") does not count.
_FUTURE = re.compile(r"next\s+(week|game|sunday|monday|thursday|matchup)|later\s+this\s+season"
                     r"|week\s+\d+(?!\s+(prep|practice|preparation))|after\s+the\s+bye|return\s+next")
_CLAUSE_END = re.compile(r"[.;]|\bbut\b")
_TOKEN = re.compile(r"[\w']+|[,.;:!?()\-]")
_NEGATORS = {"not", "isn't", "aren't", "wasn't", "weren't", "never", "cannot"}
_BREAKERS = {",", ".", ";", ":", "!", "?", "(", ")", "-", "but", "and", "however", "although", "while",
             "though", "then"}


def _negated(before: str) -> bool:
    """A negator within the 3 words just before a phrase (stopping at clause breaks)."""
    toks = _TOKEN.findall(before)
    words = 0
    for i in range(len(toks) - 1, -1, -1):
        t = toks[i]
        if t in _BREAKERS:
            return False
        words += 1
        if t in _NEGATORS or t.endswith("n't"):
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if t == "not" and nxt in ("practice", "practicing", "participate", "participating"):
                return False
            return True
        if t == "longer" and i > 0 and toks[i - 1] == "no":
            return True
        if words >= 3:
            return False
    return False


def lean(text, published, now) -> str | None:
    """"out" / "in" / "unclear" from the game-level statements in a blurb; None if no text or stale."""
    if not text or not str(text).strip() or published is None:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    if now - published > dt.timedelta(hours=config.NEWS_MAX_AGE_H):
        return None
    s = str(text).lower().replace("’", "'")
    last_pos, last = -1, "unclear"
    for m in _PHRASE_RE.finditer(s):
        idx = int(m.lastgroup[1:])
        kind = _PHRASES[idx][1]
        if kind == "in":
            rest = s[m.end():]
            end = _CLAUSE_END.search(rest)
            if _FUTURE.search(rest[:end.start()] if end else rest):
                continue
        # phrases that carry their own negation ("will not play") are never flipped again
        if not re.search(r"\b(not|won't)\b", m.group(0)) and _negated(s[:m.start()]):
            kind = "in" if kind == "out" else "out"
        if m.start() >= last_pos:
            last_pos, last = m.start(), kind
    return last


_TZ_HOURS = {"UTC": 0, "GMT": 0, "Z": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
             "MST": -7, "MDT": -6, "PST": -8, "PDT": -7}


def parse_published(value) -> dt.datetime | None:
    """ESPN's "Thu Oct 29 13:55:49 PDT 2026" (or an ISO string) -> aware UTC datetime, or None."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    parts = v.split()
    if len(parts) == 6 and parts[4].upper() in _TZ_HOURS:
        try:
            naive = dt.datetime.strptime(" ".join(parts[:4] + parts[5:]), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return None
        return (naive - dt.timedelta(hours=_TZ_HOURS[parts[4].upper()])).replace(tzinfo=dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=dt.timezone.utc) if d.tzinfo is None else d.astimezone(dt.timezone.utc)


# ---------------------------------------------------------------- sources

_TEAM_GROUPS = [("JAX", "JAC"), ("LAR", "LA"), ("PHX", "PHO"), ("WAS", "WSH"), ("NOP", "NO"),
                ("GSW", "GS"), ("SAS", "SA"), ("NYK", "NY"), ("UTA", "UTAH")]
_TEAM_CANON = {alt: grp[0] for grp in _TEAM_GROUPS for alt in grp}


def _canon_team(team) -> str:
    t = "" if team is None or (isinstance(team, float) and np.isnan(team)) else str(team).strip().upper()
    return _TEAM_CANON.get(t, t)


def _get_json(url, session):
    if session is None:
        import requests
        session = requests.Session()
    resp = session.get(url, timeout=TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


def fetch_sleeper(sport, session=None) -> dict:
    data = _get_json(SLEEPER_URL.format(sport=sport), session)
    if not isinstance(data, dict):
        raise ValueError("unexpected Sleeper response shape")
    return data


def _iso(ms) -> str:
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000, tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def attach_sleeper(pool, sleeper, sport) -> pd.DataFrame:
    """Add body_part, injury_updated (UTC ISO or ""), espn_id ("" if unknown) to the pool."""
    by_key: dict[tuple, dict] = {}
    by_name: dict[str, list[dict]] = {}
    for rec in (sleeper or {}).values():
        if not isinstance(rec, dict) or not rec.get("full_name"):
            continue
        name = normalize_name(rec["full_name"])
        key = (name, _canon_team(rec.get("team")))
        old = by_key.get(key)
        if old is None or (rec.get("news_updated") or 0) > (old.get("news_updated") or 0):
            by_key[key] = rec
        by_name.setdefault(name, []).append(rec)

    body, upd, espn = [], [], []
    for name, team in zip(pool["name"], pool["team"]):
        n = normalize_name(name)
        rec = by_key.get((n, _canon_team(team)))
        if rec is None:
            cands = by_name.get(n, [])
            rec = cands[0] if len(cands) == 1 else None
        if rec is None:
            body.append(""), upd.append(""), espn.append("")
            continue
        body.append(str(rec.get("injury_body_part") or ""))
        upd.append(_iso(rec["news_updated"]) if rec.get("news_updated") else "")
        espn.append(str(rec["espn_id"]) if rec.get("espn_id") else "")
    out = pool.copy()
    out["body_part"], out["injury_updated"], out["espn_id"] = body, upd, espn
    return out


def fetch_news(espn_id, sport, session=None) -> dict | None:
    """Latest Rotowire blurb for one athlete, or None when ESPN has none (or 404s)."""
    url = ESPN_URL.format(path=ESPN_PATH[sport], espn_id=espn_id)
    if session is None:
        import requests
        session = requests.Session()
    resp = session.get(url, timeout=TIMEOUT_S)
    if getattr(resp, "status_code", 200) == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    rw = data.get("rotowire") if isinstance(data, dict) else None
    if not isinstance(rw, dict) or not (rw.get("headline") or rw.get("story")):
        return None
    pub = parse_published(rw.get("published"))
    return {"headline": str(rw.get("headline") or ""), "story": str(rw.get("story") or ""),
            "published": pub.isoformat() if pub else ""}


# ---------------------------------------------------------------- the pool

def add_injury_columns(pool, sport, *, now, session=None, news_for=None, sleep=time.sleep):
    """Tags/classes/lean/recommendable/play_prob on the pool. Returns (pool, warning); never raises."""
    out = pool.copy()
    n = len(out)
    status = out["status"] if "status" in out.columns else pd.Series([""] * n, index=out.index)
    out["inj_tag"] = [normalize_tag(s) for s in status]
    out["inj_class"] = [tag_class(t) for t in out["inj_tag"]]
    for col in ("body_part", "injury_updated", "espn_id", "news_headline", "news_story",
                "news_published", "lean"):
        out[col] = ""

    warning = ""
    try:
        sl = fetch_sleeper(sport, session)
        extra = attach_sleeper(out, sl, sport)
        for col in ("body_part", "injury_updated", "espn_id"):
            out[col] = extra[col].to_numpy()
    except Exception as exc:  # noqa: BLE001 - any source problem must leave tags intact
        warning = f"; WARNING: injury news unavailable ({type(exc).__name__})"

    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    wanted = set(news_for or ())
    dk = out["dk_id"] if "dk_id" in out.columns else pd.Series([None] * n, index=out.index)
    fetched = 0
    for i in range(n):
        eid = out["espn_id"].iat[i]
        if not eid or not (out["inj_tag"].iat[i] != "" or dk.iat[i] in wanted):
            continue
        try:
            if fetched:
                sleep(config.NEWS_DELAY_S)
            fetched += 1
            news = fetch_news(eid, sport, session)
        except Exception as exc:  # noqa: BLE001
            if not warning:
                warning = f"; WARNING: injury news unavailable ({type(exc).__name__})"
            continue
        if not news:
            continue
        out.iat[i, out.columns.get_loc("news_headline")] = news["headline"]
        out.iat[i, out.columns.get_loc("news_story")] = news["story"]
        out.iat[i, out.columns.get_loc("news_published")] = news["published"]
        if out["inj_class"].iat[i] == "questionable":
            lv = lean(f"{news['headline']} {news['story']}", parse_published(news["published"]), now)
            out.iat[i, out.columns.get_loc("lean")] = lv or ""

    playable = out["playable"].astype(bool).to_numpy() if "playable" in out.columns else np.ones(n, bool)
    cls = out["inj_class"].to_numpy()
    ok = (cls == "healthy") | ((cls == "questionable") & (out["lean"].to_numpy() != "out"))
    out["recommendable"] = (ok & playable).astype(bool)
    out["play_prob"] = np.where(~out["recommendable"], 0.0, np.where(cls == "questionable", config.Q_PLAY_PROB, 1.0))
    return out, warning


def recommendable(pool) -> np.ndarray:
    col = "recommendable" if "recommendable" in pool.columns else "playable"
    return pool[col].astype(bool).to_numpy()
