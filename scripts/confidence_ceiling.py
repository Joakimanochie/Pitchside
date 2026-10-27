"""How often can the model be 90% sure, and how often is it right when it is?

Prices every selection a betting site widely offers (match result, double chance, total goals 0.5 to 4.5 both ways, each team's goals 0.5 to 2.5 both ways, both teams to score yes/no)
for the held-out seasons 2022/23 onward from the cached walk-forward expected goals (`scripts/cache_lambdas.py`), then groups the selections by the probability the model gave
and counts how often each group happened. Also: how often the single most likely match result is right, and how many matches have any 90% selection at all.

    uv run python scripts/confidence_ceiling.py
"""
import numpy as np
import pandas as pd
from improve_totals import LEAGUES, TEST, TOTAL, matrix

BANDS = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 1.01)]
TEAM_LINES = (0.5, 1.5, 2.5)


def selections(p, hg, ag):
    """[(name, probability, happened)] for one match."""
    res = {"home win": (np.tril(p, -1).sum(), hg > ag), "draw": (np.trace(p), hg == ag), "away win": (np.triu(p, 1).sum(), hg < ag)}
    out = list(res.items())
    out += [("home or draw", (res["home win"][0] + res["draw"][0], hg >= ag)), ("away or draw", (res["away win"][0] + res["draw"][0], hg <= ag)),
            ("home or away", (res["home win"][0] + res["away win"][0], hg != ag))]
    for k in (0.5, 1.5, 2.5, 3.5, 4.5):
        o = p[TOTAL > k].sum()
        out += [(f"over {k} goals", (o, hg + ag > k)), (f"under {k} goals", (1 - o, hg + ag < k))]
    for k in TEAM_LINES:
        n = int(k + 0.5)
        ho, ao = p[n:, :].sum(), p[:, n:].sum()
        out += [(f"home over {k}", (ho, hg > k)), (f"home under {k}", (1 - ho, hg < k)), (f"away over {k}", (ao, ag > k)), (f"away under {k}", (1 - ao, ag < k))]
    b = p[1:, 1:].sum()
    out += [("both teams score", (b, hg > 0 and ag > 0)), ("not both teams score", (1 - b, not (hg > 0 and ag > 0)))]
    return [(n, float(pr), bool(h)) for n, (pr, h) in out]


def main() -> None:
    df = pd.concat([pd.read_pickle(f"data/processed/lambdas_{lg}.pkl") for lg in LEAGUES], ignore_index=True)
    df = df[df.season.between(*TEST)].reset_index(drop=True)
    rows, top_ok, top_p, any90, any95 = [], [], [], 0, 0
    for r in df.itertuples():
        p = matrix(r.lam_h, r.lam_a, r.rho)
        sel = selections(p, r.ft_home, r.ft_away)
        rows += [(r.Index, n, pr, h) for n, pr, h in sel]
        res = [(pr, h) for n, pr, h in sel[:3]]
        top = max(res)
        top_ok.append(top[1]), top_p.append(top[0])
        any90 += any(pr >= 0.90 for _, pr, _ in sel)
        any95 += any(pr >= 0.95 for _, pr, _ in sel)
    s = pd.DataFrame(rows, columns=["match", "selection", "p", "happened"])
    print(f"{len(df):,} matches, {len(s):,} selections (held-out seasons 2022/23 onward)\n")
    print("how often selections happened, by the probability the model gave:")
    out = []
    for lo, hi in BANDS:
        g = s[(s.p >= lo) & (s.p < hi)]
        out.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "selections": len(g), "model said": g.p.mean(), "happened": g.happened.mean(), "matches with at least one": g.match.nunique()})
    t = pd.DataFrame(out)
    t.to_csv("data/processed/confidence_ceiling.csv", index=False)
    print(t.round(3).to_string(index=False))
    print(f"\nmatches with at least one 90%+ selection: {any90 / len(df):.1%}; at least one 95%+: {any95 / len(df):.1%}")
    g = s[s.p >= 0.90]
    print("\nwhat the 90%+ selections are:")
    print(g.groupby("selection").agg(n=("p", "size"), model_said=("p", "mean"), happened=("happened", "mean")).sort_values("n", ascending=False).round(3).to_string())
    print(f"\nmost likely match result: right {np.mean(top_ok):.1%} of the time overall (model said {np.mean(top_p):.1%} on average)")
    top_ok, top_p = np.array(top_ok), np.array(top_p)
    for lo in (0.5, 0.6, 0.7):
        sel = top_p >= lo
        print(f"  when its top result was at least {lo:.0%}: {sel.mean():.1%} of matches, right {top_ok[sel].mean():.1%}")


if __name__ == "__main__":
    main()
