# Market coverage

What the system prices today, against the SportyBet catalogue in `docs/market-catalogue.md`. Updated 2026-10-08.

**176 markets, 945 selections per match**, all priced from one simulation so they agree with each other.

| Family | Markets | How priced | Settled from |
|---|---|---|---|
| A. Result and goals | 34 | Exactly, from the goals model's scoreline matrix | Final score |
| B. Halves | 53 | Simulation | Final and half-time score |
| C. Game flow | 14 | Simulation | Verified goal minutes |
| D. Minutes tab | 34 | Simulation | Verified goal minutes |
| E. Combinations | 41 | Simulation | Final and half-time score |
| F. Corners, G. Bookings, H. Match stats, I. Players | not built | | |

"Verified goal minutes" means Understat's goals add up to the real full-time and half-time scores. A match that fails that
check keeps its goal-minute markets as "not scorable" and is never settled from doubtful data.

## In each family

- **A**: 1X2, double chance, draw no bet, home/away no bet, 3-way and Asian handicap (including quarter lines), total and team over/under,
  GG/NG and GG/NG 2+, odd/even (match, home, away), exact goals, goal range, home/away goals, teams to score, clean sheets, win to nil,
  winning margin, excluded goals, goal bounds, no-draw BTTS, correct score, multiscores.
- **B**: first-half and second-half versions of 1X2, double chance, draw no bet, over/under, handicap, Asian handicap, team over/under,
  GG/NG, clean sheets, win to nil, odd/even, exact goals, correct score, multigoals; and HT/FT, both halves over/under 1.5,
  1st/2nd half GG/NG, team to score in both halves, both teams to score in both halves, highest scoring half (match, home, away),
  win either half, win both halves, 1st half result or match result.
- **C**: 1X2 1UP, 2UP and Never Down, double chance 1UP, first goal, last goal, leading by 1/2/3 at any time (any, home, away),
  2 or 3 goals in a row (any, home, away), win from behind.
- **D**: 1X2 and total goals within the first N minutes (N = 5 to 85), and the interval of the first goal (10 and 15 minute).
- **E**: 1X2 with over/under (1.5 to 4.5) and with GG/NG, over/under 2.5 with GG/NG, 1st goal with 1X2, HT/FT with over/under (full match and
  first half), double chance with over/under and GG/NG (full time and each half), half-by-half 1X2 and double chance with totals and GG/NG,
  and "Team or Over/Under 2.5", "Team or GG", "Team or Any Clean Sheet".

## Not built yet

- **A**: Over/Under - Early Goals (needs a minute parameter we have not confirmed), full-time Multigoals (home, away, match), Correct Score [0:0] variant.
- **B**: HT/FT correct score, 1st-half and 2nd-half "1st Goal", first-half goal bounds and excluded goals.
- **E**: HT/FT with exact goals.
- **F corners, G bookings, H match stats, I players**: not started. Corners, team cards and shots are next (Phase 3), players last (Phase 6).

## Rules we settled on where the site's text was ambiguous

- A goal's minute is the minute shown by Understat. Stoppage-time goals count as minute 45 (first half) or 90 (second half) for the interval markets.
- "Goals from 1 to N minutes" counts every goal up to and including minute N.
- Own goals count for the team credited with the goal.
- 1UP / 2UP: a side's bet is won as soon as it leads by one or two goals, whatever happens afterwards; the draw is settled on the full-time score.
