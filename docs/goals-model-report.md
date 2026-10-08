# Goals model report: Dixon-Coles, Premier League

Generated 2026-10-08 from `scripts/tune_goals.py` and `scripts/backtest_goals.py`. Raw numbers: `data/processed/tune_goals.csv`, `backtest_goals_epl_summary.csv`, `backtest_goals_epl_predictions.csv`.

## Model

Dixon-Coles: each team has an attack and a defence strength, estimated together, so a result against a strong opponent counts for more than the same result against a weak one. Matches decay with a half-life, and a ridge penalty pulls every team toward the league average, which protects teams with little history. Only matches strictly before the prediction date are used (tested: changing results after the cut-off changes nothing).

## Method (no leakage, no peeking)

- Training data starts in 2015/16. Each week the model is refit on everything before that week, then predicts that week's matches.
- Settings were chosen on **2019/20 to 2021/22 only**: half-life 730 days, ridge 2. The tuning grid was flat between half-lives of 365 and 730 days.
- Settings were then **frozen** and evaluated once on **2022/23 to 2026/27 (to 20 Sep)**: 1,570 matches the tuning never saw.
- Baselines: the league base rate (expanding window) and the bookmaker's market-average closing odds with the margin removed. Odds are used for comparison only, never as a model input.

## Results on the held-out matches

Lower is better for log loss and RPS.

| Market | Model | League base rate | Bookmaker closing odds |
|---|---|---|---|
| 1X2 log loss | **0.9955** | 1.0691 | 0.9633 |
| 1X2 ranked probability score | 0.2059 | n/a | 0.1951 |
| 1X2 picked the right result | 51.7% | n/a | 54.8% |
| Over/under 2.5 log loss | 0.6813 | 0.6859 | 0.6692 |
| Both teams to score log loss | 0.6881 | 0.6896 | not available |

By season (1X2 log loss, model vs bookmaker): 2022/23 1.007 vs 0.962; 2023/24 0.927 vs 0.901; 2024/25 1.010 vs 0.967; 2025/26 1.032 vs 1.012; 2026/27 (50 matches) 1.041 vs 1.055.

## What this says

1. **The match result is predicted well above chance.** The model is far better than the base rate and its probabilities are well calibrated: when it says 60% for a home win, it happens about 60% of the time (buckets from 20% to 70% are all within a few points).
2. **The bookmaker is still better.** It is about 0.03 log loss ahead on the result and about 3 points ahead on picking the right result. This is expected: the market also knows team news, injuries, lineups and money flow, and this model knows only past scores. The gap closed to nothing in the first 50 matches of 2026/27, but that sample is far too small to read anything into.
3. **Over/under 2.5 and both teams to score are barely better than guessing the base rate.** Goals totals are mostly noise given only past scorelines. These markets should get the **Low confidence** tier until a better model beats the base rate clearly.
4. **The model underrates high-scoring games a little.** Where it says 41% for over 2.5, it happened 47% of the time. Where it says 50%, it happened 55%. There is room to fix this, for example with xG or a better total-goals model.
5. **Promoted and unseen teams are rare** (4 of 1,570 matches had a team with no history in the window), so there is too little to judge how well the model handles them.

## Not yet tested

- Other leagues (Phase 1b).
- Half-time scores, timing of goals, and everything in the other market families.
- Whether the model's edge over the base rate survives different eras. The four test seasons are all post-2022.

## Next improvements, in order of likely value

1. Use expected goals (Understat history) as an extra signal. Real goals are noisy; xG is a steadier measure of team strength.
2. A prior for newly promoted teams instead of the league average.
3. Separate home and away strengths, and a total-goals adjustment to fix the over/under bias.
4. Only after those: consider whether adding the market odds as a model input is acceptable. It would likely close the gap on the result but would make the product a repackaging of the bookmaker's own view. This needs HEO's decision, since BUILD.md currently says odds are not an input.

## Other leagues (Phase 1b)

The same model with the same frozen settings (half-life 730 days, ridge 2, tuned on the Premier League only) was run
unchanged on the other four leagues, over the same seasons 2022/23 to Sep 2026. `scripts/backtest_goals.py <LEAGUE>`
reproduces each row; raw numbers are in `data/processed/backtest_goals_<league>_summary.csv`.

| League | Matches | 1X2 log loss: model | league base rate | bookmaker | Right result: model / bookmaker | Over/under 2.5 log loss: model / base | Both teams to score: model / base |
|---|---|---|---|---|---|---|---|
| Premier League | 1570 | 0.9955 | 1.0691 | 0.9633 | 51.7% / 54.8% | 0.6813 / 0.6859 | 0.6881 / 0.6896 |
| La Liga | 1589 | 0.9752 | 1.0625 | 0.9584 | 53.2% / 55.0% | 0.6733 / 0.6928 | 0.6872 / 0.6922 |
| Bundesliga | 1260 | 0.9918 | 1.0726 | 0.9695 | 51.4% / 54.8% | 0.6539 / 0.6659 | 0.6682 / 0.6745 |
| Serie A | 1570 | 0.9846 | 1.0864 | 0.9670 | 52.7% / 53.9% | 0.6928 / 0.6992 | 0.6937 / 0.6974 |
| Ligue 1 | 1343 | 0.9986 | 1.0716 | 0.9799 | 52.0% / 53.6% | 0.6824 / 0.6927 | 0.6899 / 0.6908 |

What this says:

1. **The model works in every league.** It beats the base rate on the match result in all five, by a similar margin,
   without any per-league tuning.
2. **The gap to the bookmaker is similar everywhere** (about 0.017 to 0.032 log loss), and smallest in La Liga, Serie A
   and Ligue 1. The Premier League is the league where the market is furthest ahead of this model.
3. **Over/under 2.5 and both teams to score are better than the base rate in La Liga and the Bundesliga**, and only
   marginally so in the other three.
4. Tuning per league, or fitting one pooled model with league effects, is untested and may help the smaller leagues.
