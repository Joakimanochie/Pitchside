# Odds sources

BUILD.md section 11 requires every odds source to be recorded here (what it is, its licence and terms) before it is switched on. Odds are only ever shown
next to a prediction and compared with it. They are never a model input.

| Source | Used for | Access | Terms | Status |
|---|---|---|---|---|
| football-data.co.uk historical files (`mmz4281/<season>/<league>.csv`) | Closing odds in backtests (`scripts/backtest_value.py`, the goals backtest) | Free CSV download | Free to use with credit to the site; no redistribution of the raw files | In use since Phase 0 |
| football-data.co.uk `fixtures.csv` | Pre-match prices for the coming fixtures: market average, best price and Bet365 for the match result, over/under 2.5 and the main Asian handicap | Free CSV, refreshed by the site a few days before each round | Same site terms as above | In use (daily pipeline, `odds_snapshots`) |
| SportyBet (or any betting site) | The prices a user actually bets at | None. There is no public API and scraping is not allowed without confirming the terms | Not used | Not built. A manual paste importer is the safe route (`OddsProvider` in `src/pitchside/odds/provider.py`) |
| A licensed odds API (for example The Odds API) | Live prices from many bookmakers, more markets | Needs a paid plan and a key | Check the plan's markets and redistribution terms before use | Not built. Plugs in as another `OddsProvider` |

## The Odds tab and market availability
The aim: every bet on the Odds tab is one a user can place on their betting site, in a market the site lists. Level 1 is a confirmed list per league in `data/market_availability.json`
(read by `src/pitchside/accas.py`; `WIDELY_OFFERED` there is only the fallback if the file is missing). It names the site's markets and goal lines, and each leg shows the site's own market name ("Over/Under", "GG/NG", "Arsenal Over/Under").
`confirmed_on` and `lines_confirmed` record how far each league's list has been checked on a match page of the site; until `lines_confirmed` is true the Odds page tells users that a line may be missing.
To confirm a league: open one upcoming match of that league on the site, copy the lines under Over/Under, each team's Over/Under, Double Chance and GG/NG, edit the league's entry (a `markets` block like `default`'s), set `lines_confirmed` to true and `confirmed_on` to the date. Slips already stored are not changed; new slips use the new list.
Level 2, a check of every match against the site's own list, needs a licensed odds feed and is not built. The slips' odds are the model's fair odds. Showing only markets a site really has open, with the site's own price, needs a licensed odds API (for example The Odds API, paid) behind the `OddsProvider` seam; scraping a betting site is not allowed without confirming its terms and is not built.

## How the data is kept
- `odds_snapshots` stores each price with the time it was fetched, append-only; only changed prices are written. `v_latest_odds` gives the newest price per selection.
- No row-level-security policy gives the anonymous role access: odds are available to the web app only through the pipeline's exported files, which sit behind the access lock.
- The comparison on the match page uses the market average price (to remove the margin and read the bookmakers' own view) and the best price (the best a bettor could have taken).

## What is covered and what is not
Match result, over/under 2.5 goals and the main Asian handicap. Both-teams-to-score, double chance, correct score and the other 170 markets have no free pre-match price source,
so no comparison is shown for them. Where an Asian handicap line is a whole or quarter number the stake can be returned, which our probability convention excludes, so no expected value is shown for it.
