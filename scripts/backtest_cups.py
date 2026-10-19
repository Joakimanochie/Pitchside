"""Can a model that rates every club on one scale, using domestic and European matches together, predict Champions League and Europa League matches?

Cup results come from openfootball (public domain; loaded by scripts/load_cup_history.py: CL 2015/16 on, EL 2020/21 on; the score of record is the 90-minute score), domestic
results of the five leagues and the Championship from the database. Clubs outside those leagues have no domestic data here: their ratings come from cup matches alone and
they are pulled toward the average of a shared "other" group. Walk-forward: every week the model is refit on matches strictly before it and predicts the cup matches of that
week (2021/22 on). Compared with
  - the usual frequencies of home win, draw, away win, over 2.5 and both teams to score among earlier cup matches (the baseline),
  - a cup-only Dixon-Coles (no domestic data),
  - the cross-league model (`models/pyramid.py` with `team_group`).
Reads the database (SELECT only).   Usage: uv run python scripts/backtest_cups.py [step_days]
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, os.path.dirname(__file__))
from backtest_pyramid import binary_ll

from pitchside.db.migrate import _load_env
from pitchside.models.evaluate import (
    btts_probability,
    log_loss,
    over_probability,
    result_probs,
)
from pitchside.models.pyramid import PyramidDixonColes
from pitchside.pipeline.weekly import MODEL_PARAMS

DOMESTIC = ["EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1", "CHAMP"]
TEST_START = pd.Timestamp("2021-08-01").date()


def load_domestic(conn) -> pd.DataFrame:
    rows = conn.execute(
        "SELECT m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.status = 'finished' AND m.league_id = ANY(%s) ORDER BY m.match_date",
        (DOMESTIC,)).fetchall()
    return pd.DataFrame(rows, columns=["league", "season", "match_date", "home", "away", "ft_home", "ft_away"])


def load_cups(conn) -> pd.DataFrame:
    """Cup matches as loaded by scripts/load_cup_history.py (clubs already merged to one name each)."""
    rows = conn.execute(
        "SELECT m.league_id, m.season, m.match_date, th.canonical_name, ta.canonical_name, m.ft_home, m.ft_away FROM matches m "
        "JOIN teams th ON th.id = m.home_team_id JOIN teams ta ON ta.id = m.away_team_id WHERE m.status = 'finished' AND m.league_id IN ('CL', 'EL') ORDER BY m.match_date, m.id").fetchall()
    return pd.DataFrame(rows, columns=["league", "season", "match_date", "home", "away", "ft_home", "ft_away"])


def groups_of(domestic: pd.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in domestic.sort_values("match_date", kind="stable").itertuples(index=False):
        out[r.home] = r.league
        out[r.away] = r.league
    return out


def params() -> dict:
    return {"half_life_days": MODEL_PARAMS["half_life_days"], "ridge": MODEL_PARAMS["ridge"], "level_window_days": MODEL_PARAMS["level_window_days"],
            "level_shrink": MODEL_PARAMS["level_shrink"], "total_compression": MODEL_PARAMS["total_compression"]}


def main(step_days: int) -> None:
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        dom = load_domestic(conn)
        cups = load_cups(conn)
    in_dom = set(dom["home"]) | set(dom["away"])
    unknown = int((~cups[["home", "away"]].stack().isin(in_dom)).sum())
    print(f"{len(dom):,} domestic and {len(cups):,} cup matches; {unknown:,} club-appearances without domestic data")
    everything = pd.concat([dom, cups], ignore_index=True).sort_values("match_date", kind="stable").reset_index(drop=True)
    rows = []
    end = cups["match_date"].max()
    block = TEST_START
    while block <= end:
        nxt = block + timedelta(days=step_days)
        chunk = cups[(cups["match_date"] >= block) & (cups["match_date"] < nxt)]
        if len(chunk):
            past_cups = cups[cups["match_date"] < block]
            past = everything[everything["match_date"] < block]
            hist_groups = groups_of(past[past["league"].isin(DOMESTIC)])
            for comp in sorted(chunk["league"].unique()):
                tgt = chunk[chunk["league"] == comp]
                mine = past_cups[past_cups["league"] == comp]
                if len(mine) < 50:
                    mine = past_cups                      # Europa League in its first weeks: fall back to all cup matches for the baseline
                w = 0.5 ** ((pd.Series([(block - d).days for d in mine["match_date"]]).to_numpy()) / MODEL_PARAMS["half_life_days"])
                usual = {"h": float(((mine["ft_home"] > mine["ft_away"]).to_numpy() * w).sum() / w.sum()), "d": float(((mine["ft_home"] == mine["ft_away"]).to_numpy() * w).sum() / w.sum()),
                         "over": float((((mine["ft_home"] + mine["ft_away"]) > 2.5).to_numpy() * w).sum() / w.sum()), "btts": float((((mine["ft_home"] > 0) & (mine["ft_away"] > 0)).to_numpy() * w).sum() / w.sum())}
                cross = PyramidDixonColes(**params(), target_league=comp, team_group=hist_groups, ref_group="EPL").fit(everything, as_of=block)
                alone = PyramidDixonColes(**params(), target_league=comp).fit(past_cups[past_cups["match_date"] < block], as_of=block)      # same machinery, cup rows only
                for r in tgt.itertuples(index=False):
                    row = {"comp": comp, "date": r.match_date, "y": 0 if r.ft_home > r.ft_away else 1 if r.ft_home == r.ft_away else 2,
                           "over": int(r.ft_home + r.ft_away > 2.5), "btts": int(r.ft_home > 0 and r.ft_away > 0),
                           "both_known": r.home in hist_groups and r.away in hist_groups, "none_known": r.home not in hist_groups and r.away not in hist_groups}
                    row["base_1x2"] = (usual["h"], usual["d"], 1 - usual["h"] - usual["d"])
                    row["base_over"], row["base_btts"] = usual["over"], usual["btts"]
                    for name, model in (("cross", cross), ("cuponly", alone)):
                        p = model.score_matrix(r.home, r.away)
                        row[f"{name}_1x2"] = result_probs(p)
                        row[f"{name}_over"], row[f"{name}_btts"] = over_probability(p, 2.5), btts_probability(p)
                    rows.append(row)
        block = nxt
    out = pd.DataFrame(rows)
    out.to_pickle("data/processed/cups_backtest.pkl")
    report(out)


def summarise(d: pd.DataFrame) -> dict:
    y = d["y"].to_numpy()
    res = {"n": len(d)}
    for name in ("base", "cuponly", "cross"):
        res[f"{name}_1x2"] = log_loss(np.array(list(d[f"{name}_1x2"])), y)
    for name in ("base", "cuponly", "cross"):
        res[f"{name}_ou"] = binary_ll(d[f"{name}_over"], d["over"])
        res[f"{name}_btts"] = binary_ll(d[f"{name}_btts"], d["btts"])
    return res


def report(out: pd.DataFrame) -> None:
    pd.set_option("display.width", 250)
    table = defaultdict(dict)
    for label, sub in (("all", out), ("CL", out[out["comp"] == "CL"]), ("EL", out[out["comp"] == "EL"]), ("both clubs from the six leagues", out[out["both_known"]]),
                       ("neither club from them", out[out["none_known"]]), ("2024/25 on", out[out["date"] >= pd.Timestamp("2024-08-01").date()])):
        if len(sub):
            table[label] = summarise(sub)
    t = pd.DataFrame(table).T
    t["cross_vs_base_1x2"] = t["cross_1x2"] - t["base_1x2"]
    print("match-result log loss (1x2), over/under 2.5 (ou), both teams to score (btts); lower is better")
    print(t.round(4).to_string())
    t.to_csv("data/processed/cups_backtest.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
