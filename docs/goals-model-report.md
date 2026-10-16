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

## Half-time model (Phase 2, first step)

Each goal falls in the first half independently with probability `p1`, so the half-time score and the second-half score
follow exactly from the full-time scoreline matrix (`src/pitchside/models/halves.py`; it reproduces the exact Poisson
identities in `tests/test_halves.py`). `p1` was estimated on 2015/16 to 2021/22 only and frozen. The goals model is
refit weekly on past matches only, and everything is scored on 2022/23 to Sep 2026 against league base rates
(`scripts/backtest_halves.py <LEAGUE>`). Log loss, lower is better; model / base rate:

| League | p1 | Half-time result | Second-half result | HT/FT (9 outcomes) |
|---|---|---|---|---|
| Premier League | 0.447 | 1.0507 / 1.0855 | 1.0636 / 1.0970 | 1.9068 / 1.9839 |
| La Liga | 0.434 | 1.0292 / 1.0618 | 1.0391 / 1.0902 | 1.8742 / 1.9595 |
| Bundesliga | 0.436 | 1.0362 / 1.0941 | 1.0552 / 1.0918 | 1.8572 / 1.9492 |
| Serie A | 0.435 | 1.0309 / 1.0802 | 1.0378 / 1.0947 | 1.8793 / 1.9854 |
| Ligue 1 | 0.437 | 1.0494 / 1.0901 | 1.0527 / 1.0916 | 1.8719 / 1.9497 |

What this says:

1. **The split model works in every league**: it beats the base rate on all three, by a similar margin everywhere. The
   share of goals before half-time is stable at 43% to 45%.
2. **Over/under on half-time goals is only marginally better than the base rate** (Ligue 1 half-time over 0.5 is slightly
   worse). The model also under-predicts "at least one first-half goal" in four of five leagues (for example Premier
   League 71.7% predicted against 73.9% actual), the same low-scoring bias seen at full time.
3. **Real football has more comebacks than independent goals allow.** In the Premier League, a team leading at half-time
   goes on to lose 3.0% of the time against 2.0% predicted, and a team behind at half-time goes on to win 3.2% against 2.4%.
   That is the game-state effect (trailing sides push, leading sides sit back). It matters for HT/FT, "win from
   behind", "lead by N at any time" and "1UP". The simulator's game-state layer exists to fix this, and the fix has to
   be judged against these numbers.

## Match simulator (Phase 2): families B to E

The simulator samples a full-time score from the goals model, splits it into halves with the **empirical half-time table**
(real P(half-time score | full-time score) from 12,679 matches, 2015 to 2021, five leagues pooled), and places each goal in
its half with a **goal-timing profile** fitted on 9,998 verified goals from 2023 and 2024. Family A prices stay exactly the
goals model's; families B to E (142 markets, 705 selections per match) come from the simulated matches.

**Empirical half-time table versus the simple independent split** (held-out 2022/23 onwards, `scripts/backtest_halves.py`).
The table moves the predicted comeback frequencies toward the real ones, but the log-loss gain is small and not uniform:
HT/FT (9-way) improves by 0.002 to 0.003 in the Premier League, La Liga and Serie A and is unchanged in the Bundesliga and
Ligue 1. Some under-prediction of comebacks remains (Premier League: a team leading at half-time loses 2.4% of matches
predicted against 3.0% actual). It is never materially worse, so it is used.

**Held-out validation of the whole simulator** (`scripts/backtest_sim.py`). Goal-timing profile fitted on seasons up to 2024,
half-time table on seasons up to 2021, goals model refit weekly on earlier matches, and 500 randomly chosen verified matches
from 2025/26 and 2026/27 scored. Each selection is compared with the base rate (how often it happened in the 2023 and 2024
verified matches). Skill is the share of the base-rate log loss removed.

| Family | Selections | Model log loss | Base-rate log loss | Skill |
|---|---|---|---|---|
| B. Halves | 211 | 0.4941 | 0.5129 | +3.7% |
| C. Game flow | 52 | 0.4834 | 0.5161 | +6.3% |
| D. Minutes tab | 161 | 0.4602 | 0.4718 | +2.5% |
| E. Combinations | 281 | 0.3613 | 0.3727 | +3.0% |

**Calibration is very good**: over about 330,000 priced selections, the average predicted probability is within about one
percentage point of the actual frequency in every bucket from 0-2% to 98-100% (for example, selections priced at 70 to 80%
happened 75.5% of the time; those priced at 2 to 5% happened 3.7% of the time).

