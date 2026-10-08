"""Goal events with minutes, from Understat shot events, loaded into `match_events`.

For every finished match we keep the goals only if they can be trusted: the goals credited to each side must add up to the
real full-time score (football-data) and be consistent with the real half-time score. A match that fails either check is
NOT loaded and is flagged `goal_minutes = false` in matches.source_ids, so path-dependent markets are never settled from
doubtful data. A match with verified goals (including 0-0) is flagged `goal_minutes = true`.

Conventions:
  - `team_id` of a goal event is the side CREDITED with the goal. For an own goal, Understat's `team` is the team of the
    player who scored it, so the credit goes to the opponent (checked: 99.7% of La Liga 2025 scores match with this reading).
  - Understat gives a minute (0-99) but no half. The half is assigned from the half-time score: for each side, the first
    `ht` goals in time order are first-half goals.
"""
import json

import pandas as pd
import psycopg

from pitchside.db.teams import TeamResolver

SOURCE = "understat"
GOAL_RESULTS = {"Goal", "Own Goal"}
MAX_FIRST_HALF_MINUTE = 60   # a goal flagged first-half later than this means the data and half-time score disagree
MIN_SECOND_HALF_MINUTE = 40  # likewise for second-half goals this early


def credited_goals(events: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """One row per goal with the credited side ('home' or 'away'). Own goals are credited to the opponent."""
    if events.empty or "result" not in events.columns:
        return pd.DataFrame(columns=["game_id", "side", "minute", "player", "assist", "xg", "situation", "own_goal", "shot_id"])
    g = events[events["result"].isin(GOAL_RESULTS)].merge(
        schedule[["game_id", "home_team", "away_team"]], on="game_id", how="inner")
    own = g["result"] == "Own Goal"
    credited_home = (g["team"] == g["home_team"]) ^ own
    out = pd.DataFrame({
        "game_id": g["game_id"], "side": credited_home.map({True: "home", False: "away"}), "minute": g["minute"].astype(int),
        "player": g["player"], "assist": g["assist_player"], "xg": g["xg"], "situation": g["situation"],
        "own_goal": own, "shot_id": g["shot_id"],
    })
    return out.sort_values(["game_id", "minute"], kind="stable").reset_index(drop=True)


def assign_periods(goals: pd.DataFrame, ft: tuple[int, int], ht: tuple[int, int]) -> tuple[pd.DataFrame | None, str]:
    """Add a 'period' column (1 or 2) using the half-time score. Returns (goals, '') or (None, reason)."""
    parts = []
    for side, ft_n, ht_n in (("home", ft[0], ht[0]), ("away", ft[1], ht[1])):
        mine = goals[goals["side"] == side].sort_values("minute", kind="stable").copy()
        if len(mine) != ft_n:
            return None, f"{side} goals {len(mine)} != full-time {ft_n}"
        if ht_n > ft_n:
            return None, f"{side} half-time {ht_n} > full-time {ft_n}"
        mine["period"] = [1] * ht_n + [2] * (ft_n - ht_n)
        parts.append(mine)
    out = pd.concat(parts).sort_values(["minute", "period"], kind="stable").reset_index(drop=True)
    if ((out["period"] == 1) & (out["minute"] > MAX_FIRST_HALF_MINUTE)).any():
        return None, "a first-half goal is later than minute 60"
    if ((out["period"] == 2) & (out["minute"] < MIN_SECOND_HALF_MINUTE)).any():
        return None, "a second-half goal is earlier than minute 40"
    return out, ""


def _clean(value):
    """Understat leaves some fields empty (pandas NA): treat those as unknown, never as a value."""
    return None if value is None or pd.isna(value) else value


PENALTY_XG = (0.70, 0.80)  # a penalty is worth about 0.76 xG; Understat leaves the situation of penalties empty


def _event_type(row) -> str:
    if row.own_goal:
        return "own_goal"
    situation, xg = _clean(row.situation), _clean(row.xg)
    is_penalty = situation == "Penalty" or (situation is None and xg is not None and PENALTY_XG[0] <= float(xg) <= PENALTY_XG[1])
    return "penalty_goal" if is_penalty else "goal"


def load_goals(conn: psycopg.Connection, league_id: str, season: int, events: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """Load verified goal events for one league-season. Idempotent: a re-run replaces that match's Understat goals."""
    resolver = TeamResolver(conn)
    ids = resolver.resolve_all(SOURCE, [*schedule["home_team"], *schedule["away_team"]])
    db = {
        (home, away): (mid, fh, fa, hh, ha)
        for mid, home, away, fh, fa, hh, ha in conn.execute(
            "SELECT id, home_team_id, away_team_id, ft_home, ft_away, ht_home, ht_away FROM matches "
            "WHERE league_id = %s AND season = %s AND status = 'finished'", (league_id, season))
    }
    goals = credited_goals(events, schedule)
    by_game = {gid: grp for gid, grp in goals.groupby("game_id")}
    summary = {"games": len(schedule), "loaded": 0, "goals": 0, "not_finished_in_db": 0, "no_half_time_score": 0, "inconsistent": []}
    event_rows, flagged = [], []
    for s in schedule.itertuples(index=False):
        key = (ids[s.home_team], ids[s.away_team])
        if key not in db:
            summary["not_finished_in_db"] += 1
            continue
        match_id, fh, fa, hh, ha = db[key]
        if hh is None or ha is None:
            summary["no_half_time_score"] += 1
            flagged.append((match_id, str(s.game_id), False))
            continue
        mine = by_game.get(s.game_id, goals.iloc[0:0])
        checked, reason = assign_periods(mine, (fh, fa), (hh, ha))
        if checked is None:
            summary["inconsistent"].append((str(s.game_id), s.home_team, s.away_team, reason))
            flagged.append((match_id, str(s.game_id), False))
            continue
        flagged.append((match_id, str(s.game_id), True))
        summary["loaded"] += 1
        for r in checked.itertuples(index=False):
            team_id = key[0] if r.side == "home" else key[1]
            details = {"xg": None if pd.isna(r.xg) else float(r.xg), "situation": _clean(r.situation), "assist": _clean(r.assist),
                       "side": r.side, "understat_shot_id": None if pd.isna(r.shot_id) else int(r.shot_id)}
            event_rows.append((match_id, team_id, _event_type(r), int(r.period), int(r.minute), None if pd.isna(r.player) else r.player,
                               json.dumps(details)))
            summary["goals"] += 1

    with conn.cursor() as cur:
        cur.executemany(
            "DELETE FROM match_events WHERE match_id = %s AND source = 'understat' AND event_type IN ('goal', 'own_goal', 'penalty_goal')",
            [(m,) for m, _, _ in flagged])
        cur.executemany(
            "INSERT INTO match_events (match_id, team_id, event_type, period, minute, player_name, details, source) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'understat')", event_rows)
        cur.executemany(
            "UPDATE matches SET source_ids = source_ids || jsonb_build_object('understat', %s::text, 'goal_minutes', %s::boolean) WHERE id = %s",
            [(gid, ok, m) for m, gid, ok in flagged])
    return summary
