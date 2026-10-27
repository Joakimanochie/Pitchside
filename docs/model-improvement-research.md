# Model improvement research (2026-10-27)

Goal of the product: for every market of a match, a probability that is **calibrated** (when it says 70%, about 70% happen) and **informative** (it separates likely from unlikely
better than the usual rate). Each probability is stored before kickoff and scored after the match. Bookmaker prices are not part of that goal. They are a yardstick: the best
public estimate of the same probabilities, so the distance to them shows how much room there is.

Everything below was run on the repo's own data with the walk-forward harness (the model is refitted every 14 days on matches before the block and scored on the block; five leagues,
2019/20 to 2026/27; settings are chosen on 2019/20 to 2021/22 and scored on 2022/23 onward). The cached expected goals come from `scripts/cache_lambdas.py`.

## 1. Where the model stands (goals model 0.3.0, 7,379 matches, 2022/23 to 2026/27)
| Measure (log loss, lower is better) | Model | League base rate | Bookmaker closing |
|---|---|---|---|
| Match result | 0.9955 | 1.0691 | 0.9633 |
| Over/under 2.5 | 0.6813 | 0.6859 | 0.6692 |
| Both teams to score | 0.6881 | 0.6896 | no data |

It beats the base rate and its probabilities are calibrated (section 2). It trails the bookmaker by about 0.03 on the result, and a blend of the two beat the bookmaker by at most 0.0007,
so the model adds almost nothing the price does not already contain. The model knows only past scores; the market also knows lineups, injuries, suspensions and money flow.

## 2. Can the model give "winning picks" at 90 to 95% confidence? (`scripts/confidence_ceiling.py`)
A probability is a statement about how often something happens, so it cannot be raised by wanting it higher: if the model said 95% for something that happens 70% of the time it would be wrong.
More data helps only by making the number closer to the truth. What the held-out seasons show (7,478 matches, 224,340 priced selections in markets betting sites widely list):

| Model said | Selections | Happened | Matches with at least one |
|---|---|---|---|
| 50 to 60% | 25,284 | 55.2% | 100% |
| 60 to 70% | 21,635 | 65.3% | 95% |
| 70 to 80% | 30,256 | 75.4% | 99.7% |
| 80 to 90% | 21,854 | 85.3% | 99.9% |
| 90 to 95% | 10,676 | 93.0% | 92% |
| 95 to 100% | 2,465 | 95.9% | 28.5% |

- **The model is honest at the top.** When it says 90 to 95%, it happens 93% of the time; when it says 95% or more, 95.9%. So 90%+ picks exist today and they do win about 93 to 96% of the time.
- **But they are the obvious ones.** Of the 13,141 selections at 90% or more, 6,672 are "over 0.5 goals" (happens 94.4%), then "away team under 2.5 goals" (2,913), "home team under 2.5 goals" (1,216) and "under 4.5 goals" (1,188). Only 399 are "home or draw", and 2 are a plain home win.
  These are safe because they are nearly always true, which is also why a betting site pays about 1.05 to 1.10 for them.
- **The picks people mean (who wins) cannot reach 90%.** The most likely match result is right 52.4% of the time. When the model's top result was 60% or more (22.9% of matches) it was right 72.1%;
  at 70% or more (7.7% of matches) it was right 79.0%. Football results are mostly luck: even the bookmakers, who know everything public, only lower the result's log loss from 1.069 (base rate) to 0.963.
- **So the way to "winning picks" is selection, not a higher number**: show only selections above a chosen probability, say so, and keep scoring them. That is already what the confidence bars and the Odds tab do.
  Combining safe picks multiplies the chances: 5 picks at 93% win together 70% of the time, at fair odds of about 1.4.
- **Accuracy is not profit.** A 93% pick paid at 1.07 is a loss over time if it really happens 93% of the time, once the bookmaker's margin is taken (about 5% to 7%). Backing our numbers against the bookmakers' prices lost 2.6% to 8.7% per unit in the backtest.

## 3. Results of the three planned steps (all scored on 2022/23 onward unless stated)

### Step 1: totals calibration (`scripts/improve_totals.py`): no change adopted
The 0.3.0 total-goals compression already fixed the large bias. What is left is small: over 2.5 predicted 41.6% happens 42.5%, predicted 59.2% happens 60.3% (about one point too low everywhere).
Tested against the production settings, log loss difference (negative is better):

