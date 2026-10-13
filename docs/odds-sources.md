# Odds sources

BUILD.md section 11 requires every odds source to be recorded here (what it is, its licence and terms) before it is switched on. Odds are only ever shown
next to a prediction and compared with it. They are never a model input.

| Source | Used for | Access | Terms | Status |
|---|---|---|---|---|
| football-data.co.uk historical files (`mmz4281/<season>/<league>.csv`) | Closing odds in backtests (`scripts/backtest_value.py`, the goals backtest) | Free CSV download | Free to use with credit to the site; no redistribution of the raw files | In use since Phase 0 |
| football-data.co.uk `fixtures.csv` | Pre-match prices for the coming fixtures: market average, best price and Bet365 for the match result, over/under 2.5 and the main Asian handicap | Free CSV, refreshed by the site a few days before each round | Same site terms as above | In use (daily pipeline, `odds_snapshots`) |
| SportyBet (or any betting site) | The prices a user actually bets at | None. There is no public API and scraping is not allowed without confirming the terms | Not used | Not built. A manual paste importer is the safe route (`OddsProvider` in `src/pitchside/odds/provider.py`) |
| A licensed odds API (for example The Odds API) | Live prices from many bookmakers, more markets | Needs a paid plan and a key | Check the plan's markets and redistribution terms before use | Not built. Plugs in as another `OddsProvider` |

## How the data is kept
- `odds_snapshots` stores each price with the time it was fetched, append-only; only changed prices are written. `v_latest_odds` gives the newest price per selection.
- No row-level-security policy gives the anonymous role access: odds are available to the web app only through the pipeline's exported files, which sit behind the access lock.
- The comparison on the match page uses the market average price (to remove the margin and read the bookmakers' own view) and the best price (the best a bettor could have taken).

## What is covered and what is not
Match result, over/under 2.5 goals and the main Asian handicap. Both-teams-to-score, double chance, correct score and the other 170 markets have no free pre-match price source,
so no comparison is shown for them. Where an Asian handicap line is a whole or quarter number the stake can be returned, which our probability convention excludes, so no expected value is shown for it.
