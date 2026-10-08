# BUILD.md: European Football Match Outcome Predictor

Working title: **Pitchside** (rename freely).
Builder: HEO. Executor: Claude Code. Read `CLAUDE.md` first for the gstack setup.

## Status and order of work (updated 2026-10-08)

**Done and running**
- Phase 0 data audit (`docs/data-audit.md`).
- Phase 1 and 1b: Supabase schema, five leagues loaded (about 20,000 matches, 167 clubs), the Dixon-Coles goals model with an honest backtest (`docs/goals-model-report.md`), 34 result-and-goals markets (family A), frozen append-only predictions, the settle step and track-record views, and a daily GitHub Actions pipeline (`docs/operations.md`).
- First live predictions were stored on 2026-10-08: 48 matches across the five leagues. They settle automatically once the matches are played.

- Phase 2 (2026-10-08): goal minutes verified and loaded for 2023 to 2026, the match simulator, and families B to E (142 markets). Held-out validation shows well-calibrated probabilities and some skill over the base rate in every family (`docs/goals-model-report.md`). Coverage is listed in `docs/market-coverage.md`.

**Order from here (agreed with HEO on 2026-10-08)**
1. ~~**Phase 2**: goal timing, the match simulator, and families B to E.~~ Done.
2. **Confidence tiers** (the backtest part of Phase 4), so every prediction can carry a tier.
3. **Phase 5**: the product screens (fixtures, match board, deep-dive, track record).
4. Along the way: **check the first live settlement** (after the 9 to 12 Oct matches) and fix anything it exposes. Then **improve the model** (xG signal, a prior for newly promoted teams, the over/under fix) using backtest and live evidence together.
5. Later, not blocking the above: Phase 3 (corners, cards, shots), Phase 6 (players), Phase 7 (odds comparison, case study).

**What depends on what**
- Phase 2 needs goal-minute data for all five leagues (Understat). It does not need live results.
- The screens only read the database, so they work with whatever model version is live. They need HEO's decision on Streamlit versus a custom web app (section 15) and a design pass (`/office-hours`, `/plan-design-review`).
- The track-record screen shows settled results, so the first live settlement should be checked before that screen is trusted.
- A better model later plugs in as a new model version. The goal-timing layer takes expected goals as an input, so it does not need rebuilding. Old predictions stay under the old version.

## 1. Goal

Cover **every match, in every game week, across the major European leagues**, not a single fixture. For each upcoming match, and for **every market a betting site offers** on it, the system gives a prediction, a probability and a confidence level, built from statistics.

The Premier League is the **pilot**: we build and prove everything on it first, then extend league by league (section 6a). Nothing in the design may be hard-wired to one league or one match.

Examples of what it answers:
- Match result: will the home team win, draw, or lose?
- Will this player score? Get a card? Have 2+ shots?
- How many corners, cards, shots, goals will there be, and is over or under a given line more likely?
- Will both teams score? Who scores first? What happens at half-time?

The **market list comes from the betting sites** (SportyBet first, others later). The markets define *what questions the system must answer*. The predictions come from our own statistical analysis. Odds are not an input to the prediction.

