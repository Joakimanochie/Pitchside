"""Shared by the web app exporter (scripts/export_app_data.py): the latest stored predictions for upcoming matches, the live record, the confidence
ratings and the held-out validation numbers. SELECT only; nothing is written to the database.
"""
import csv
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from pitchside.confidence import RATED_LEAGUES, TIERS, UNRATED, load_rules, tier_for
from pitchside.leagues import LEAGUES
from pitchside.markets.players import LOG_STATS
from pitchside.markets.registry import MARKETS

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
CACHE = ROOT / "web" / "validation.json"
PAUSED_PLAYER_VERSIONS = ("players-0.4.0",)    # the lineup-aware player model: miscalibrated on the live record, no longer shown (audit 2026-10-25)


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
        "FROM matches WHERE status = 'finished' AND season >= 2019 AND ft_home IS NOT NULL AND league_id = ANY(%s) GROUP BY 1", (list(RATED_LEAGUES),))}
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


def live_lines(conn: psycopg.Connection) -> list[dict]:
    """The live record of every model version that has scored matches: goals, corners/cards/shots and players are separate lines.
    Only one-sided probabilities against what happened: mean predicted vs mean actual, and a log loss, per version."""
    out = []
    for version, run_type_matches, sels, pred, act, ll in conn.execute(
            "SELECT model_version_id, count(DISTINCT match_id), count(*), avg(probability), avg(outcome_value), avg(log_loss) FROM v_settled "
            "WHERE run_type = 'weekly' AND outcome_value IS NOT NULL GROUP BY 1 ORDER BY 1 DESC"):
        calib = [{"from": float(b), "n": int(c), "predicted": round(float(pr), 4), "actual": round(float(ac), 4)} for b, c, pr, ac in conn.execute(
            "SELECT floor(least(probability, 0.9999) * 10) / 10, count(*), avg(probability), avg(outcome_value) FROM v_settled "
            "WHERE model_version_id = %s AND run_type = 'weekly' AND outcome_value IS NOT NULL GROUP BY 1 ORDER BY 1", (version,))]
        out.append({"version": version, "matches": int(run_type_matches), "selections": int(sels), "predicted": round(float(pred), 4),
                    "actual": round(float(act), 4), "log_loss": None if ll is None else round(float(ll), 4), "calibration": calib})
    seen = {o["version"] for o in out}
    for version, n in conn.execute(
            "SELECT r.model_version_id, count(DISTINCT p.match_id) FROM prediction_runs r JOIN predictions p ON p.run_id = r.id "
            "WHERE r.run_type = 'weekly' GROUP BY 1 ORDER BY 1 DESC"):
        if version not in seen:
            out.append({"version": version, "matches": 0, "selections": 0, "predicted": None, "actual": None, "log_loss": None, "calibration": [], "stored_for": int(n)})
    line = {"goals": 0, "goalscup": 1, "counts": 2, "cardtime": 3, "players": 4}
    return sorted(out, key=lambda o: (line.get(o["version"].split("-")[0], 9), [-ord(c) for c in o["version"]]))


def with_counts(val: dict) -> dict:
    """Add the held-out results of the corners, cards and shots markets (scripts/backtest_counts.py) to the families table."""
    path = PROCESSED / "count_validation.json"
    if path.exists():
        extra = json.loads(path.read_text(encoding="utf-8"))
        val = {**val, "families": [*val["families"], *extra["families"]], "count_matches": extra["matches"]}
    return val


