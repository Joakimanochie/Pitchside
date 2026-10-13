"""Export a JSON snapshot of the latest stored predictions for the web prototype (SELECT only; nothing is written).

Reads DATABASE_URL, takes the newest weekly run of the newest model version for every upcoming match, and writes
web/prototype/data/snapshot.json together with the held-out validation numbers shown on the track-record screen.

Usage: uv run python scripts/export_prototype_data.py
"""
import csv
import json
import math
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from pitchside.confidence import TIERS, load_rules, tier_for
from pitchside.db.migrate import _load_env
from pitchside.leagues import LEAGUES
from pitchside.markets.registry import MARKETS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "prototype" / "data" / "snapshot.json"
PROCESSED = ROOT / "data" / "processed"
CACHE = ROOT / "web" / "validation.json"


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


def validation_cached() -> dict:
    """The backtest log is not in git, so the parsed numbers are kept in a committed file and reused where it is absent (CI)."""
    fresh = validation()
    if fresh["calibration"] and fresh["families"]:
        CACHE.write_text(json.dumps(fresh, indent=1), encoding="utf-8")
        return fresh
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return fresh


def live_record(conn: psycopg.Connection, version: str) -> dict:
    """Settled predictions of the current model version, from v_settled (live runs only, never backtests)."""
    base = {sel: float(v) for sel, v in conn.execute(
        "SELECT CASE WHEN ft_home > ft_away THEN 'home' WHEN ft_home = ft_away THEN 'draw' ELSE 'away' END, count(*)::float / sum(count(*)) OVER () "
        "FROM matches WHERE status = 'finished' AND season >= 2019 AND ft_home IS NOT NULL GROUP BY 1")}
    rows = conn.execute(
        "SELECT s.match_id, s.league_id, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away, s.selection, s.probability, s.outcome_value "
        "FROM v_settled s JOIN matches m ON m.id = s.match_id JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE s.model_version_id = %s AND s.run_type = 'weekly' AND s.market_id = '1x2' AND s.outcome_value IS NOT NULL", (version,)).fetchall()
    by_match: dict = {}
    for mid, league, day, home, away, fh, fa, sel, prob, out in rows:
        m = by_match.setdefault(mid, {"league": league, "date": day.isoformat(), "home": home, "away": away, "score": [fh, fa], "p": {}, "actual": None})
        m["p"][sel] = round(float(prob), 4)
        if float(out) == 1:
            m["actual"] = sel
    matches = []
    for m in by_match.values():
        pick = max(m["p"], key=m["p"].get)
        m["pick"], m["hit"] = pick, int(pick == m["actual"])
        matches.append(m)
    matches.sort(key=lambda m: (m["date"], m["league"], m["home"]))
    n = len(matches)
    ll = sum(-math.log(m["p"][m["actual"]]) for m in matches) / n if n else None
    ll_base = sum(-math.log(base[m["actual"]]) for m in matches) / n if n else None

    def rate(market: str, sel: str, line: float | None = None) -> dict:
        q = ("SELECT count(*), avg(probability), avg(outcome_value) FROM v_settled WHERE model_version_id = %s AND run_type = 'weekly' "
             "AND market_id = %s AND selection = %s AND outcome_value IS NOT NULL")
        args: list = [version, market, sel]
        if line is not None:
            q += " AND line = %s"
            args.append(line)
        c, pr, ac = conn.execute(q, args).fetchone()
        return {"n": c, "predicted": round(float(pr), 4) if c else None, "actual": round(float(ac), 4) if c else None}

    calib = [{"from": float(b), "n": int(c), "predicted": round(float(pr), 4), "actual": round(float(ac), 4)} for b, c, pr, ac in conn.execute(
        "SELECT floor(least(probability, 0.9999) * 10) / 10, count(*), avg(probability), avg(outcome_value) FROM v_settled "
        "WHERE model_version_id = %s AND run_type = 'weekly' AND outcome_value IS NOT NULL GROUP BY 1 ORDER BY 1", (version,))]
    fams = [{"family": f, "n": int(c), "log_loss": round(float(l), 4)} for f, c, l in conn.execute(
        "SELECT family, count(*), avg(log_loss) FROM v_settled WHERE model_version_id = %s AND run_type = 'weekly' AND outcome_value IS NOT NULL GROUP BY 1 ORDER BY 1", (version,))]
    waiting = conn.execute(
        "SELECT count(*) FROM settlements st JOIN predictions p ON p.id = st.prediction_id JOIN prediction_runs r ON r.id = p.run_id "
        "WHERE r.model_version_id = %s AND st.result = 'not_scorable'", (version,)).fetchone()[0]
    return {"matches": matches, "n": n, "log_loss": ll, "log_loss_base": ll_base,
            "pick_hits": sum(m["hit"] for m in matches), "home": rate("1x2", "home"), "draw": rate("1x2", "draw"), "away": rate("1x2", "away"),
            "btts_yes": rate("btts", "yes"), "over25": rate("ou_total", "over", 2.5), "calibration": calib, "families": fams,
            "selections": sum(f["n"] for f in fams), "waiting_minutes": int(waiting)}


def main() -> None:
    _load_env()
    order = {mid: i for i, mid in enumerate(MARKETS)}
    rules = load_rules()
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
            tier = TIERS.index(tier_for(rules, market_id, MARKETS[market_id].family, float(prob))) if market_id in MARKETS else 2
            preds[mid][market_id]["null" if line is None else str(float(line))].append([sel, round(float(prob), 4), 1 if pick else 0, tier])

        # the live record belongs to the newest model version that already has scored matches
        scored = conn.execute(
            "SELECT s.model_version_id FROM v_settled s JOIN prediction_runs r ON r.model_version_id = s.model_version_id AND r.run_type = 'weekly' "
            "WHERE s.run_type = 'weekly' GROUP BY 1 ORDER BY max(r.created_at) DESC LIMIT 1").fetchone()
        live = live_record(conn, scored[0] if scored else version)
        live["model_version"] = scored[0] if scored else version

    markets = {mid: {"name": m.name, "family": m.family, "exclusive": m.exclusive, "order": order[mid]} for mid, m in MARKETS.items()}
    fixtures = []
    for mid, league, kickoff, home, away in matches:
        x12 = {s: p for s, p, *_ in preds[mid]["1x2"]["null"]}
        fixtures.append({"id": mid, "league": league, "kickoff": kickoff.astimezone(UTC).isoformat(), "home": home, "away": away,
                         "p": x12, "ctx": ctx.get(mid, {})})
    snapshot = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "model_version": version,
        "leagues": {lid: lg.name for lid, lg in LEAGUES.items()}, "markets": markets, "fixtures": fixtures,
        "preds": {str(mid): preds[mid] for mid in ids}, "validation": validation_cached(), "live": live,
        "confidence": {"labels": list(TIERS), "validation": rules.get("validation"), "backtest": rules.get("backtest")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    n_rows = sum(len(v) for mm in preds.values() for ml in mm.values() for v in ml.values())
    print(f"wrote {OUT.relative_to(ROOT)}: {len(fixtures)} matches, {n_rows} selections, {OUT.stat().st_size / 1e6:.2f} MB, model {version}")
    print("validation:", {k: len(v) for k, v in snapshot["validation"].items()})


if __name__ == "__main__":
    main()