Reference fixture and **golden test match** (used for end-to-end testing, not the product's scope): Arsenal vs Leeds United, Sat 10 Oct 2026, 12:30, `sr:match:72221292`. SportyBet shows 262 market headers for it (full list in `docs/market-catalogue.md`).

Two outputs from one codebase:
1. A **product** for individuals: pick a league and game week, then open any match to see a board of every market with the prediction, probability, confidence and the statistics behind it.
2. A **portfolio case study** (HEO is a product manager): data audit, honest evaluation, product decisions, what did not work.

## 2. Ground rules (non-negotiable)

- **Honest about accuracy.** Football is noisy. Report how often predictions were right and how well calibrated they are, per market family. Never write "sure bet", "guaranteed", "banker" or "winning tips".
- **High probability is not the same as a good bet.** Show probability and confidence together. If bookmaker odds are loaded, also show the edge, and do not rank purely by probability.
- Time-ordered evaluation only. No leakage (section 8).
- Responsible gambling: 18+ notice, no bet placement, no affiliate links in v1.
- **League-agnostic by design.** Leagues are configuration (teams, seasons, sources, home advantage, goal rates), not code. Calibration and accuracy are reported **per league as well as per market family**; a league with thin data gets a lower confidence tier, not a silent pass.
- **Batch-ready.** Predicting a whole game week (up to ~50 matches across leagues) must run in one command, unattended, on a schedule.
- Verify before relying on a source. Phase 0 is a data audit; do not assume a source has a column until it has been pulled.
- Respect site terms. Prefer licensed APIs and published CSVs. Reading the public market names from a betting page is fine; automated scraping of odds is not added without HEO confirming the terms allow it.
- Keys in `.env`, never committed.

## 3. How a prediction is made (inputs)

For a fixture, the system gathers evidence from before kickoff:

1. **Recent form against everyone (momentum).** The last 5 to 10 matches of each team against *all* opponents: goals, xG, shots, shots on target, corners, cards, fouls, offsides, tackles, results. Each match is **weighted by opponent strength** (a win over a top side counts more than a win over a weak one) and by recency. Home and away form are kept separate.
2. **Head-to-head history** between the two teams. A smaller input, because samples are small. Used to adjust, not to lead.
3. **Team strength and context:** Elo, home advantage, rest days, fixture congestion, promoted-team and early-season priors, referee tendencies for cards and fouls.
4. **Player evidence** for the players in this fixture: recent form, scoring and assist rates, shots, tackles, fouls won, cards, minutes played, role, record against this opponent, and whether they are expected to start. Lineups, injuries and suspensions matter most here.

Every prediction shows the "why": the statistics that drove it.

## 4. Core design: one simulator, many markets

Do **not** train a separate model per market. Build one **match simulator** and read every market from its output. All answers stay consistent (Over 2.5 can never be more likely than Over 1.5).

```
inputs (form, strength, H2H, lineups, context)
   -> generative model of a match
   -> Monte Carlo: N = 100,000 simulated matches
   -> each sim = a MatchRecord (events + counts)
   -> market resolvers read the MatchRecord and settle: win / lose / push / half-win / half-lose
   -> probability = settled share across sims
```

`MatchRecord`: goals with minute and scorer/assister, half-time score, corners (half and order), cards (player), shots, shots on target, offsides, fouls, tackles, substitutions, posts/crossbars, per-player counts.

Model layers, built in this order:
1. **Goals:** team goal rates from Dixon-Coles / bivariate Poisson, or an ML model (XGBoost) predicting goals for each side, with a draw-correlation term. Goal minutes from an empirical time profile (more goals late) with a first-half/second-half split.
2. **Count stats:** corners, cards, shots, shots on target, offsides, fouls, tackles. Negative binomial per team, rates driven by recent form, opponent, and game state (trailing teams earn more corners).
3. **Game-state coupling:** simulate minute by minute (or in 5-minute blocks) so "1UP", "Never Down", "lead by N at any time", "win from behind", goals in a row and "1X2 at minute N" fall out naturally.
4. **Players:** allocate team events to players using lineup, minutes, role and per-90 rates. Weakest layer; ship last, labelled experimental.

Analytic check: for goal markets the scoreline matrix gives exact answers, and the simulator must agree with it. Add as a test.

## 5. Market catalogue

Source: the SportyBet match page, read on 2026-10-06. Full list with groupings in `docs/market-catalogue.md`. Each market is a resolver in `src/pitchside/markets/`, parameterised by line (not one function per line), with a canonical ID and a mapping from each site's display name (`data/market_aliases.csv`).

| Family | Markets | Decided by |
|---|---|---|
| **A. Result and goals** | 1X2, over/under (match and each team), early goals, double chance, draw no bet, home/away no bet, 3-way and Asian handicap, GG/NG, odd/even, exact goals, goal range and bounds, excluded goals, clean sheets, win to nil, winning margin, teams to score, correct score, multigoals, multiscores | Goal model scoreline matrix |
| **B. Halves** | 1st and 2nd half versions of 1X2, over/under, double chance, DNB, 1st goal, handicaps, team goals, GG/NG, correct score, exact goals, clean sheets, win to nil, odd/even, multigoals; HT/FT, HT/FT correct score; both halves over/under 1.5; team to score in both halves; highest scoring half; win either/both halves; 1st-half result or match result | Goal model with half split |
| **C. Game flow** | 1X2 1UP / 2UP / Never Down, 2 or 3 goals in a row, lead by 1/2/3 at any time, win from behind, 1st goal, last goal | Minute-by-minute simulation |
| **D. Minutes** | 1X2 from minute 1 to N, total goals over/under from 1 to N (N = 5, 10, 15 ... 85), when the 1st goal is scored (10 and 15 minute intervals) | Goal minute profile |
| **E. Combos** | 1X2 with over/under or GG/NG, over/under with GG/NG, 1st goal with 1X2, HT/FT with over/under or exact goals, double chance with over/under or GG/NG (full time and halves), "Team or Over/Under 2.5", "Team or GG", "Team or Any Clean Sheet" | Joint probabilities from the same sims |
| **F. Corners** | Match over/under, corners 1X2, 1st/last corner, home/away corners, ranges, odd/even, 1st-half versions | Corner count model |
| **G. Bookings** | Team cards, match cards (full time and each half), player to be carded | Card count model, referee, player foul rates |
| **H. Match stats** | Shots 1X2 and over/under, shots on target 1X2 and over/under, posts and crossbars, offsides, tackles, team shots/SOT/tackles, team assists, 1st-half substitutions | Count models |
| **I. Players** | 1st/last/anytime goalscorer, player not to score, player goals, assists, shots, shots on goal, tackles, fouls won, to be carded | Player layer, lineup dependent |

Notes: many markets repeat at several lines; some show no price on the site; odds are decimal. We only need the market *names and rules* from the sites, not their prices.

## 6. Data sources

Run Phase 0 against every row and record what actually comes back in `docs/data-audit.md`.

| Need | Source | Notes |
|---|---|---|
| Results, **half-time goals, corners, cards, fouls, shots, shots on target** | **football-data.co.uk** CSVs, or `soccerdata.MatchHistory` | Free, many seasons. Primary table for families A, B, F, G, H. No goal minutes, scorers, offsides or tackles. |
| Goal minutes, scorers, shots with xG | `soccerdata.Understat()` | First/last scorer, goal timing, player xG/xA/shots. |
| Event stream (tackles, fouls, offsides, cards, subs, corners with minute) | `soccerdata.WhoScored().read_events()` | Verified for one match. Fragile and slow; scale not yet tested. Only source for tackles, offsides, substitutions. |
| Upcoming fixtures, confirmed lineups, per-player match stats | ESPN public JSON (`site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard` and `/summary`) | Verified for the Big 5. Unofficial API. Lineups only appear about an hour before kickoff. No tackles. |
| Team strength | `soccerdata.ClubElo()`, else our own Elo from results | ClubElo returned HTTP 502 on 2026-10-07. |
| Squad market values (optional) | Transfermarkt datasets on Kaggle | No reader in soccerdata. |
| Expected lineups, injuries, suspensions | **Open gap** (see `docs/data-audit.md`) | ESPN gives confirmed lineups only about 1 hour before kickoff. No source yet for earlier expected starters. Needed for player markets and confidence. |
| Bookmaker odds (optional, later) | The Odds API, football-data.co.uk historical odds, or manual import | Only for the odds-comparison add-on. See section 11. |

### 6a. League coverage

Proposed order (HEO to confirm, section 15):
1. **Pilot:** Premier League.
2. **Big 5:** add La Liga, Bundesliga, Serie A, Ligue 1. Understat and ClubElo cover these, and football-data.co.uk has all of them, so the data audit should transfer.
3. **Next tier (if wanted):** Championship, Eredivisie, Liga Portugal, Scottish Premiership, Belgian Pro League, Turkish Super Lig.
4. **European cups (if wanted):** Champions League, Europa League, Conference League. These pair teams from different leagues, so team strength must be comparable across leagues (Elo helps) and there is less shared history.

Per-league data coverage differs (for example, event data and player stats are thinner outside the top leagues). Phase 0 records coverage **per league**, and a market family is only offered for a league where its data exists. The betting sites' market lists are checked per league too, since smaller leagues usually offer fewer markets.

**Cross-league modelling:** one pooled model with league-level effects (goal rate, home advantage, draw rate, card and corner rates) so small leagues borrow strength from big ones, rather than separate models per league. Team strength comes from within-league form plus Elo for cross-league comparison.

**FBref note:** FBref lost its Opta licence in Jan 2026 and no longer updates advanced stats. Do not depend on it.

## 7. Confidence

Confidence must mean something testable. For each prediction show:
- **Probability** `p`: the calibrated simulation probability.
- **Confidence tier (High / Medium / Low)** from four ingredients:
  1. **Backtested reliability of that market family** at that probability bucket (when we said 70-80%, how often did it happen?). Poorly calibrated families cannot reach High.
  2. **Input quality:** lineups confirmed, matches played this season, data coverage, injuries known.
  3. **Model uncertainty:** spread of `p` across bootstraps or ensemble members.
  4. **Distance from the base rate:** a prediction near the league average carries little information.
- **The pick:** for yes/no and over/under markets, the side with the higher `p`; for multi-outcome markets, the most likely outcome, with the others listed.

Rules:
- Tier thresholds are set from the calibration backtest, not by hand, and written in `docs/model-card.md`.
- Publish the calibration chart per market family. Poorly calibrated families (likely players) are labelled "experimental".

## 8. Features and leakage rules

Every feature for match M uses **only data from before M's kickoff**. Add a test that fails if any feature row uses a stat dated on or after its match date.

- Rolling form (last 5/10, home/away split), opponent-strength adjusted, recency weighted.
- Elo and Elo difference, rest days, congestion, home advantage.
- Promoted teams and early season: priors from last season and league average.
- Style indicators (possession, crossing, pressing) that drive corners and cards.
- Referee tendencies.
- Lineup strength and player availability.
- Head-to-head, with shrinkage toward the general model.

## 9. Evaluation

Split by season. Walk-forward retraining.

Baselines per market family: league base rate, and (where we have it) bookmaker de-margined closing odds as a hard benchmark.

Metrics per family: **accuracy of the pick, log loss, Brier score, calibration curve**; ranked probability score for ordered outcomes; negative binomial vs Poisson fit for corners, cards, shots.

Consistency tests: simulator vs analytic scoreline matrix; monotonic lines (Over 2.5 <= Over 1.5); complementary outcomes sum to 1 (pushes handled); half-time and full-time scores compatible.

## 10. Product

Hypotheses to test, not assume: users want to see **why**, and they distrust black boxes, so the track record must be visible.

v1 screens:
1. **Fixtures:** league and game-week selector listing every upcoming match, each with headline H/D/A probabilities and a data-quality badge (lineups confirmed or not). Out of the box it shows all leagues for the coming week.
2. **Match board** (main screen): every market, grouped like the betting sites (Main, Goals, Half, Bookings, Corners, Specials, Players, Teams, Minutes). Each shows the pick, probability and confidence. Filters: confidence tier, family. A "why" panel shows the stats behind it.
3. **Match deep-dive:** both teams' recent form, head-to-head, key players.
4. **Track record:** calibration and accuracy by market family and by league. All predictions stored at prediction time and scored after the match, so the record cannot be edited.

Out of v1: accounts, payments, bet placement, in-play updating. League coverage in v1 is whatever has passed its data audit (section 6a).

Run `/office-hours` and `/plan-design-review` before the UI, and `/design-consultation` for the visual system.

## 11. Odds comparison (optional add-on, after predictions work)

Not part of the core. When added, an `OddsProvider` interface with:
1. `ManualImportProvider`: paste or upload the odds seen on SportyBet or any book, mapped through `market_aliases.csv`.
2. `TheOddsApiProvider`: licensed live odds for the markets it carries (verify sport key and markets first; props are not on all plans).
3. `FootballDataCoUkProvider`: historical odds for backtests (main markets only).

Shows edge = `p - fair_implied_probability(odds)` and `EV = p * odds - 1` next to the prediction. Record each site in `docs/odds-sources.md` (API? licence? terms?) before using it. No scraping without HEO confirming terms.

## 12. Tech stack

Python 3.11+, `uv`. `pandas`, `numpy`, `scipy`, `scikit-learn`, `xgboost`, `statsmodels`, `soccerdata`, `requests`, `numba`, `plotly`.
Production database: **Supabase (Postgres)**. Raw file cache in `data/raw/` locally (object storage such as Cloudflare R2 later if needed). **DuckDB** is for local development and analysis only, never the system of record.
API: **FastAPI**. UI: Streamlit (fast demo) or Next.js (product feel), decided at design review. Frontend may be hosted on Cloudflare Pages.
Scheduled jobs: Python on a scheduled runner (GitHub Actions cron or a small hosted container), not Cloudflare Workers (the simulation and scrapers need Python and heavy compute).
Tests: `pytest`. Lint: `ruff`.

## 12a. Data platform and the settle-and-score loop

The project is built for production. **Supabase Postgres is the system of record** for history, fixtures, predictions, results and scores. The scheduled job is the only writer; the API and app read.

### Layers
1. **Raw cache:** files exactly as fetched. Never edited. Lets us rebuild the warehouse without re-scraping.
2. **Warehouse tables (Postgres):** `leagues`, `teams` and `team_aliases` (one canonical team per club, with each source's spelling), `matches` (fixtures and results, keyed by league, season, kickoff), `team_match_stats`, `match_events` (goals, cards, corners, subs with minute), `player_match_stats`, `lineups`, `elo_ratings`. History is backfilled once; after that each run adds only matches finished since the last run.
3. **Prediction tables (append-only, never updated or deleted):**
   - `prediction_runs`: run id, timestamp, model version, data cutoff, feature version.
   - `predictions`: run id, match, canonical market id, line, selection, probability, pick, confidence tier, "why" (JSON). Written before kickoff and frozen.
   - Row-level security: the app and API have read-only access; only the job can insert. Updates and deletes on prediction tables are blocked.
4. **Settlement tables:**
   - `match_outcomes`: the real `MatchRecord` for each finished match, built from the warehouse.
   - `settlements`: for each prediction, the result (`won`, `lost`, `push`, `half_won`, `half_lost`, `void`, `not_scorable`), the observed value, and the scores (log loss and Brier contribution).

### Weekly job
1. **Ingest:** fetch results since the last run (football-data, Understat, WhoScored, ESPN), map team names through `team_aliases`, upsert.
2. **Settle:** for every finished match with unsettled predictions, build the real `MatchRecord` and settle each prediction with the **same market resolvers the simulator uses**, so prediction and settlement can never disagree about a market's rules. Write `settlements`.
3. **Report:** refresh the track-record views (below).
4. **Plan:** fetch the next game week's fixtures for all leagues (ESPN), update lineups where available.
5. **Predict:** build features as of now, simulate each match, store all market predictions in a new `prediction_runs` entry.
6. **Re-predict near kickoff:** when lineups are confirmed, a second run adds new predictions (the first run is kept, never overwritten).

All steps are idempotent: re-running a step for the same inputs gives the same rows.

### Not scorable
A market is only settled where real result data exists. Goals, halves, game flow, corners, team cards and shots are scorable from our sources. Tackles, offsides and substitutions depend on WhoScored. If the data for a finished match is missing, the settlement is `not_scorable`, counted separately, and never guessed.

### Learning from the results
Views (or materialised views) over `settlements` give:
- accuracy, log loss, Brier score and calibration curve by market family, by league, by confidence tier, by model version, and over time;
- the worst-calibrated families and leagues (the improvement backlog);
- hit rate when the model was High confidence versus Low, which tests whether the confidence tiers mean anything;
- model version A versus B on the same set of matches.

Improvement cycle: review the track record, pick the weakest family or league, change the model or features, **backtest first** (walk-forward, section 9), release as a new model version, and compare it against the old version on live matches. Model versions are never deleted, so every past prediction stays explainable.

### Security and operations
- Keys in `.env` locally and in the host's secret store in production, never committed. The Supabase service key is used only by the job.
- Database migrations are SQL files in `db/migrations/`, applied in order.
- Backups: use Supabase's backups, and export the prediction tables regularly.
- Job failures alert (email or chat), and a failed ingest never blocks settling or predicting for the leagues that did succeed.

```
Match_Outcome/
  CLAUDE.md  BUILD.md
  docs/        market-catalogue.md  data-audit.md  odds-sources.md  model-card.md  case-study.md
  data/        raw/  processed/  market_aliases.csv  team_aliases.csv  (seed files; local DuckDB only for dev)
  db/          migrations/  (Postgres schema for Supabase)
  scripts/     audit scripts, one-off tools
  src/pitchside/
    leagues.py            (league config: id, sources, seasons, team and market coverage)
    db/        client.py  repositories (Postgres access)
    pipeline/  weekly.py  (ingest, settle, report, plan, predict for a game week, all leagues)
    settle/    match_record.py  settle.py  scoring.py  (settle predictions against real results)
    ingest/    results.py  team_stats.py  events.py  players.py  elo.py  lineups.py  fixtures.py
    features/  rolling.py  h2h.py  build.py
    sim/       goals.py  counts.py  game_state.py  players.py  simulate.py  record.py
    markets/   base.py  goals.py  halves.py  path.py  timeline.py  combos.py  corners.py  cards.py  stats.py  players.py
    models/    baseline.py  train.py  calibrate.py  evaluate.py
    confidence/ tiers.py
    odds/      (optional, section 11)
    api/       main.py
  app/
  tests/
```

## 13. Scope and phases

Ship in layers, because data quality drops sharply from goals to players.

**Phase 0: Data audit. [DONE]** For the golden match and one full past season, pull every source in section 6, for the Premier League and each Big 5 league. Write `docs/data-audit.md`: columns that exist, coverage, failures, rate limits, **per league**. Map each market family to "data available / partial / missing" per league. Also check each league's betting-site market list against `docs/market-catalogue.md`. *Done when HEO reviews it and agrees the v1 scope.*

**Phase 1: Database, goals foundation, and the first settle loop (Premier League pilot, league-agnostic code). [DONE, except checking the first live settlement]** First create the Supabase project (with HEO's go-ahead), the migrations in `db/migrations/` for the warehouse and prediction tables (section 12a), and the team alias table. Then ingest 10+ seasons of results and half-time goals into Postgres. Build the form features (opponent-adjusted, recency weighted) and head-to-head. Scoreline model plus baselines. Resolvers for family A. *Done when 1X2, over/under, GG/NG, double chance, handicaps and correct score reproduce from one command for the golden match and match the analytic matrix, predictions for a game week are stored in Postgres, and the settle step scores them against real results (family A) once the matches are played.*

**Phase 1b: Add the Big 5 and the weekly batch. [DONE]** Add La Liga, Bundesliga, Serie A and Ligue 1 as league config, retrain the pooled model, and build `pipeline/weekly.py` so one command predicts a full game week across all leagues. *Done when a full game week for all five leagues runs unattended, with per-league calibration reports.*

**Phase 2: Simulator, halves, game flow, minutes, combos. [DONE]** Families B, C, D, E. *Done when consistency tests pass.*

**Phase 3: Count markets.** Corners, cards, shots, shots on target (F, G, H) from football-data.co.uk columns first. *Done when each has a calibration report.*

**Phase 4: Confidence and track record.** Settlement extended to all scorable families, tiers from backtests, the improvement views in section 12a. *Done when the model card documents the tier thresholds and per-family accuracy.*

**Phase 5: Product.** FastAPI plus fixtures, match board, deep-dive, track record. Run `/qa` and `/design-review`. *Done when a stranger can open the match board and understand it unaided.*

**Phase 6: Player markets (experimental).** Lineups, per-player rates, family I. Ship behind an "experimental" label unless calibration supports more.

**Phase 7: Odds comparison and portfolio write-up.** Section 11 add-on, then `docs/case-study.md`: problem, users, scope decisions (why goals first, why players last), data audit findings, honest results, what failed, next steps.

## 14. gstack workflow

- Plan: `/office-hours`, then `/plan-eng-review` and `/plan-design-review` (or `/autoplan`).
- Build with tests; `/review` before merges; `/test-audit` periodically.
- All web browsing, including reading betting-site market lists: `/browse` or `/scrape`.
- Safety: `/careful` around data files; `/freeze` to limit edits to a directory.
- Ship: `/ship`, `/land-and-deploy`, `/canary`. Security pass: `/cso`.
- Weekly: `/retro`.

## 15. Open questions for HEO

Decided: leagues for v1 are the Big 5 (Premier League, La Liga, Bundesliga, Serie A, Ligue 1); the next tier and the European cups come later if wanted. **Supabase Postgres** is the production database. The scheduled job runs on **GitHub Actions** (daily, `.github/workflows/pipeline.yml`). The web app is a **custom build** (decided 2026-10-08, not Streamlit). Still open: the framework and where the API and web app are hosted (Phase 5 design review).

1. Which other betting sites should we read market lists from?
2. Is v1 limited to families A to H (no players), as proposed?
3. ~~Streamlit or custom web UI?~~ Decided 2026-10-08: a **custom web app** (more product-like). Framework and hosting to be chosen at the Phase 5 design review.
4. Publish publicly, or portfolio case study only?
5. Is odds comparison wanted in v1 at all, or after the predictions are proven?
