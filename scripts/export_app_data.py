"""Export the data files the web app reads: one small index plus one file per upcoming match (SELECT only; nothing is written to the database).

The web app holds no database credentials. The daily pipeline writes these files and they ship with the app, so every page is a static read.

    web/app/static/data/index.json          fixtures (with the match-result probabilities and ratings), markets, leagues, live record, validation
    web/app/static/data/match/<id>.json     every stored prediction for the match, plus recent results and head-to-head

Usage: uv run python scripts/export_app_data.py
"""
import json
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_common as base

from pitchside.confidence import load_rules
from pitchside.db.migrate import _load_env
from pitchside.markets.registry import MARKETS
from pitchside.odds.compare import demargin, edge, expected_value, overround

OUT = base.ROOT / "web" / "app" / "static" / "data"
FORM_MATCHES, H2H_MATCHES = 6, 5


def recent_results(conn: psycopg.Connection, team_id: int, before: str) -> list[dict]:
    """The team's last finished matches before the date, newest first, from its own point of view."""
    out = []
    for day, home_id, ft_h, ft_a, hn, an in conn.execute(
            "SELECT m.match_date, m.home_team_id, m.ft_home, m.ft_away, th.canonical_name, ta.canonical_name FROM matches m "
            "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
            "WHERE m.status = 'finished' AND m.match_date < %s AND (m.home_team_id = %s OR m.away_team_id = %s) "
            "ORDER BY m.match_date DESC LIMIT %s", (before, team_id, team_id, FORM_MATCHES)):
        home = home_id == team_id
        gf, ga = (ft_h, ft_a) if home else (ft_a, ft_h)
        out.append({"date": day.isoformat(), "opponent": an if home else hn, "home": home, "gf": gf, "ga": ga,
                    "result": "W" if gf > ga else "D" if gf == ga else "L"})
    return out


def meetings(conn: psycopg.Connection, home_id: int, away_id: int, before: str) -> list[dict]:
    out = []
    for day, ft_h, ft_a, hn, an in conn.execute(
            "SELECT m.match_date, m.ft_home, m.ft_away, th.canonical_name, ta.canonical_name FROM matches m "
            "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
            "WHERE m.status = 'finished' AND m.match_date < %s AND ((m.home_team_id = %s AND m.away_team_id = %s) "
            "OR (m.home_team_id = %s AND m.away_team_id = %s)) ORDER BY m.match_date DESC LIMIT %s",
            (before, home_id, away_id, away_id, home_id, H2H_MATCHES)):
        out.append({"date": day.isoformat(), "home": hn, "away": an, "ft_home": ft_h, "ft_away": ft_a})
    return out


def odds_block(conn: psycopg.Connection, match_id: int, preds: dict, rules: dict) -> dict | None:
    """Latest bookmaker prices for the match set against our probabilities: the market average (de-margined into the bookmakers' own view)
    and the best price. None when no prices are stored yet."""
    rows = conn.execute("SELECT bookmaker, market_id, line, selection, odds, fetched_at FROM v_latest_odds WHERE match_id = %s", (match_id,)).fetchall()
    if not rows:
        return None
    grouped: dict = {}
    for bookmaker, market, line, sel, odds, fetched in rows:
        key = (market, None if line is None else float(line))
        grouped.setdefault(key, {}).setdefault(bookmaker, {})[sel] = (float(odds), fetched)
    markets, newest = [], None
    for (market, line), books in sorted(grouped.items(), key=lambda kv: (list(MARKETS).index(kv[0][0]) if kv[0][0] in MARKETS else 99, kv[0][1] or 0)):
        ours = {sel: (p, pick, tier) for sel, p, pick, tier in preds.get(market, {}).get("null" if line is None else str(float(line)), [])}
        avg = books.get("avg")
        if not ours or not avg or set(avg) != set(ours):
            continue
        sels = list(avg)
        fair = dict(zip(sels, demargin([avg[sel][0] for sel in sels]), strict=True))
        half_line = line is not None and abs(line * 2 - round(line * 2)) < 1e-9 and round(line * 2) % 2 != 0
        whole_or_quarter = market == "asian_handicap" and not half_line   # the stake can be returned or split, which our probability excludes
        best = books.get("max", {})
        out = []
        for sel in sels:
            p, _pick, tier = ours[sel]
            best_odds = best[sel][0] if sel in best else avg[sel][0]
            out.append({"selection": sel, "p": p, "tier": tier, "fair": round(fair[sel], 4), "avg_odds": avg[sel][0], "best_odds": best_odds,
                        "edge": round(edge(p, fair[sel]), 4), "ev": None if whole_or_quarter else round(expected_value(p, best_odds), 4)})
        stamp = max(v[1] for v in avg.values())
        newest = stamp if newest is None or stamp > newest else newest
        markets.append({"market": market, "line": line, "margin": round(overround([avg[sel][0] for sel in sels]), 4), "stake_can_be_returned": bool(whole_or_quarter), "rows": out})
    if not markets:
        return None
    return {"fetched_at": newest.astimezone(base.UTC).isoformat(timespec="minutes"), "source": "football-data.co.uk", "markets": markets}


def main() -> None:
    _load_env()
    rules = load_rules()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        snap = base.build_snapshot(conn)
        match_dir = OUT / "match"
        match_dir.mkdir(parents=True, exist_ok=True)
        for old in match_dir.glob("*.json"):   # only matches still upcoming stay
            old.unlink()
        index_fixtures = []
        for f in snap["fixtures"]:
            day = f["kickoff"][:10]
            detail = {"id": f["id"], "league": f["league"], "kickoff": f["kickoff"], "home": f["home"], "away": f["away"], "p": f["p"], "ctx": f["ctx"],
                      "preds": snap["preds"][str(f["id"])],
                      "form": {"home": recent_results(conn, f["home_id"], day), "away": recent_results(conn, f["away_id"], day)},
                      "h2h": meetings(conn, f["home_id"], f["away_id"], day),
                      "odds": odds_block(conn, f["id"], snap["preds"][str(f["id"])], rules)}
            (match_dir / f"{f['id']}.json").write_text(json.dumps(detail, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            x12 = snap["preds"][str(f["id"])]["1x2"]["null"]
            index_fixtures.append({"has_odds": detail["odds"] is not None, "id": f["id"], "league": f["league"], "kickoff": f["kickoff"], "home": f["home"], "away": f["away"], "p": f["p"],
                                   "tiers": {sel: tier for sel, _p, _pick, tier in x12}})
    index = {k: v for k, v in snap.items() if k not in ("fixtures", "preds")}
    index["fixtures"] = index_fixtures
    backtest = base.ROOT / "data" / "processed" / "value_backtest.json"
    index["value_backtest"] = json.loads(backtest.read_text(encoding="utf-8")) if backtest.exists() else None
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*.json")) / 1e6
    print(f"wrote {OUT.relative_to(base.ROOT)}: {len(index_fixtures)} matches, {size:.2f} MB, model {snap['model_version']}")


if __name__ == "__main__":
    main()
