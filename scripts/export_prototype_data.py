"""Export a JSON snapshot of the latest stored predictions for the web prototype (SELECT only; nothing is written).

Reads DATABASE_URL, takes the newest weekly run of the newest model version for every upcoming match, and writes
web/prototype/data/snapshot.json together with the held-out validation numbers shown on the track-record screen.

Usage: uv run python scripts/export_prototype_data.py
"""
import csv
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from pitchside.db.migrate import _load_env
from pitchside.leagues import LEAGUES
from pitchside.markets.registry import MARKETS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "prototype" / "data" / "snapshot.json"
PROCESSED = ROOT / "data" / "processed"


def validation() -> dict:
    """Numbers shown on the track-record screen, read from files the backtests wrote. Nothing is invented here."""
    out: dict = {"calibration": [], "families": [], "leagues": []}
    log = (PROCESSED / "backtest_sim.log").read_text(encoding="utf-8", errors="ignore") if (PROCESSED / "backtest_sim.log").exists() else ""
    for m in re.finditer(r"predicted ([\d.]+)-([\d.]+): n=\s*(\d+)\s+avg predicted ([\d.]+)\s+actual ([\d.]+)", log):
        lo, hi, n, pred, act = m.groups()
        out["calibration"].append({"from": float(lo), "to": float(hi), "n": int(n), "predicted": float(pred), "actual": float(act)})
    for m in re.finditer(r"^\s*([BCDE])\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s*$", log, re.MULTILINE):
        fam, sel, model, base, skill = m.groups()
        out["families"].append({"family": fam, "selections": int(sel), "model": float(model), "base": float(base), "skill": float(skill)})
    for lid, lg in LEAGUES.items():
        path = PROCESSED / f"backtest_goals_{lid.lower()}_summary.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row[""] == "ALL":
                    out["leagues"].append({
                        "id": lid, "name": lg.name, "matches": int(float(row["n"])),
                        "model": float(row["1x2_logloss_model"]), "base": float(row["1x2_logloss_base"]), "book": float(row["1x2_logloss_book"]),
                        "right_model": float(row["1x2_accuracy_model"]), "right_book": float(row["1x2_accuracy_book"]),
                    })
    return out


def main() -> None:
    _load_env()
    order = {mid: i for i, mid in enumerate(MARKETS)}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        version = conn.execute("SELECT model_version_id FROM prediction_runs WHERE run_type = 'weekly' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        matches = conn.execute(
            "SELECT DISTINCT m.id, m.league_id, m.kickoff, th.canonical_name, ta.canonical_name FROM predictions p "
            "JOIN prediction_runs r ON r.id = p.run_id JOIN matches m ON m.id = p.match_id "
            "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
            "WHERE r.model_version_id = %s AND r.run_type = 'weekly' AND m.status = 'scheduled' ORDER BY m.kickoff, m.id", (version,)).fetchall()
        ids = [m[0] for m in matches]
        ctx = {mid: c for mid, c in conn.execute(
            "SELECT c.match_id, c.context FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id "
            "WHERE r.model_version_id = %s AND c.match_id = ANY(%s)", (version, ids))}
        preds: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for mid, market_id, line, sel, prob, pick in conn.execute(
                "SELECT p.match_id, p.market_id, p.line, p.selection, p.probability, p.is_pick FROM predictions p "
                "JOIN prediction_runs r ON r.id = p.run_id WHERE r.model_version_id = %s AND r.run_type = 'weekly' "
                "AND p.match_id = ANY(%s) ORDER BY p.id", (version, ids)):
            preds[mid][market_id]["null" if line is None else str(float(line))].append([sel, round(float(prob), 4), 1 if pick else 0])

    markets = {mid: {"name": m.name, "family": m.family, "exclusive": m.exclusive, "order": order[mid]} for mid, m in MARKETS.items()}
    fixtures = []
    for mid, league, kickoff, home, away in matches:
        x12 = {s: p for s, p, _ in preds[mid]["1x2"]["null"]}
        fixtures.append({"id": mid, "league": league, "kickoff": kickoff.astimezone(UTC).isoformat(), "home": home, "away": away,
                         "p": x12, "ctx": ctx.get(mid, {})})
    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "model_version": version,
        "leagues": {lid: lg.name for lid, lg in LEAGUES.items()}, "markets": markets, "fixtures": fixtures,
        "preds": {str(mid): preds[mid] for mid in ids}, "validation": validation(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    n_rows = sum(len(v) for mm in preds.values() for ml in mm.values() for v in ml.values())
    print(f"wrote {OUT.relative_to(ROOT)}: {len(fixtures)} matches, {n_rows} selections, {OUT.stat().st_size / 1e6:.2f} MB, model {version}")
    print("validation:", {k: len(v) for k, v in snapshot["validation"].items()})


if __name__ == "__main__":
    main()