What this says:

1. **The simulator's probabilities can be taken at face value.** They are well calibrated across the whole range, including the
   long shots that dominate the combination and exact-score style markets.
2. **It adds information over the base rate in every family, but not much in the pure-timing markets.** The clearest gains are
   in the markets that depend on which team is stronger (leading by N, winning either or both halves, goals in a row, half-time
   draw-no-bet and handicaps, +8% to +13%). Markets that depend mainly on the *amount* of scoring and its timing (first-goal
   interval, goals in the first 5 to 25 minutes, first-half odd/even) are within a fraction of a percent of the base rate.
   That is expected: nothing in the model says when a particular match will be early or late.
3. **No market is materially worse than the base rate.** The worst is away team to win from behind (-1.4%, on very few
   events), then a handful within a few tenths of a percent.
4. **Limits.** 500 matches is a sample, so a single market's skill number is noisy and only the family-level and the
   calibration results are firm. The goal-timing profile is one pooled distribution for all teams and leagues; a team that
   scores early or late more than average is not modelled.

## Following the recent scoring level (model 0.3.0)

The 0.2.0 model slightly under-predicted goals: over 5 test seasons, 52.1% predicted for over 2.5 against 53.7% actual,
worst in 2026/27 (52.5% against 58.8%). Team strengths move slowly (half-life 730 days) but the league's scoring level moves faster,
so 0.3.0 shifts the league goal level by the ratio of goals actually scored to goals expected over the last 240 days, shrunk toward no change
by n / (n + 60). Both numbers were chosen on 2019/20-2021/22 across the five leagues (`scripts/tune_level.py`), then run once on the
held-out seasons (`scripts/tune_level.py --test`):

| Held-out 2022-2026, five leagues | 0.2.0 | 0.3.0 |
|---|---|---|
| Over/under 2.5 log loss | 0.6774 | 0.6767 |
| Both teams to score log loss | 0.6861 | 0.6852 |
| 1X2 log loss | 0.9881 | 0.9881 |
| Average predicted over 2.5 (actual 53.67%) | 52.05% | 52.43% |

The gain is real but small, and it closes only about a quarter of the gap. The first live week (47 matches, 54% predicted against 72% actual) is far
bigger than this bias and is mostly small-sample variation.

## Form, head-to-head and the low end of over/under (still model 0.3.0, not yet used live)

All three were tuned on 2019/20-2021/22 (five leagues pooled) and run once on 2022/23 onwards.

