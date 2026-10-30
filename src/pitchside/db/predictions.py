"""Write frozen prediction runs. Predictions are append-only (enforced by the database)."""
import json
import hashlib
from datetime import datetime

import psycopg

from pitchside.markets.base import Market
from pitchside.confidence import RULES_PATH, load_rules, tier_for


def ensure_model_version(conn: psycopg.Connection, version_id: str, description: str, params: dict) -> None:
    conn.execute(
        "INSERT INTO model_versions (id, description, params) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (version_id, description, json.dumps(params)),
    )


def create_run(conn: psycopg.Connection, run_type: str, model_version_id: str, feature_version: str,
               data_cutoff: datetime, notes: str | None = None) -> str:
    rules_hash = hashlib.sha256(RULES_PATH.read_bytes()).hexdigest() if RULES_PATH.exists() else None
    return str(conn.execute(
        "INSERT INTO prediction_runs (run_type, model_version_id, feature_version, data_cutoff, notes, confidence_rules_hash) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (run_type, model_version_id, feature_version, data_cutoff, notes, rules_hash),
    ).fetchone()[0])


def pick_flags(rows: list[dict], markets: dict[str, Market]) -> set[tuple]:
    """Keys (market_id, line, selection) of the most likely selection in each market whose outcomes are exclusive."""
    best: dict[tuple, dict] = {}
    for r in rows:
        if not markets[r["market_id"]].exclusive:
            continue
        key = (r["market_id"], r["line"])
        if key not in best or r["probability"] > best[key]["probability"]:
            best[key] = r
    return {(r["market_id"], r["line"], r["selection"]) for r in best.values()}


def write_predictions(conn: psycopg.Connection, run_id: str, match_id: int, rows: list[dict],
                      markets: dict[str, Market], why: dict) -> int:
    rows = [r for r in rows if r["probability"] == r["probability"]]  # drop NaN (no live stake), the DB rejects it
    picks = pick_flags(rows, markets)
    rules = load_rules() if RULES_PATH.exists() else None
    params = [
        (run_id, match_id, r["market_id"], r["line"], r["selection"], round(r["probability"], 6),
         (r["market_id"], r["line"], r["selection"]) in picks,
         None if rules is None else tier_for(rules, r["market_id"], markets[r["market_id"]].family, float(r["probability"])).lower(),
         json.dumps({**why, **({"p_push": round(r["p_push"], 6)} if r["p_push"] > 0.0005 else {})}))
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO predictions (run_id, match_id, market_id, line, selection, probability, is_pick, confidence_tier, why) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            params,
        )
    return len(params)


def write_context(conn: psycopg.Connection, run_id: str, match_id: int, context: dict) -> None:
    conn.execute("INSERT INTO prediction_context (run_id, match_id, context) VALUES (%s, %s, %s)",
                 (run_id, match_id, json.dumps(context)))
