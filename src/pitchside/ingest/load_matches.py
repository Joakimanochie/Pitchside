"""Write parsed football-data matches and team stats into Postgres. Idempotent: re-running updates in place."""
import pandas as pd
import psycopg

from pitchside.db.teams import TeamResolver

SOURCE = "footballdata"


def _v(x):
    """pandas NA/NaN -> None, numpy numbers -> python numbers."""
    if x is None or pd.isna(x):
        return None
    return x.item() if hasattr(x, "item") else x


def load_footballdata(conn: psycopg.Connection, league_id: str, df: pd.DataFrame) -> dict:
    """df is the output of ingest.footballdata.load_seasons. Raises UnknownTeamsError before writing anything."""
    resolver = TeamResolver(conn)
    ids = resolver.resolve_all(SOURCE, [*df["home"], *df["away"]])

    n_matches = n_stats = 0
    for r in df.itertuples(index=False):
        home_id, away_id = ids[r.home], ids[r.away]
        match_id = conn.execute(
            "INSERT INTO matches (league_id, season, match_date, home_team_id, away_team_id, status, "
            "ft_home, ft_away, ht_home, ht_away, referee) VALUES (%s,%s,%s,%s,%s,'finished',%s,%s,%s,%s,%s) "
            "ON CONFLICT (league_id, season, home_team_id, away_team_id, match_date) DO UPDATE SET "
            "status = 'finished', ft_home = EXCLUDED.ft_home, ft_away = EXCLUDED.ft_away, "
            "ht_home = EXCLUDED.ht_home, ht_away = EXCLUDED.ht_away, referee = EXCLUDED.referee RETURNING id",
            (league_id, int(r.season), r.match_date, home_id, away_id, _v(r.ft_home), _v(r.ft_away),
             _v(r.ht_home), _v(r.ht_away), _v(r.referee)),
        ).fetchone()[0]
        n_matches += 1
        for team_id, is_home, side in ((home_id, True, "h"), (away_id, False, "a")):
            conn.execute(
                "INSERT INTO team_match_stats (match_id, team_id, is_home, shots, shots_on_target, corners, fouls, "
                "yellow_cards, red_cards, xg, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (match_id, team_id) DO UPDATE SET shots = EXCLUDED.shots, "
                "shots_on_target = EXCLUDED.shots_on_target, corners = EXCLUDED.corners, fouls = EXCLUDED.fouls, "
                "yellow_cards = EXCLUDED.yellow_cards, red_cards = EXCLUDED.red_cards, xg = EXCLUDED.xg",
                (match_id, team_id, is_home, _v(getattr(r, f"shots_{side}")), _v(getattr(r, f"sot_{side}")),
                 _v(getattr(r, f"corners_{side}")), _v(getattr(r, f"fouls_{side}")), _v(getattr(r, f"yellow_{side}")),
                 _v(getattr(r, f"red_{side}")), _v(getattr(r, f"xg_{side}")), SOURCE),
            )
            n_stats += 1
    return {"matches": n_matches, "team_stats": n_stats}
