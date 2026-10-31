# Model performance and product roadmap

Review date: 2026-10-31

## What the current evidence says

The production result/goals engine is `goals-dc-0.3.0`: a domestic-league Dixon–Coles score model with a 730-day exponential half-life, ridge shrinkage, a 240-day scoring-level adjustment, and 0.7 total compression. Each forecast uses matches strictly before its `as_of` cutoff. That is a sensible, interpretable baseline and its time ordering is a strength.

The current walk-forward report evaluates 7,379 matches from 2022/23 onward. Result log loss is 0.9955 versus 1.0691 for a league base rate and 0.9633 for closing bookmaker probabilities. Over/under 2.5 is 0.6813 versus 0.6859 and 0.6692; BTTS is 0.6881 versus 0.6896. So the model beats a naive base rate, but the market remains stronger on the measured result and totals markets. The existing investigation also found that a basic blend with closing odds adds almost no skill, while tested rest, generic lineup strength and small totals recalibrations did not deliver a stable gain. See [`model-improvement-research.md`](model-improvement-research.md) for the experiment details and [`data-audit.md`](data-audit.md) for source coverage.

The goal should be **better calibrated probability forecasts and better measured selection performance**, not higher displayed probabilities. Historical slip hit rate is not evidence of a profitable product by itself: market price, margin, stake rules, correlated outcomes, and uncertainty in the estimated edge all matter. The current Odds page correctly says that its displayed prices are model fair odds and that past market-price betting lost in the backtest.

## Prioritized avenues to test

### 1. Make the evaluation journal the release gate

Keep every prediction frozen before kickoff and score every eligible prediction, including losses and abstentions in their proper denominators. Use rolling-origin folds by date (never random match splits), tune only in earlier seasons, then evaluate once on untouched later seasons. Report log loss and Brier score for binary markets, ranked probability score for 1X2, reliability plots by probability band, and uncertainty intervals clustered by matchweek/season. Compare against both league base rates and de-vigged closing prices on exactly the same matches. Track calibration and discrimination separately from hit rate and simulated return.

For betting claims, additionally record the actual offered price at decision time, closing price, market/line, bookmaker, timestamp, commission/margin, and settlement. Measure yield with confidence intervals and closing-line value; do not select thresholds on the final test period. Do not infer slip reliability by multiplying marginal probabilities if legs can share information or fixtures: estimate and audit whole-slip outcomes directly as well.

### 2. Add a time-aligned xG challenger, not a wholesale replacement

Historical goals are noisy measures of team strength. The data audit indicates Understat has historical xG for at least the Premier League, while football-data's xG fields begin only in 2026/27. First confirm season-by-season and league-by-league completeness, stable definitions, and collection timestamps. Build an xG-only or goals+xG challenger using only xG already observed before each forecast cutoff. Keep the current score model as the control; compare on the same matches and seasons. Fit any blend weight only inside the training fold and shrink it toward the score-only model when coverage is sparse. Do not backfill current xG values into historical seasons or treat future match xG as a pre-match feature.

Published work supports xG-driven score-rate forecasts as a plausible experiment, but not a guaranteed transfer of results: a 2026 Bundesliga study reports a rolling xG/Skellam model with isotonic calibration and also finds bookmaker forecasts better calibrated overall ([Wilkens, 2026](https://journals.sagepub.com/doi/full/10.1177/22150218261416681)). The Dixon–Coles framework itself motivates recency weighting because team performance changes over time ([Dixon & Coles, 1997](https://rss.onlinelibrary.wiley.com/doi/pdf/10.1111/1467-9876.00065)).

### 3. Treat market odds as a benchmark and a separate product mode

The observed gap to closing odds is the largest measured headroom. Collect a reliable, timestamped pre-match odds feed for the exact offered lines and markets. First use it to improve the benchmark and price-aware selection: remove bookmaker margin consistently, compare model probability to the offered price, and abstain when no positive expected value remains after margin and uncertainty. A market-anchored probability can be tested as a separately labelled forecast mode, but should not be presented as independent model skill. Fit any market blend weights on past seasons only, by league/market where sample size permits, and report performance against the market itself. Research finds bookmaker forecast quality varies by bookmaker and league, reinforcing the need to retain source and league detail ([Štrumbelj & Robnik Šikonja, 2010](https://www.sciencedirect.com/science/article/pii/S0169207009001733)).

### 4. Calibrate by market only when forward data supports it

The current confidence audit suggests aggregate high-probability bins are broadly honest, but that does not establish calibration for every market, league, line, or season. Test a small set of rolling calibration methods (for example, logistic/Platt calibration and isotonic regression) on prior out-of-fold forecasts. Require enough data per market, preserve mutually exclusive 1X2 probability sums, and compare against uncalibrated predictions on the next untouched period. Use a calibration layer only if its gain persists across multiple temporal folds; do not calibrate on the same forecasts used to fit the model.

### 5. Improve source coverage before adding fragile features

The data audit flags xG coverage differences across leagues, unverified Understat shot/player coverage outside the Premier League, ESPN as an undocumented API, WhoScored as fragile at scale, referee data limited to the Premier League, and no verified pre-lineup injury/suspension feed. The next data work should measure completeness, delay, correction rates, definition changes and provider outages by league and season. Only then test goalkeeper/defender availability or expected lineups with timestamped pre-match snapshots. The previous generic attacking-XI test was not predictive out of sample, so a live injury integration is not currently supported by evidence.

### 6. Separate market families and avoid assuming all slip legs are equal

The goals model, count model and experimental player model have different inputs and evidence. Maintain separate scorecards, calibration and release decisions by family and market. The odds slip currently selects the highest-probability offered outcome per match above an 80% floor, with one leg per match, then multiplies marginal probabilities to build target fair odds. That construction favors high hit probability, not value at the bookmaker's actual price. Keep the actual price and model probability side by side in any future slip workflow, surface the implied chance of the complete set, and allow a no-bet outcome when price/data quality is inadequate.

## Suggested next experiment sequence

1. Reproduce the baseline from frozen, pre-kickoff predictions and verify the market comparison uses the identical match set and de-vig method.
2. Produce a league/season coverage matrix for historical xG, including source timestamp and missingness. Start with the EPL if coverage is materially better there.
3. Run a temporal xG challenger and rolling calibration variants on fixed folds; publish per-season and pooled scores with uncertainty intervals.
4. Build an odds-input benchmark/decision layer only after reliable timestamped prices are available; freeze thresholds before the final holdout.
5. Rebuild the slip evaluation using actual offered prices, whole-slip settled results, and a predeclared selection/stake policy. Keep “most likely” and “value” picks as distinct user concepts.

## Product implications

No experiment can guarantee a higher win rate or profit. A higher hit rate can be achieved by selecting very short-priced outcomes, while expected returns can still be negative. Until the model demonstrates repeatable out-of-sample calibration and positive price-aware results with adequate uncertainty bounds, present it as a probability and research product, not a promise of winning bets. For the reasoning behind this distinction and the current slip record, see [`model-improvement-research.md`](model-improvement-research.md).
