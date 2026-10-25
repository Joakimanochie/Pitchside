# Pitchside

A probability for every market a betting site offers, for every match in Europe's top leagues. Predictions come from statistics, never from bookmaker odds. They are stored before kickoff, never edited, and scored after the match.

Pitchside is a private preview, open by Google sign-in. It shows estimates, not advice or tips, and it does not take bets. It is for people aged 18 and over.

## What it covers

| Competition | Goals markets | Corners, cards, shots | Card timing | Players |
|---|---|---|---|---|
| Premier League, La Liga, Bundesliga, Serie A, Ligue 1 | yes | yes | yes | goals, shots, assists, cards, fouls |
| Championship | yes | yes | yes | cards and fouls only |
| Champions League, Europa League (experimental) | yes (90 minutes) | yes | yes | cards and fouls only |

About 210 markets per match: result, double chance, handicaps, over/under, both teams to score, correct score, halves, game flow, goal minutes, combinations, corners, cards, shots and shots on target, card timing and player markets. Coverage and gaps are listed in [docs/market-coverage.md](docs/market-coverage.md).

Each number carries a High, Medium or Low confidence rating, set from how the model did on past matches of that kind (the Championship and the cups are not rated yet). The Track record page scores every stored prediction after the match.

## How it works

```
football-data.co.uk, Understat, ESPN, openfootball
        │  daily GitHub Actions job (07:00 UTC) + half-hourly lineups job
        ▼
   Supabase Postgres  ── append-only predictions, settlements, track-record views
        │  scripts/export_app_data.py (SELECTs only)
        ▼
   JSON files ──► SvelteKit app (prerendered) ──► Cloudflare Workers, behind Cloudflare Access
```

- **Models** (Python 3.11): a Dixon-Coles goals model (time decay, ridge shrinkage, recent scoring level) plus a simulator for halves, goal timing and combinations; negative binomial count models for corners, cards and shots; a player layer; and, for the European cups, a version that rates every club on one scale from its domestic and cup results together. Held-out results, and what was tried and dropped, are in [docs/goals-model-report.md](docs/goals-model-report.md) and [docs/model-card.md](docs/model-card.md).
- **Honesty rules:** one official prediction per match per model version, written before kickoff and protected by database triggers; every market is settled by the same function that priced it; probabilities are checked on matches the rules never saw.
- **What it cannot do:** it does not know injuries or suspensions (lineups are used only once announced), and in our own tests bookmaker prices predicted results better than ours. Backing our numbers against bookmaker prices lost money, and the site says so.

## Repository layout

| Path | What is there |
|---|---|
| `src/pitchside/` | the Python package: `ingest/` (data sources), `models/`, `markets/` (pricing and settlement rules), `sim/`, `settle/`, `pipeline/` (daily and lineups jobs), `odds/`, `db/` |
| `db/migrations/` | numbered SQL migrations (`python -m pitchside.db.migrate`) |
| `scripts/` | backtests, tuning, data loaders and the web data export |
| `tests/` | pytest suite (embedded Postgres, no network) |
| `web/app/` | the SvelteKit site (Svelte 5, Cloudflare adapter) |
| `data/` | club-name aliases and the committed confidence rules |
| `docs/` | model card, goals-model report, market coverage and catalogue, data sources, operations |
| `.github/workflows/` | `pipeline.yml` (daily) and `lineups.yml` (every 30 minutes) |

## Run it locally

Needs [uv](https://docs.astral.sh/uv/) and, for the site, Node 22.

```bash
uv sync                                   # Python dependencies
# create .env with DATABASE_URL=<a Postgres connection string>
uv run python -m pytest                   # tests (a few minutes; uses an embedded Postgres)
uv run ruff check src scripts tests       # lint

uv run python -m pitchside.pipeline.weekly --league ALL --days 5   # ingest, settle, predict
uv run python scripts/export_app_data.py                           # write the site's data files

cd web/app
npm ci
npm run dev                               # local dev server
npm run check && npm test && npm run build
```

`python -m pytest` is used rather than `pytest` so the `tests` package is importable.

## Configuration

| Name | Where | What |
|---|---|---|
| `DATABASE_URL` | `.env` locally, repository secret in GitHub | Postgres connection string (Supabase session pooler) |
| `CLOUDFLARE_API_TOKEN` | repository secret | lets the daily job deploy; without it the build and deploy steps are skipped |
| Cloudflare D1 `pitchside-feedback` | `web/app/wrangler.jsonc` | feedback and usage counts used by the admin page |

Never commit `.env` or any key. See [docs/operations.md](docs/operations.md) for setup, the daily job, reading the track record, and what to do when a run fails (a failed run opens a GitHub issue).

## Access

The site's front door is a public landing page at `/` (with the method, terms, privacy and responsible-gambling pages). The app itself lives under `/app` (fixtures, `/app/match/…`, `/app/results`, `/app/record`) together with `/data` and `/api`, and sits behind Cloudflare Access: visitors continue with Google and land on the fixtures. `/admin` (usage, people, feedback) is limited to the operator. Public pages load no prediction data, so none appears in their HTML.

## Documents

- [BUILD.md](BUILD.md): what is built, in what order, and the decisions behind it
- [PRODUCT.md](PRODUCT.md) and [DESIGN.md](DESIGN.md): who it is for and how it looks
- [docs/data-audit.md](docs/data-audit.md) and [docs/odds-sources.md](docs/odds-sources.md): data sources and their terms
- [docs/audit-2026-10-25.md](docs/audit-2026-10-25.md): the latest audit of the model, the pipeline and the interface, with ranked findings

## Data sources

Results and team statistics: [football-data.co.uk](https://www.football-data.co.uk). Shots and expected goals: [Understat](https://understat.com). Fixtures, lineups, cards and cup results: ESPN's public match feeds (unofficial, can change without notice). European cup history: [openfootball](https://github.com/openfootball/europe-champions-league) (public domain). Check each source's terms before any commercial use.

## Status

Experimental. Predictions are statistical estimates and can be wrong. The Terms and Privacy pages are drafts and have not been reviewed by a lawyer. Payments, a custom domain and a public launch are not done.