| Variant | Result | Over 2.5 | Both teams score | Reading |
|---|---|---|---|---|
| compression 0.8 | -0.0001 | -0.0001 | +0.0001 | same |
| compression 1.0 (none) | -0.0003 | +0.0006 | +0.0007 | worse for goals markets |
| scale all expected goals x1.03 | +0.0001 | -0.0001 | -0.0005 | mixed |
| per-league scale | 0.0000 | -0.0001 | 0.0000 | same |
| bivariate Poisson (shared goals part) 0.06 | -0.0004 | +0.0002 | -0.0003 | helps result and both-score, hurts over 0.5 and 1.5 |
| logistic recalibration of every probability (upper bound) | 0.0000 | -0.0002 | -0.0010 | best case 0.15% on both teams to score |

Nothing beats the baseline by more than the noise, and the best-case post-hoc fix is 0.0010. The totals are at what this information can give. Negative binomial spread was tested earlier and also rejected.

### Step 2: rest days and congestion (`scripts/improve_rest.py`): rejected
Short rest (3 days or fewer, 4 days, 5 to 6 days), a previous European match and a European match within 4 days, for the team and its opponent, from every finished match in the database.
Poisson regression fitted on 2019/20 to 2021/22: every coefficient is within 1.4 standard errors of zero (largest: opponent on 4 days' rest +4.7% on scoring, z +1.4). On the test seasons the changes in log loss are between -0.0003 and +0.0002. No effect worth adding.

### Step 3: lineups, an upper bound (`scripts/improve_lineups.py`): not supported, so live injury news is not worth chasing yet
Using the real starting XIs of finished matches (ESPN) and each player's share of his club's chances (Understat xG plus assisted xG over the previous 45 matches), the question was how much
perfect knowledge of the attacking XI would help. 4,363 matches had a usable signal for both teams (2023/24 onward).
- Fitted on 2024/25: a weaker-than-usual XI cuts expected goals, effect +0.30 per unit (z +3.2), about -5% for a one standard deviation weaker XI.
- It did not hold: fitted on 2025/26 onward the effect is +0.03 (z +0.3), and applying the 2024/25 effect to the test seasons made log loss slightly worse on every market (+0.0001 on the result, up to +0.004 on over 4.5).
- Limits: this measures the attacking XI only (defenders and goalkeepers carry no chance share), with a crude value measure, and the lineup is known in hindsight. It does not prove that specific news (a star striker or the first-choice goalkeeper out) is worthless.
  It does show that a generic "how strong is today's XI" signal is not a reliable gain, so spending effort on a live injury feed is not justified on this evidence.

## 4. What is left, and what would change the picture
| Idea | Status |
|---|---|
| Form, head-to-head, recent hit rates | tested earlier, near zero |
| Expected goals blended into the fit | tested earlier, +0.04% on the result, built, off |
| Totals calibration, bivariate goals, per-league scale | tested now, no gain |
| Rest days, congestion, European weeks | tested now, no effect |
| Lineups (attack, hindsight upper bound) | tested now, unstable, not a reliable gain |
| Defence and goalkeeper availability | not measured |
| Market prices as an input (decision for HEO) | not built. The only tested route that closes the 0.03 gap, because the price already contains team news and money flow |
| Squad market value (Transfermarkt) | not tested; terms of automated access unchecked (unverified) |
| Referee data for cards outside the Premier League | no source found |

Honest reading: on the information we have, the model is close to what a goals-only model can do. The remaining gap to the bookmakers is team news and money flow, and the tests above found no cheap way to buy it.
Published work points the same way: a model-plus-odds blend puts most of the weight on the odds ([an open Dixon-Coles, Elo and odds blend](https://github.com/hediblk/football-predictions) uses 0.35, 0.55 and 0.10),
and a recent paper anchors totals to over/under prices ([arXiv 2605.16066](https://arxiv.org/pdf/2605.16066)). Neither is evidence about our model; they show where others got the gain.

## 5. Decisions for HEO
1. **Market prices as a model input**: none (today); only the over/under prices to set the expected total; or a full blend. The full blend would very likely close most of the gap, but the output would then be mostly the bookmaker's number.
   It also needs a live price source (see `docs/odds-sources.md`).
2. **How to present high-confidence selections.** The data supports a "most likely today" list at 90%+ with its measured hit rate (93 to 96%), labelled plainly as near-certain markets with short prices. It does not support promising winners of matches.
3. **Whether to charge for slips.** On this evidence a subscription for "picks" would sell accuracy that the bookmaker's margin removes. The honest product is transparent, scored probabilities.

Sources for the web leads: [Boshnakov, Kharrat and McHale bivariate Weibull](https://salford-repository.worktribe.com/output/1395286/a-bivariate-weibull-count-model-for-forecasting-association-football-scores) (reported better over/under fit; not tested here),
[API-Football](https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports) and [PitchAPI](https://sportsapis.dev/apis/pitchapi) for injury and lineup data (free-tier limits and accuracy unverified).
