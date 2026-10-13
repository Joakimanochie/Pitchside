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

from pitchside.db.migrate import _load_env

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


def main() -> None:
    _load_env()
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
                      "h2h": meetings(conn, f["home_id"], f["away_id"], day)}
            (match_dir / f"{f['id']}.json").write_text(json.dumps(detail, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            x12 = snap["preds"][str(f["id"])]["1x2"]["null"]
            index_fixtures.append({"id": f["id"], "league": f["league"], "kickoff": f["kickoff"], "home": f["home"], "away": f["away"], "p": f["p"],
                                   "tiers": {sel: tier for sel, _p, _pick, tier in x12}})
    index = {k: v for k, v in snap.items() if k not in ("fixtures", "preds")}
    index["fixtures"] = index_fixtures
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*.json")) / 1e6
    print(f"wrote {OUT.relative_to(base.ROOT)}: {len(index_fixtures)} matches, {size:.2f} MB, model {snap['model_version']}")


if __name__ == "__main__":
    main()
