"""Confidence tiers (High / Medium / Low) for stored predictions, set from a held-out backtest.

A tier answers one testable question: when the model made predictions like this one, how much better than simply using the usual
frequency of that outcome was it, and was its probability trustworthy? "Like this one" means the same market and the same probability band.

For every (market, band) cell of the backtest we measure
    skill = 1 - (model log loss / base-rate log loss) over the cell's selections, base rate = how often that exact selection happened,
    gap   = average predicted probability - how often it happened (calibration), judged with its sampling error se.
A cell is High if skill >= HIGH_SKILL and |gap| <= HIGH_GAP + se, Medium if skill >= MEDIUM_SKILL and |gap| <= MEDIUM_GAP + se, otherwise Low;
and it needs at least MIN_CELL selections to be rated at all (sparse cells fall back to the market family in the same band, then to Low).
A prediction far from the usual frequency carries information; one close to it carries almost none, which is why a 95% "Over 0.5 goals" is Low.

Input quality was tested as a cap (no High when a team has under 60 matches in the last three years, for example a promoted side) and dropped:
on held-out matches those games were predicted no worse (skill over the base rate +3.6% against +2.9%, calibration the same).

Not included: model uncertainty (the spread of a probability across refits). It is not measured yet, and the tiers do not claim it.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

BAND_EDGES = (0.0, 0.10, 0.25, 0.40, 0.60, 0.75, 0.90, 1.0000001)
HIGH_SKILL, HIGH_GAP = 0.05, 0.03
MEDIUM_SKILL, MEDIUM_GAP = 0.015, 0.05
MIN_CELL = 200
BASE_FLOOR = 0.005
RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "confidence_rules.json"
TIERS = ("High", "Medium", "Low")
UNRATED = 3        # tier shown for leagues the ratings were not built from
# The ratings and the half-time/goal-timing inputs come from tests on these five leagues. Other leagues (the Championship) get predictions
# from the same models, but no confidence rating until their own backtest exists.
RATED_LEAGUES = ("EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1")
# Player markets (family I) are never rated High: their ratings come from one short backtest and the live record of the lineup-aware version missed (audit 2026-10-25).
CAPPED_AT_MEDIUM = ("I",)


def band_of(p: float) -> int:
    return int(np.searchsorted(BAND_EDGES, p, side="right") - 1)


def _bands(p: pd.Series) -> np.ndarray:
    return np.searchsorted(BAND_EDGES, p.to_numpy(), side="right") - 1


def _key(market_id: str, line, selection: str) -> str:
    return f"{market_id}|{'' if line is None or (isinstance(line, float) and np.isnan(line)) else float(line)}|{selection}"


def base_rates(df: pd.DataFrame) -> dict[str, float]:
    """How often each exact selection happened, smoothed so it is never exactly 0 or 1."""
    rows = df.dropna(subset=["y"])
    g = rows.assign(k=[_key(m, ln, s) for m, ln, s in zip(rows["market_id"], rows["line"], rows["selection"], strict=True)]).groupby("k")["y"]
    return {k: float((v.sum() + 0.5) / (len(v) + 1.0)) for k, v in g}


def _log_loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def score_rows(df: pd.DataFrame, bases: dict[str, float]) -> pd.DataFrame:
    """Rows with the base rate, band and both log losses attached (selections never seen in the base period are dropped)."""
    rows = df.dropna(subset=["y"]).copy()
    rows["base"] = [bases.get(_key(m, ln, s)) for m, ln, s in zip(rows["market_id"], rows["line"], rows["selection"], strict=True)]
    rows = rows.dropna(subset=["base"])
    rows["base"] = rows["base"].clip(BASE_FLOOR, 1 - BASE_FLOOR)
    rows["band"] = _bands(rows["p"])
    rows["ll_model"] = _log_loss(rows["p"].to_numpy(), rows["y"].to_numpy())
    rows["ll_base"] = _log_loss(rows["base"].to_numpy(), rows["y"].to_numpy())
    return rows


def _cells(rows: pd.DataFrame, by: list[str]) -> dict[str, dict]:
    out = {}
    for key, g in rows.groupby(by):
        key = key if isinstance(key, tuple) else (key,)
        skill = 1.0 - float(g["ll_model"].sum() / g["ll_base"].sum())
        gap = float(g["p"].mean() - g["y"].mean())
        se = float(np.sqrt((g["p"] * (1 - g["p"])).mean() / len(g)))
        out["|".join(str(k) for k in key)] = {"n": len(g), "skill": round(skill, 4), "gap": round(gap, 4), "se": round(se, 4),
                                              "tier": tier_from_stats(len(g), skill, gap, se)}
    return out


def tier_from_stats(n: int, skill: float, gap: float, se: float = 0.0) -> str:
    """se is the sampling error of the gap (binomial); a small cell is not judged miscalibrated for noise it could not avoid."""
    if n < MIN_CELL:
        return "Low"
    if skill >= HIGH_SKILL and abs(gap) <= HIGH_GAP + se:
        return "High"
    if skill >= MEDIUM_SKILL and abs(gap) <= MEDIUM_GAP + se:
        return "Medium"
    return "Low"


def fit_rules(df: pd.DataFrame) -> dict:
    """Rules from backtest rows with columns market_id, family, line, selection, p, y."""
    bases = base_rates(df)
    rows = score_rows(df, bases)
    return {
        "thresholds": {"high_skill": HIGH_SKILL, "high_gap": HIGH_GAP, "medium_skill": MEDIUM_SKILL, "medium_gap": MEDIUM_GAP,
                       "min_cell": MIN_CELL, "band_edges": list(BAND_EDGES[:-1]) + [1.0]},
        "markets": _cells(rows, ["market_id", "band"]),
        "families": _cells(rows, ["family", "band"]),
    }


def tier_for(rules: dict, market_id: str, family: str, p: float) -> str:
    band = band_of(p)
    cell = rules["markets"].get(f"{market_id}|{band}")
    if cell is None or cell["n"] < rules["thresholds"]["min_cell"]:
        cell = rules["families"].get(f"{family}|{band}")
    tier = cell["tier"] if cell is not None else "Low"
    return "Medium" if tier == "High" and family in CAPPED_AT_MEDIUM else tier


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