def build_snapshot(conn: psycopg.Connection) -> dict:
    """Everything the screens need, from SELECTs only: upcoming matches with every stored prediction (and its confidence tier),
    the live record, and the validation numbers."""
    order = {mid: i for i, mid in enumerate(MARKETS)}
    rules = load_rules()
    version = conn.execute("SELECT model_version_id FROM prediction_runs WHERE run_type = 'weekly' AND model_version_id LIKE 'goals-%' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    cup = conn.execute("SELECT model_version_id FROM prediction_runs WHERE run_type = 'weekly' AND model_version_id LIKE 'goalscup-%' ORDER BY created_at DESC LIMIT 1").fetchone()
    goal_versions = [version] + ([cup[0]] if cup else [])      # the domestic leagues and the cups are one family on the page
    # the count models (corners, cards, shots) are their own model line; predictions from the newest of each line are shown together
    counts = conn.execute("SELECT model_version_id FROM prediction_runs WHERE run_type = 'weekly' AND model_version_id LIKE 'counts-%' ORDER BY created_at DESC LIMIT 1").fetchone()
    # player markets: every match shows its newest player prediction, except versions paused after the audit (players-0.4.0, the lineup-aware one, was miscalibrated live)
    player_versions = [r[0] for r in conn.execute("SELECT DISTINCT model_version_id FROM prediction_runs WHERE run_type = 'weekly' AND model_version_id LIKE 'players-%%' AND NOT model_version_id = ANY(%s)", (list(PAUSED_PLAYER_VERSIONS),))]
    timing = conn.execute("SELECT model_version_id FROM prediction_runs WHERE run_type = 'weekly' AND model_version_id LIKE 'cardtime-%' ORDER BY created_at DESC LIMIT 1").fetchone()
    versions = goal_versions + ([counts[0]] if counts else []) + ([timing[0]] if timing else []) + player_versions
    matches = conn.execute(
        "SELECT DISTINCT m.id, m.league_id, m.kickoff, th.canonical_name, ta.canonical_name, m.home_team_id, m.away_team_id FROM predictions p "
        "JOIN prediction_runs r ON r.id = p.run_id JOIN matches m ON m.id = p.match_id "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id "
        "WHERE r.model_version_id = ANY(%s) AND r.run_type = 'weekly' AND m.status = 'scheduled' ORDER BY m.kickoff, m.id", (goal_versions,)).fetchall()
    ids = [m[0] for m in matches]
    league_of = {m[0]: m[1] for m in matches}
    ctx = {mid: c for mid, c in conn.execute(
        "SELECT c.match_id, c.context FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id "
        "WHERE r.model_version_id = ANY(%s) AND c.match_id = ANY(%s)", (goal_versions, ids))}
    preds: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for mid, market_id, line, sel, prob, pick in conn.execute(
            "SELECT p.match_id, p.market_id, p.line, p.selection, p.probability, p.is_pick FROM predictions p "
            "JOIN prediction_runs r ON r.id = p.run_id WHERE r.model_version_id = ANY(%s) AND r.run_type = 'weekly' "
            "AND p.match_id = ANY(%s) AND (r.model_version_id NOT LIKE 'players-%%' OR r.id = (SELECT r2.id FROM prediction_runs r2 JOIN predictions p2 ON p2.run_id = r2.id "
            "WHERE p2.match_id = p.match_id AND r2.model_version_id LIKE 'players-%%' AND NOT r2.model_version_id = ANY(%s) AND r2.run_type = 'weekly' ORDER BY r2.created_at DESC LIMIT 1)) ORDER BY p.id", (versions, ids, list(PAUSED_PLAYER_VERSIONS))):
        if market_id in MARKETS and MARKETS[market_id].family == 'I' and MARKETS[market_id].player_stat not in LOG_STATS and league_of[mid] not in RATED_LEAGUES:
            continue            # no shot-based player markets for leagues without shot data (cards and fouls come from the ESPN log and exist everywhere)
        tier = (UNRATED if league_of[mid] not in RATED_LEAGUES else TIERS.index(tier_for(rules, market_id, MARKETS[market_id].family, float(prob)))) if market_id in MARKETS else 2
        preds[mid][market_id]["null" if line is None else str(float(line))].append([sel, round(float(prob), 4), 1 if pick else 0, tier])

    # the live match-result record belongs to the newest domestic goals version that already has scored matches (a newer player or card version must not take its place)
    scored = conn.execute(
        "SELECT s.model_version_id FROM v_settled s JOIN prediction_runs r ON r.model_version_id = s.model_version_id AND r.run_type = 'weekly' "
        "WHERE s.run_type = 'weekly' AND s.market_id = '1x2' AND s.outcome_value IS NOT NULL AND s.model_version_id LIKE 'goals-%' "
        "GROUP BY 1 ORDER BY max(r.created_at) DESC LIMIT 1").fetchone()
    live = live_record(conn, scored[0] if scored else version)
    live["model_version"] = scored[0] if scored else version
    live["lines"] = live_lines(conn)

    markets = {mid: {"name": m.name, "family": m.family, "exclusive": m.exclusive, "order": order[mid]} for mid, m in MARKETS.items()}
    fixtures = []
    for mid, league, kickoff, home, away, home_id, away_id in matches:
        x12 = {s: p for s, p, *_ in preds[mid]["1x2"]["null"]}
        fixtures.append({"id": mid, "league": league, "kickoff": kickoff.astimezone(UTC).isoformat(), "home": home, "away": away,
                         "p": x12, "ctx": ctx.get(mid, {}), "home_id": home_id, "away_id": away_id})
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "model_version": version, "count_model_version": counts[0] if counts else None,
        "leagues": {lid: lg.name for lid, lg in LEAGUES.items()}, "markets": markets, "fixtures": fixtures,
        "preds": {str(mid): preds[mid] for mid in ids}, "validation": with_counts(validation_cached()), "live": live,
        "confidence": {"labels": list(TIERS), "validation": rules.get("validation"), "backtest": rules.get("backtest")},
    }
