"""Step 1 of docs/model-improvement-research.md: can the over/under and both-teams-to-score probabilities be made better calibrated?

Reads the walk-forward expected goals cached by `scripts/cache_lambdas.py` (production 0.3.0 settings) and prices every variant from them:
  * baseline: the production expected goals and the Dixon-Coles low-score correction;
  * compression beta re-tuned (the production value is 0.7) and a plain scale on the expected total;
  * a per-league scale on the expected total;
  * a bivariate Poisson (the two teams' goals share a common part, so high-scoring games are more likely, means unchanged);
  * a logistic recalibration of each binary probability, fitted on the tuning seasons (an upper bound on what post-hoc calibration can give).
Everything is chosen on the tuning seasons 2019/20 to 2021/22 and then scored on 2022/23 onwards. Log loss, lower is better.

    uv run python scripts/improve_totals.py
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

LEAGUES = ["EPL", "LALIGA", "BUNDESLIGA", "SERIEA", "LIGUE1"]
TUNE, TEST = (2019, 2021), (2022, 2026)
G = 11
GRID = np.arange(G)
OVER_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
TEAM_LINES = (0.5, 1.5)
TOTAL = GRID[:, None] + GRID[None, :]


def matrix(lh, la, rho, cov=0.0):
    """Scoreline matrix: Poisson goals (or a bivariate Poisson with common part `cov`), Dixon-Coles low-score correction, normalised."""
    if cov > 0:
        c = min(cov, 0.9 * min(lh, la))
        p = np.zeros((G, G))
        for z in range(G):
            wz = poisson.pmf(z, c)
            if wz < 1e-9:
                break
            ph = poisson.pmf(GRID[: G - z], lh - c)
            pa = poisson.pmf(GRID[: G - z], la - c)
            p[z:, z:] += wz * np.outer(ph, pa)
    else:
        p = np.outer(poisson.pmf(GRID, lh), poisson.pmf(GRID, la))
    p[0, 0] *= 1 - lh * la * rho
    p[0, 1] *= 1 + lh * rho
    p[1, 0] *= 1 + la * rho
    p[1, 1] *= 1 - rho
    return p / p.sum()


def markets(p):
    """Probabilities of every scored market from one matrix: [home, draw, away], over lines, btts, team lines."""
    out = {"res": np.array([np.tril(p, -1).sum(), np.trace(p), np.triu(p, 1).sum()])}
    for k in OVER_LINES:
        out[f"over{k}"] = p[TOTAL > k].sum()
    out["btts"] = p[1:, 1:].sum()
    for k in TEAM_LINES:
        out[f"home{k}"] = p[int(k + 0.5):, :].sum()
        out[f"away{k}"] = p[:, int(k + 0.5):].sum()
    return out


def actuals(df):
    y = {"res": np.where(df.ft_home > df.ft_away, 0, np.where(df.ft_home == df.ft_away, 1, 2))}
    for k in OVER_LINES:
        y[f"over{k}"] = (df.ft_home + df.ft_away > k).astype(int).to_numpy()
    y["btts"] = ((df.ft_home > 0) & (df.ft_away > 0)).astype(int).to_numpy()
    for k in TEAM_LINES:
        y[f"home{k}"] = (df.ft_home > k).astype(int).to_numpy()
        y[f"away{k}"] = (df.ft_away > k).astype(int).to_numpy()
    return y


def price(df, lh, la, cov=0.0):
    rows = [markets(matrix(a, b, r, cov)) for a, b, r in zip(lh, la, df.rho, strict=True)]
    return {k: np.array([r[k] for r in rows]) for k in rows[0]}


def ll(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    if p.ndim == 2:
        return float(-np.log(p[np.arange(len(y)), y]).mean())
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def compress(df, beta):
    k = np.exp((beta - 1.0) * (np.log(df.raw_h + df.raw_a) - df.ref_log_total))
    return (df.raw_h * k).to_numpy(), (df.raw_a * k).to_numpy()


def recalibrate(p, a, b):
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return 1 / (1 + np.exp(-(a + b * np.log(q / (1 - q)))))


def platt(p, y):
    """Fit logit(q) = a + b logit(p) on the tuning seasons."""
    x = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    f = lambda t: ll(1 / (1 + np.exp(-(t[0] + t[1] * x))), y)
    return minimize(f, [0.0, 1.0], method="Nelder-Mead").x


def main() -> None:
    df = pd.concat([pd.read_pickle(f"data/processed/lambdas_{lg}.pkl") for lg in LEAGUES], ignore_index=True)
    df = df.sort_values("match_date").reset_index(drop=True)
    tune = df[df.season.between(*TUNE)].reset_index(drop=True)
    test = df[df.season.between(*TEST)].reset_index(drop=True)
    print(f"matches: tune {len(tune):,}, test {len(test):,}")
    y_t, y_s = actuals(tune), actuals(test)
    keys = list(y_t)

    def score(part, y, lh, la, cov=0.0):
        pr = price(part, lh, la, cov)
        return {k: ll(pr[k], y[k]) for k in keys}, pr

    variants = {"baseline (production)": (lambda d: (d.lam_h.to_numpy(), d.lam_a.to_numpy()), 0.0)}
    for b in (0.5, 0.6, 0.8, 0.9, 1.0):
        variants[f"beta {b}"] = ((lambda d, b=b: compress(d, b)), 0.0)
    for s in (0.97, 1.03, 1.06):
        variants[f"scale x{s}"] = ((lambda d, s=s: (d.lam_h.to_numpy() * s, d.lam_a.to_numpy() * s)), 0.0)
    for c in (0.03, 0.06, 0.10):
        variants[f"bivariate c={c}"] = ((lambda d: (d.lam_h.to_numpy(), d.lam_a.to_numpy())), c)

    # per-league scale fitted on the tuning seasons (actual total goals / expected total goals)
    ratio = (tune.assign(a=tune.ft_home + tune.ft_away, e=tune.lam_h + tune.lam_a).groupby("league").agg(a=("a", "sum"), e=("e", "sum")))
    ratio = (ratio.a / ratio.e).to_dict()
    print("per-league total scale (tuning seasons):", {k: round(v, 3) for k, v in ratio.items()})
    variants["per-league scale"] = ((lambda d: (d.lam_h.to_numpy() * d.league.map(ratio).to_numpy(), d.lam_a.to_numpy() * d.league.map(ratio).to_numpy())), 0.0)

    rows = []
    cache = {}
    for name, (fn, cov) in variants.items():
        res_t, pr_t = score(tune, y_t, *fn(tune), cov)
        res_s, pr_s = score(test, y_s, *fn(test), cov)
        cache[name] = (pr_t, pr_s)
        rows.append({"variant": name, "part": "tune", **res_t})
        rows.append({"variant": name, "part": "test", **res_s})
        print(f"done {name}", flush=True)

    # logistic recalibration of the baseline's binary markets, fitted on tune, applied to test
    pr_t, pr_s = cache["baseline (production)"]
    rec_t, rec_s = {"res": ll(pr_t["res"], y_t["res"])}, {"res": ll(pr_s["res"], y_s["res"])}
    for k in keys[1:]:
        a, b = platt(pr_t[k], y_t[k])
        rec_t[k], rec_s[k] = ll(recalibrate(pr_t[k], a, b), y_t[k]), ll(recalibrate(pr_s[k], a, b), y_s[k])
    rows.append({"variant": "logistic recalibration (post-hoc)", "part": "tune", **rec_t})
    rows.append({"variant": "logistic recalibration (post-hoc)", "part": "test", **rec_s})

    out = pd.DataFrame(rows)
    out.to_csv("data/processed/improve_totals.csv", index=False)
    pd.set_option("display.width", 250)
    for part in ("tune", "test"):
        t = out[out.part == part].drop(columns="part").set_index("variant")
        print(f"\n=== {part} seasons: log loss (lower is better) ===")
        print(t.round(5).to_string())
        print("\ndifference from baseline (negative = better):")
        print((t - t.loc["baseline (production)"]).round(5).to_string())

    # calibration of the production over 2.5 in bands, test seasons
    p, y = pr_s["over2.5"], y_s["over2.5"]
    print("\nbaseline over 2.5 on the test seasons, by predicted band:")
    for lo, hi in ((0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, 1)):
        sel = (p >= lo) & (p < hi)
        print(f"  {lo:.2f}-{hi:.2f}: n={int(sel.sum()):5d} predicted {p[sel].mean():.3f} happened {y[sel].mean():.3f}")


if __name__ == "__main__":
    main()
