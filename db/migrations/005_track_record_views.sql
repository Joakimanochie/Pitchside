-- 005_track_record_views: the numbers behind the track record. Voids, pushes and unscorable markets are
-- excluded (outcome_value IS NULL). run_type is kept in every view so live runs and backtests never mix.

-- Accuracy by market family: mean log loss and Brier score (lower is better).
CREATE VIEW v_scores_by_family WITH (security_invoker = true) AS
SELECT model_version_id, run_type, league_id, family,
       count(*)                       AS n,
       round(avg(log_loss)::numeric, 5) AS avg_log_loss,
       round(avg(brier)::numeric, 5)    AS avg_brier
FROM v_settled
WHERE outcome_value IS NOT NULL
GROUP BY model_version_id, run_type, league_id, family;

-- Calibration: in each probability bucket, how often did the selection actually win?
CREATE VIEW v_calibration WITH (security_invoker = true) AS
SELECT model_version_id, run_type, family,
       floor(least(probability, 0.9999) * 10) / 10 AS bucket_from,
       count(*)                                    AS n,
       round(avg(probability)::numeric, 4)         AS avg_probability,
       round(avg(outcome_value)::numeric, 4)       AS hit_rate
FROM v_settled
WHERE outcome_value IS NOT NULL
GROUP BY model_version_id, run_type, family, floor(least(probability, 0.9999) * 10) / 10;

-- How often the flagged pick (most likely selection of an exclusive market) came true.
CREATE VIEW v_pick_accuracy WITH (security_invoker = true) AS
SELECT model_version_id, run_type, league_id, market_id,
       count(*)                              AS n,
       round(avg(probability)::numeric, 4)   AS avg_probability,
       round(avg(outcome_value)::numeric, 4) AS hit_rate
FROM v_settled
WHERE is_pick AND outcome_value IS NOT NULL
GROUP BY model_version_id, run_type, league_id, market_id;

-- What the settle step could not or would not score, and why.
CREATE VIEW v_unscored WITH (security_invoker = true) AS
SELECT s.result, s.observed ->> 'reason' AS reason, r.run_type, count(*) AS n
FROM settlements s
JOIN predictions p ON p.id = s.prediction_id
JOIN prediction_runs r ON r.id = p.run_id
WHERE s.outcome_value IS NULL
GROUP BY s.result, s.observed ->> 'reason', r.run_type;
