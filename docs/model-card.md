# Model card: goals model 0.3.0 and confidence tiers

## What the model is
A Dixon-Coles goals model per league (attack and defence for every club, home advantage, time-decayed with a two-year half-life), with the league scoring
level followed over the last 240 days and each match's expected total pulled 30% toward the league's typical total. A simulator turns the scoreline
probabilities into half-time, game-flow, minute and combination markets. It uses past scores only: no lineups, injuries, form beyond the decay, or
head-to-head (both were tested and did not help, see `goals-model-report.md`). It trails the bookmakers' closing odds on the match result.

## What a confidence tier says
The bars rate how far a probability can be trusted. They are not the chance the outcome happens. For each market and probability band (under 10%, 10-25%,
25-40%, 40-60%, 60-75%, 75-90%, over 90%) we measured, on a held-out backtest:

- **skill**: 1 - model log loss / base-rate log loss, where the base rate is how often that exact selection usually happens;
- **gap**: average predicted probability minus how often it happened, judged against its own sampling error.

| Tier | Rule |
|---|---|
| High | at least 200 selections in the cell, skill of 5% or more, and the calibration gap within 3 points (plus sampling error) |
| Medium | at least 200 selections, skill of 1.5% or more, gap within 5 points (plus sampling error) |
| Low | anything else, including cells too thin to judge (these fall back to the market family in the same band, then to Low) |

A prediction near the usual rate carries almost no information, so a 95% "Over 0.5 goals" is Low even though it nearly always happens. The thresholds
(5%, 1.5%, 3 and 5 points, 200) are fixed in `src/pitchside/confidence.py`; which cells reach which tier comes from the backtest.

## Evidence
`scripts/backtest_tiers.py` prices every market (176 markets, 945 selections per match) for 1,400 random verified matches played from 2025/26 onward
with the production settings and settles each selection (1.32 million rows). `scripts/build_tiers.py` fits the rules on the earlier 60% of matches and checks them on the later 40%
(matches played after 2026-02-28 that the rules never saw):

| Tier | Share of predictions | Model said | Happened | Better than the base rate by |
|---|---|---|---|---|
| High | 20.6% | 40.7% | 40.8% | 7.2% |
| Medium | 39.2% | 22.3% | 22.4% | 3.3% |
| Low | 40.2% | 41.4% | 41.2% | 1.2% |

Higher tiers did better in every market family (A to E), and the probabilities in each tier matched what happened to within 0.2 points.
The final rules in `data/confidence_rules.json` are refitted on all 1,400 matches.

## Known limits
- Selections from the same match move together, so the effective sample is closer to the number of matches than the number of rows.
- Input quality was tested as a cap (no High rating when a team had under 60 matches in three years, for example a promoted side) and dropped: those matches
  were predicted no worse (skill +3.6% against +2.9%).
- Not included: model uncertainty, meaning how much a probability would move if the model were refitted. Not claimed anywhere.
- Rules belong to one model version. When the model changes, rebuild them (`backtest_tiers.py`, then `build_tiers.py`) before trusting the bars.
- Game-flow and minute markets (families C and D) are only settled where goal minutes are verified, so their ratings come from fewer matches than the rest.
