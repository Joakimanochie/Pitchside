# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated (HEO, 2026-10-09): the first clickable prototype is plain static HTML/CSS/JS with no build step, reading a JSON snapshot of real predictions,
because it is the fastest way to judge the design. The production web app is a custom build hosted on Cloudflare; its framework is chosen at the
Phase 5 design review (see BUILD.md section 12). Data comes from Supabase through a thin API, so database credentials never reach the browser.

## Users

- **First user (now): HEO**, the product owner, using it privately to test how the predictions fare against real results once the first matches are played.
- **Later users: paying subscribers** who bet on football and want a probability for every market on every match in Europe's top five leagues. Subscriptions,
  accounts and payments are not in scope until the early results are good. The site is private to HEO until then.

## Product Purpose

For every upcoming match in the Premier League, La Liga, Bundesliga, Serie A and Ligue 1, show a prediction, a probability and a confidence level for every
market a betting site offers (176 markets, 945 selections per match, grouped the way betting sites group them). Every prediction is stored before kickoff
and scored after the match, so how well it did is always visible. Success, for now: HEO can open a match, see every market with its probability and the
statistics behind it, and later compare predictions with what actually happened.

## Positioning

One consistent simulation prices every market, so the numbers can never contradict each other (a bigger over/under line is never more likely than a smaller one).
Predictions are frozen before kickoff and scored against real results, and the track record cannot be edited. The product reports its own limits plainly:
on the plain match result the model beats a league-average guess but still trails the bookmakers' closing odds; its probabilities are well calibrated.

## Operating Context

- A daily pipeline (GitHub Actions) ingests results and fixtures, settles past predictions, and stores one official prediction per match when it enters a 5-day window.
- Data lives in Supabase (Postgres). Predictions and settlements are append-only; views give accuracy, calibration and pick accuracy by market family, league and model version.
- Matches cluster Friday to Monday; midweek rounds exist. Kickoff times are shown to the user in their own time zone.
- The site is private for now (restricted to HEO, for example with Cloudflare Access), hosted on Cloudflare.

## Capabilities and Constraints

- Model version `goals-dc-0.2.0`: a goals model, a half-time table and a goal-timing profile, simulated. Families priced: result and goals (34 markets), halves (53),
  game flow (14), minutes tab (34), combinations (41). Not built: corners, bookings, match stats, players (see `docs/market-coverage.md`).
- **Confidence tiers (High / Medium / Low) are not calibrated yet.** Until they are, any screen that shows them must say so; nothing may be presented as final.
- Lineups, injuries and suspensions are **not** used. The model knows past scores and the half and timing patterns only.
- No odds, edge or bet placement in this version. Odds comparison is a later optional add-on.
- Never rank or sort by raw probability alone. Probability and confidence are always shown together. No "sure bet", "guaranteed", "banker" or "winning tips" wording anywhere.
- A responsible-gambling notice (18+, estimates not advice, no bet placement) is part of the platform from the first screen.
- Terms: "market", "selection", "line" (for example 2.5 for over/under), "pick" (the most likely selection of a market whose selections are mutually exclusive),
  "family" (A to E), "model version", "run".

## Brand Commitments

- Working name: **Pitchside** (BUILD.md allows renaming).
- HEO volunteered binding visual references: the two sites https://practicegateway.com/ and https://www.brimble.io/ (notes and screenshots in `docs/design-reference/`),
  with **restrained animation**: HEO likes the first site's animations but does not want many.

## Evidence on Hand

- Live: 48 upcoming matches across the five leagues, each with 945 stored predictions (model 0.2.0, run on 2026-10-09), in Supabase.
- Backtests with honest results: `docs/goals-model-report.md` (goals model by league, half-time model, held-out simulator validation with calibration).
- Market list and rules read from SportyBet: `docs/market-catalogue.md`, `docs/market-coverage.md`.
- **Absent, so never fabricate:** a live track record (no match has been settled yet; the first settlements come after the 9 to 12 Oct 2026 weekend), odds, customers, testimonials,
  subscriber counts, pricing, and calibrated confidence tiers.

## Product Principles

1. **Honest over impressive.** State what the model knows and does not know; never imply certainty or a winning system.
2. **Probability and confidence together.** A likely outcome is not a good bet; nothing is ranked by probability alone.
3. **Show the why.** Every prediction can be traced to the numbers behind it (expected goals, history used, model version).
4. **The record is the product.** Predictions are frozen before kickoff and scored after; the track record is visible and cannot be edited.
5. **Consistency across markets.** All numbers come from one simulation, so the board never contradicts itself.

## Accessibility & Inclusion

- Required: a responsible-gambling notice; respect the browser's reduce-motion setting (all animation off); never use color alone to carry meaning (won / lost, confidence), and meet WCAG AA contrast.