**Recent form** (goals scored and conceded in a team's last 5-20 matches against what the fitted model expected, shrunk toward zero) and
**head-to-head** (the same residual over the pair's meetings in the last 6-10 years) were both tried at several shrink strengths
(`scripts/tune_signals.py`, `src/pitchside/models/signals.py`). On the tuning seasons every setting that moved predictions made the match result
worse (1X2 log loss +0.0015 to +0.028); the heaviest shrinkage only converged back to the baseline. Held-out, the best form setting (last 10 matches,
shrink 100) improved 1X2 log loss by 0.0016 (0.98813 to 0.98658) and left over/under and BTTS flat; head-to-head changed nothing (0.98815).
Neither is shipped: the form gain is below what could be luck, and the model already has its two-year memory. They stay in the repo, tested,
for revisiting when player and lineup data exists.

**Negative binomial goals** (extra spread for the same mean) hardly moved over/under and made BTTS worse, and did not repair the low band, so goal
variability was not the cause (`dispersion` option, off).

**Total-goals compression** was. The model's expected totals were too extreme: where it expected few goals, more happened; where it expected many, fewer.
Each match's expected total is now pulled toward the league's typical total (exponent 0.7, ratio between the two teams kept). Tuned on 2019-2021
(`scripts/tune_totals.py`), then run once on 2022-2026:

| Held-out 2022-2026 | without | with (0.7) |
|---|---|---|
| Over/under 2.5 log loss | 0.67669 | 0.67605 |
| Both teams to score log loss | 0.68519 | 0.68441 |
| 1X2 log loss | 0.98813 | 0.98842 |
| Over 2.5 predicted below 40%: predicted / actual | 35.7% / 41.4% | 37.2% / 40.0% |

Small gains on over/under and BTTS, a negligible 0.0003 loss on the match result. The simulator test (500 held-out matches) stays calibrated
within about a point and the skill over the base rate is now B +3.8%, C +6.5%, D +2.0%, E +3.5% (was +3.7, +6.3, +2.5, +3.0).

## Recent hit rates per market (last 5, 10 and 15 matches)

Tested on the 7,300 held-out matches of the goals backtest with `scripts/test_recent_hit_rates.py`: each team's hit rate over its previous N matches for home win,
draw, away win, over 2.5 goals and both teams to score (log loss, lower is better; model fitted on the earlier 60% by date and scored on the later 40%).

- **On its own, a recent hit rate is a poor predictor.** Using "how often has this happened in the last N" as the probability scores worse than the model for every market
  (for example over 2.5: 0.689 to 0.738 against the model's 0.679) and, for over 2.5 and both teams to score over the last 5 matches, worse than a coin flip (0.693).
- **Added to the model it helps very little.** The gain is 0.0001 to 0.0022 log loss (at most 0.4%). Home win gains most with 15 matches (0.6155 to 0.6134); draw, over 2.5
  and both teams to score gain nothing worth keeping. The model already counts those same matches, with recent ones weighted more.
- This agrees with the earlier form test (`scripts/tune_signals.py`): short windows add noise.

## Against the bookmakers' prices, and would the gaps have paid (`scripts/backtest_value.py`)

Model 0.3.0 settings, walk-forward over 7,379 matches (2022/23 to 2026/27, five leagues), against football-data.co.uk opening and closing prices (match result and over/under 2.5).

- **Information.** The bookmakers' own probabilities beat the model everywhere (match result log loss at opening prices 0.9733 against 0.9908; over/under 2.5 0.6715 against 0.6776). A blend
  of both did not beat the bookmakers by more than 0.0007: the model adds essentially nothing the price does not already contain.
- **Betting.** Backing every selection returned -6.5% per unit at the average price and -2.6% at the best opening price. Backing only selections where our probability was at least 5 points above
  the bookmakers' returned -8.7% at the best opening price (5,535 bets, ±3.8%), and the bigger the gap the worse it did (12 points: -10.9%, ±11%). The only positive groups are tiny
  (High-confidence bets with 8+ points of gap: 109 bets, +13.5% ±54%) and not distinguishable from luck.
- **Reading.** Where we disagree with the bookmakers it has usually been our number that was wrong. The comparison on the match page is information; it should not be sold as a way to find winning bets.

## Fitting to expected goals as well as goals (`scripts/tune_xg.py`, not adopted)

Team ratings can be fitted to a blend of real goals and expected goals (Understat xG, 2014/15 onward, `scripts/pull_understat_xg.py`): target = (1 - w) goals + w xG, with the
low-score correction still on real goals (`xg_weight` in `DixonColes`). Tuned on 2019/20-2021/22, then run once on 2022/23 onwards (five leagues, weekly refits, 0.3.0 settings otherwise).

| Held-out 2022-2026 | goals only | w = 0.5 |
|---|---|---|
| 1X2 log loss | 0.98842 | 0.98798 |
| Over/under 2.5 log loss | 0.67605 | 0.67575 |
| Both teams to score log loss | 0.68441 | 0.68346 |

Weight 0.5 was best on the tuning seasons for 1X2 and over/under (0.25 and 0.75 were close; 1.0 was worse than goals alone). The gains are positive on all three markets but small (0.04% on the match
result, about 0.1% on both teams to score), well below the gap to the bookmakers. Shipping it would need a daily xG feed, a new model version and a full rebuild of the confidence ratings, so it is left
in the code, tested and switched off. Where it should matter more is clubs with little history (promoted sides), which is the next thing to test.

## Corners, cards, shots and shots on target (Phase 3, `scripts/tune_counts.py`, `scripts/backtest_counts.py`)

Each statistic has its own count model: attack and defence rates per club with a home advantage, older matches counting less, and a negative binomial spread estimated from the data
(`src/pitchside/models/counts.py`). Memory and shrinkage were chosen on 2019/20-2021/22 only (a 365-day half-life and shrinkage 16 for all four; heavier shrinkage than goals,
because these counts are noisier per club), then frozen. Priced markets: over/under for the match and each team, which team has more, a handicap, and odd/even and ranges for corners and cards.

Held-out 2022/23 to 2026/27, 3,000 random matches, later half scored against how often each selection usually happens (log loss; positive skill is better):

| Statistic | Skill over the usual frequency |
|---|---|
| Corners | +3.6% |
| Cards (yellow plus red) | +2.6% |
| Shots | +9.3% |
| Shots on target | +7.4% |

Calibration is close in every probability band for cards and shots on target; corners and shots are slightly overconfident in the tails (a prediction of about 85% happened about 83%),
which the confidence ratings pick up. Highest skill is on team counts and handicaps (shots handicap +12.8%); odd/even markets carry no information (+0.0% to +0.1%) and are rated Low. Corners over/under on the
match total is the weakest of the main markets (+1.6%). Confidence ratings for families F to H come from the same rule as the others and held out in the same order
(High 8.3%, Medium 3.5%, Low 1.2% overall; in each of F, G and H High beat Medium beat Low).

## Newly promoted clubs (`scripts/analyse_promoted.py`)

The goals model shrinks a club with little history toward the league average. If promoted sides are really weaker, their goals scored should come in below the model's expectation and goals conceded above it.
Held-out (2022/23 onwards, 13,000 team-matches), by how many matches the club had played in the league in the previous three years:

| Matches in last 3 years | Team-matches | Scored: actual - expected | Conceded: actual - expected |
|---|---|---|---|
| under 15 (promoted) | 438 | -0.050 (±0.05) | -0.016 |
| 15 to 39 | 886 | +0.033 (±0.04) | +0.014 |
| 40 to 79 | 2,056 | +0.014 (±0.02) | +0.009 |
| 80 or more | 11,378 | +0.014 (±0.01) | +0.016 |

No clear bias: the promoted group is within about one standard error of zero on both, so no special prior for promoted clubs is needed and none was added.

## Player markets (experimental; `scripts/backtest_players.py`, `scripts/backtest_player_counts.py`)

Understat shot events (2023/24 onward, 142,000 shots) give each player's recent share of his club's goals, shots, shots on target and assists. No lineup is used (lineups are published about an hour before kickoff;
the daily job runs days ahead), so a player's recent share carries availability with it. For a coming match the club's expected goals come from the goals model and the player takes his share of them:
P(scores) = 1 - exp(-club expected goals x share), where the share is the player's share of the club's xG over its last 45 matches (memory of 14 matches). Settings were chosen on matches before 2026-01-01
and scored on matches from 2026 onward (about 52,000 player-matches).

| Held-out | Result |
|---|---|
| Anytime goalscorer log loss | 0.1885, 10.9% better than giving every player the same chance (0.2115) and far better than a player's raw recent scoring rate (0.2556) |
| Shots over 0.5 / 1.5 / 2.5 | skill over the same chance +9.3% / +10.9% / +11.6% |
| Shots on target over 0.5 / 1.5 | +8.6% / +11.2% |
| Anytime assist | +2.5% (weak) |

Calibration is close for ordinary players; the very likely scorers (30-40% predicted) scored more often than predicted (42% against 33%). Rotation, injuries and suspensions are unknown, which is why the whole family is labelled experimental
and why a player who did not play is settled as a loss. Confidence ratings for family I come from the same rule as the others.

## Rating clubs across leagues (tested, not adopted)

A club that changes league is rated, in the single-league model, only on its matches in the new league. `models/pyramid.py` fits the Premier League and the Championship together instead: each club has one attack and one defence rating, and the leagues differ by the average rating of their clubs (fitted from the clubs that moved). Walk-forward from 2022/23, production 0.3.0 settings, 14-day refits (`scripts/backtest_pyramid.py`), match-result log loss, lower is better:

| Matches | Single league | Across leagues | Difference (t) |
|---|---|---|---|
| Championship, all (2,316) | 1.0539 | 1.0523 | -0.0017 (-1.1) |
| Championship, a club that came down from the Premier League (318) | 1.0279 | 1.0102 | -0.0177 (-2.0) |
| Premier League, all (1,580) | 0.9960 | 1.0015 | +0.0055 (+2.3) |
| Premier League, a club that came up (306) | 0.9263 | 0.9447 | +0.0184 (+1.9) |

So carrying a rating down a league helps a little, but carrying it up hurts: one league-average gap does not fit both directions (promoted clubs are rated too highly), and the Championship gain is not consistent from season to season (worse in 2024/25). Not adopted: production keeps one fit per league. It is the starting point for the Champions League and Europa League, where clubs from many leagues meet.
