# Operations

## The daily pipeline

`.github/workflows/pipeline.yml` runs every day at 07:00 UTC (and on demand from the repo's **Actions** tab). It runs
`python -m pitchside.pipeline.weekly`, which does, in order:

1. **Ingest** new results (football-data.co.uk) for the current and previous season.
2. **Settle** every stored prediction whose match has finished, and score it (log loss, Brier).
3. **Load fixtures** for the next 5 days (ESPN).
4. **Predict**: every match that has just entered the window gets exactly one official prediction per model version.
   A match already predicted is never predicted again, so daily runs cannot create competing predictions.

Each step is safe to re-run. Results are always ingested and settled even if there is nothing new to predict.

## One-time setup (only you can do this)

The job needs the Supabase connection string as a repository secret:

1. GitHub repo -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
2. Name: `DATABASE_URL`. Value: the same connection string that is in your local `.env` (Session pooler, port 5432).
3. Open the **Actions** tab, choose **Pitchside pipeline**, and press **Run workflow** to test it once.

GitHub emails the repo owner when a scheduled run fails. The run's **Summary** shows the pipeline report.

## Running it yourself

```
uv run python -m pitchside.pipeline.weekly --league ALL --days 5
uv run python -m pitchside.settle.settle          # settle only
uv run python -m pitchside.db.migrate             # apply new database migrations
```

Flags: `--force` predicts again even for matches already predicted (creates a second run; use for testing only),
`--no-ingest` skips the results download.

## Reading the track record

In Supabase's SQL editor (or any Postgres client):

```sql
select * from v_scores_by_family;   -- log loss and Brier by market family and league
select * from v_calibration;        -- when we said 70-80%, how often did it happen?
select * from v_pick_accuracy;      -- how often the flagged pick came true, per market
select * from v_unscored;           -- pushes, voids and anything we could not settle, and why
```

Live runs (`run_type = 'weekly'`) and backtests (`'backtest'`) are always kept apart. Predictions are append-only:
the database refuses to update or delete them.

## When something fails

- **Unmapped club name** (the run stops and lists the names): add the spellings to `data/team_aliases.csv`, commit, re-run.
- **"only N finished matches in the database"**: the league has not been backfilled. Run `scripts/load_history.py <LEAGUE>`.
- **ESPN or football-data unavailable**: that league's step fails without writing partial data; the other leagues still run, the job ends red, and the next day's run catches up.
