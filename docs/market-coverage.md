# Market coverage

What the system prices today, against the SportyBet catalogue in `docs/market-catalogue.md`. Updated 2026-10-16.

**200 markets: 945 selections per match from the goals simulation plus 212 from the count models** (corners, cards, shots, shots on target).
Families A to E are priced from one simulation so they agree with each other; F to H come from their own count models and are independent of it.

| Family | Markets | How priced | Settled from |
|---|---|---|---|
| A. Result and goals | 34 | Exactly, from the goals model's scoreline matrix | Final score |
| B. Halves | 53 | Simulation | Final and half-time score |
| C. Game flow | 14 | Simulation | Verified goal minutes |
| D. Minutes tab | 34 | Simulation | Verified goal minutes |
| E. Combinations | 41 | Simulation | Final and half-time score |
| F. Corners | 7 | Negative binomial count model (model line `counts-nb-0.1.0`) | Team corners from football-data |
| G. Cards | 7 | Same | Yellow plus red cards |
| G. Card timing | 5 | The cards count model's joint distribution of both sides' cards, split into halves and minutes by the typical pattern of past cards (model line `cardtime-0.1.0`) | The cards of the match with their minute (ESPN), only when they add up to the real card counts |
| H. Shots and shots on target | 10 | Same | Team shots and shots on target |
| I. Players (experimental) | 7 | Each player's recent share of his club's goals, shots, shots on target and assists, scaled by the goals model's expected goals; cards from his recent cards per club match scaled by the club's expected cards in the match; fouls committed and won from his recent record (model line `players-0.3.0`, with the announced lineup `players-0.4.0`) | The player's own counts: shots and goals from Understat, cards and fouls from the ESPN match log shot events |

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

- **F, G, H**: for each statistic (corners, cards, shots, shots on target): over/under for the match total and for each team, which team has more (1X2), a handicap on the difference, and where it makes sense odd/even
  (corners, cards) and a range (corners, cards). All lines are half lines so no stake is returned. Full-time only: football-data records match totals, not halves.
  Held-out skill over how often each thing usually happens: corners +3.6%, cards +2.6%, shots and shots on target +8.4% (`scripts/backtest_counts.py`, `docs/goals-model-report.md`).

- **I (experimental)**: anytime goalscorer, anytime assist, player shots over 0.5/1.5/2.5, player shots on target over 0.5/1.5. One selection per player, so selections of a market do not add to 1 and no pick is flagged.
  Only players with a meaningful chance are priced (up to about a dozen per club). Settled from the shot events; a player who took no shot counts as a loss even if he did not play (bookmakers would void it).

## Not built yet

- **A**: Over/Under - Early Goals (needs a minute parameter we have not confirmed), full-time Multigoals (home, away, match), Correct Score [0:0] variant.
- **B**: HT/FT correct score, 1st-half and 2nd-half "1st Goal", first-half goal bounds and excluded goals.
- **E**: HT/FT with exact goals.
- **F-H**: first and last corner and half-by-half corners (ESPN lists corner minutes but misses 1 to 5 corners in most matches, so they are not reliable), posts and crossbars, offsides, tackles, team assists, substitutions: no data source for them in our feeds.
- **I players**: first/last goalscorer, tackles, player goals as a count line: no data or no calibrated approach yet. Lineups are used only once announced (about an hour before kickoff), and the lineup adjustment is not validated.

## Rules we settled on where the site's text was ambiguous

- A goal's minute is the minute shown by Understat. Stoppage-time goals count as minute 45 (first half) or 90 (second half) for the interval markets.
- "Goals from 1 to N minutes" counts every goal up to and including minute N.
- Own goals count for the team credited with the goal.
- 1UP / 2UP: a side's bet is won as soon as it leads by one or two goals, whatever happens afterwards; the draw is settled on the full-time score.

## Card timing and player cards and fouls (added 2026-10-16)

Data: ESPN match summaries from 2023/24 on (`scripts/load_espn_log.py`, daily for new matches): every card with its minute and player, and each player's fouls and cards. A match's log is
trusted only when the cards ESPN lists for each side, and the players' own cards, equal the yellow plus red cards football-data recorded for that side (about nine matches in ten); the rest are
flagged and ignored.

- **Card timing (G)**: cards 1st half over/under 0.5, 1.5, 2.5; 2nd half over/under 0.5 to 3.5; which half has more cards; which team is shown the first card (or none); a card shown by minute 15, 30 or 45.
- **Players (I)**: to be carded, fouls committed over 0.5 or 1.5, fouls won over 0.5 or 1.5. They exist for every league with a log, the Championship included.
