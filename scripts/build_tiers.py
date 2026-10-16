"""Set the confidence tiers from data/raw/tier_backtest.csv.gz (made by scripts/backtest_tiers.py).

1. Rules are fitted on the earlier 60% of the held-out matches (by date) and checked on the later 40%: a tier only means something if
   High predictions beat Medium and Medium beat Low on matches the rules never saw.
2. Final rules are then refitted on all of it and written to data/confidence_rules.json.
Usage: uv run python scripts/build_tiers.py
"""
import json
from pathlib import Path

import pandas as pd

from pitchside.confidence import (
    RULES_PATH,
    base_rates,
    fit_rules,
    score_rows,
    tier_for,
)

SRC = "data/raw/tier_backtest.csv.gz"            # families A-E (scripts/backtest_tiers.py)
COUNTS = "data/raw/count_backtest.csv.gz"        # families F-H (scripts/backtest_counts.py), added when present
CARD_TIMING = "data/raw/cardtiming_backtest.csv.gz"   # card timing markets, family G (scripts/backtest_cardtiming.py), added when present


def summarise(rows: pd.DataFrame, label: str) -> pd.DataFrame:
    out = []
    for tier in ("High", "Medium", "Low"):
        g = rows[rows["tier"] == tier]
        if len(g):
            out.append({label: tier, "selections": len(g), "share": len(g) / len(rows), "avg_predicted": g["p"].mean(), "happened": g["y"].mean(),
                        "skill_vs_base": 1 - g["ll_model"].sum() / g["ll_base"].sum(), "log_loss": g["ll_model"].mean(), "base_log_loss": g["ll_base"].mean()})
    return pd.DataFrame(out)


def main() -> None:
    df = pd.read_csv(SRC, parse_dates=["date"])
    for extra in (COUNTS, CARD_TIMING, *sorted(str(p) for p in Path("data/raw").glob("player_dataset_*.csv.gz"))):   # F-H and the experimental player markets (I), when present
        if Path(extra).exists():
            df = pd.concat([df, pd.read_csv(extra, parse_dates=["date"])], ignore_index=True)
    df["line"] = df["line"].astype(float)
    cut = df["date"].sort_values().iloc[int(len(df) * 0.6)]
    fit, test = df[df["date"] < cut], df[df["date"] >= cut]
    # the player datasets number their rows, not matches, so matches are counted from the team-level markets only
    team = lambda d: d[d["family"] != "I"]["match_id"].nunique()
    print(f"{team(df)} matches; rules fitted on {team(fit)} (before {cut.date()}), checked on {team(test)}")
    rules = fit_rules(fit)
    rows = score_rows(test, base_rates(fit))
    rows["tier"] = [tier_for(rules, m, f, p) for m, f, p in zip(rows["market_id"], rows["family"], rows["p"], strict=True)]
    pd.set_option("display.width", 200)
    print("\nHELD-OUT CHECK (tiers from the earlier matches, scored on the later ones)")
    print(summarise(rows, "tier").round(4).to_string(index=False))
    for fam, g in rows.groupby("family"):
        print(f"\nfamily {fam}")
        print(summarise(g, "tier").round(4).to_string(index=False))
    low_hist = rows["min_team_matches"] < 60  # tested as a cap, see confidence.py
    print(f"\nteams with under 60 recent matches: {low_hist.mean():.1%} of rows")
    for name, g in (("thin history", rows[low_hist]), ("normal history", rows[~low_hist])):
        print(f"  {name}: skill vs base {1 - g['ll_model'].sum() / g['ll_base'].sum():+.4f}, avg predicted {g['p'].mean():.4f}, happened {g['y'].mean():.4f}")

    final = fit_rules(df)
    check = summarise(rows, "tier")
    final["validation"] = {"fitted_on_matches": int(team(fit)), "checked_on_matches": int(team(test)), "until": str(cut.date()),
                           "tiers": [{"tier": r.tier, "share": round(float(r.share), 4), "predicted": round(float(r.avg_predicted), 4), "happened": round(float(r.happened), 4),
                                      "skill": round(float(r.skill_vs_base), 4)} for r in check.itertuples()]}
    final["backtest"] = {"matches": int(team(df)), "from": str(df["date"].min().date()), "to": str(df["date"].max().date()), "selections": len(df)}
    all_rows = score_rows(df, base_rates(df))
    all_rows["tier"] = [tier_for(final, m, f, p) for m, f, p in zip(all_rows["market_id"], all_rows["family"], all_rows["p"], strict=True)]
    print("\nFINAL RULES, all matches (in-sample, for the share of each tier only)")
    print(summarise(all_rows, "tier").round(4).to_string(index=False))
    tiers = {t: int(sum(1 for c in final["markets"].values() if c["tier"] == t)) for t in ("High", "Medium", "Low")}
    print("market-band cells by tier:", tiers)
    RULES_PATH.write_text(json.dumps(final, indent=1), encoding="utf-8")
    print(f"wrote {RULES_PATH}")


if __name__ == "__main__":
    main()
