"""The daily "odds" slips: for each day's fixtures, combinations of the model's most likely outcomes that multiply up to about 2, 3, 5, 10, 20 and 30 odds.

    uv run python -m pitchside.accas

How a slip is built (RULES below), in plain words:
  * one leg per match, only from the markets and lines listed in data/market_availability.json for the match's league (result, double chance, total goals, a team's goals,
    both teams to score), only for the five rated leagues, only matches that have not kicked off;
  * a leg's fair odds are 1 / probability. The slip's fair odds are the product of its legs'; bookmakers pay less because each price carries their margin;
  * for a target T the safest legs are taken first (highest probability, but never above 95%: below about 1.05 a site will not take the bet), and the last leg is the smallest price that lands the total
    over T. If the day has too few matches to get there, the ceiling comes down step by step, but never below P_MIN (80%): a slip is made only when confident legs can reach its target,
    so a quiet day gets only the small slips, or none, rather than a big slip padded with weak legs;
  * the chance that the whole slip wins is the product of the legs' probabilities. It is about 1 / odds: a 30-odds slip wins roughly once in thirty days however it is built.
    No selection rule changes that, so the page shows the figure instead of a label like "sure".
A slip is stored once per day and target before its first kickoff and never changed; how it turned out is read from the settlements of its legs.
"""
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from pitchside.confidence import RATED_LEAGUES
from pitchside.db.migrate import _load_env, apply_migrations

RULES = "acca-2"       # acca-1 had a 30% leg floor, which let quiet days pad big slips with 45% legs
TARGETS = (2, 3, 5, 10, 20, 30)
P_MAX = 0.95            # fair odds under about 1.05 are not accepted by betting sites
P_MIN = 0.80            # a slip is for confident picks: no leg below this, so a quiet day gets no big slip rather than a padded one
THETAS = [round(P_MAX - 0.02 * i, 2) for i in range(33)]      # the probability ceiling, lowered until the day can reach the target
UK = ZoneInfo("Europe/London")
TOTAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
TEAM_LINES = (0.5, 1.5, 2.5)
# Markets listed by every betting site we know of. This is a fixed list, not a live check of any one site: a site may drop a market for a particular match.
WIDELY_OFFERED = {"1x2": None, "double_chance": None, "ou_total": TOTAL_LINES, "ou_home": TEAM_LINES, "ou_away": TEAM_LINES, "btts": None}


@dataclass(frozen=True)
class Leg:
    prediction_id: int
    match_id: int
    market_id: str
    line: float | None
    selection: str
    p: float

    @property
    def odds(self) -> float:
        return 1.0 / self.p


AVAILABILITY_PATH = Path(__file__).resolve().parents[2] / "data" / "market_availability.json"


@lru_cache(maxsize=4)
def load_availability(path: Path = AVAILABILITY_PATH) -> dict:
    """The site's market list from data/market_availability.json; the built-in list when the file is missing so the pipeline never stops on it."""
    if not path.exists():
        return {"site": "betting sites", "site_names": {}, "default": {"confirmed_on": None, "lines_confirmed": False, "markets": WIDELY_OFFERED}, "leagues": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def league_markets(avail: dict, league: str | None) -> dict:
    entry = avail.get("leagues", {}).get(league or "", {})
    return entry.get("markets") or avail["default"]["markets"]


def offered(market_id: str, line: float | None, league: str | None = None, avail: dict | None = None) -> bool:
    """Whether the site lists this market (and line) for a match of `league`."""
    markets = league_markets(avail or load_availability(), league)
    if market_id not in markets:
        return False
    lines = markets[market_id]
    return lines is None or (line is not None and round(float(line), 2) in lines)


def site_market(market_id: str, home: str, away: str, avail: dict | None = None) -> str | None:
    """The name of the market on the site, so a user knows where to look: 'Over/Under', 'GG/NG', 'Arsenal Over/Under'."""
    name = (avail or load_availability()).get("site_names", {}).get(market_id)
    return name.format(home=home, away=away) if name else None


def build_slip(by_match: dict[int, list[Leg]], target: float) -> list[Leg] | None:
    """Legs (one per match) whose odds multiply to at least `target` and as close above it as the day allows, or None if the day cannot reach it."""
    for theta in THETAS:
        best = {}
        for mid, legs in by_match.items():
            ok = [leg for leg in legs if P_MIN <= leg.p <= theta]
            if ok:
                best[mid] = max(ok, key=lambda leg: (leg.p, leg.market_id, leg.selection))
        order = sorted(best.values(), key=lambda leg: (-leg.p, leg.match_id))
        chosen: list[Leg] = []
        used: set[int] = set()
        prod = 1.0
        done = False
        for safe in order:
            need = target / prod
            if safe.odds >= need:       # this safe leg would overshoot: finish with the smallest price that still gets there
                finishers = [leg for mid, legs in by_match.items() if mid not in used for leg in legs if P_MIN <= leg.p <= P_MAX and leg.odds >= need]
                chosen.append(min(finishers, key=lambda leg: (leg.odds, leg.match_id, leg.market_id, leg.selection)))
                done = True
                break
            chosen.append(safe)
            used.add(safe.match_id)
            prod *= safe.odds
        if done:
            return chosen
    return None


def win_probability(legs: list[Leg]) -> float:
    out = 1.0
    for leg in legs:
        out *= leg.p
    return out


def fair_odds(legs: list[Leg]) -> float:
    out = 1.0
    for leg in legs:
        out *= leg.odds
    return out


def _candidates(conn: psycopg.Connection, now: datetime) -> dict:
    """{slip_date: {match_id: [Leg]}} from the newest goals-model run of every upcoming match in a rated league."""
    runs, leagues = {}, {}
    for mid, run, league in conn.execute(      # the newest goals-model run of each upcoming match (every run writes one context row per match)
            "SELECT DISTINCT ON (c.match_id) c.match_id, c.run_id, m.league_id FROM prediction_context c JOIN prediction_runs r ON r.id = c.run_id JOIN matches m ON m.id = c.match_id "
            "WHERE m.status = 'scheduled' AND m.kickoff > %s AND m.league_id = ANY(%s) AND r.run_type = 'weekly' AND r.model_version_id LIKE 'goals-dc-%%' "
            "ORDER BY c.match_id, r.created_at DESC", (now, list(RATED_LEAGUES))):
        runs[mid], leagues[mid] = run, league
    if not runs:
        return {}
    avail = load_availability()
    rows = conn.execute(
        "SELECT p.id, p.match_id, p.market_id, p.line, p.selection, p.probability, m.kickoff, p.run_id FROM predictions p JOIN matches m ON m.id = p.match_id "
        "WHERE p.match_id = ANY(%s) AND p.market_id = ANY(%s) AND p.run_id = ANY(%s)",
        (list(runs), list(WIDELY_OFFERED), list(set(runs.values())))).fetchall()
    rows = [r[:7] for r in rows if r[7] == runs[r[1]]]
    days: dict = {}
    for pid, mid, market, line, sel, prob, kickoff in rows:
        line = None if line is None else float(line)
        if not offered(market, line, leagues[mid], avail):
            continue
        day = kickoff.astimezone(UK).date()
        days.setdefault(day, {}).setdefault(mid, []).append(Leg(pid, mid, market, line, sel, float(prob)))
    return days


def build_slips(conn: psycopg.Connection, now: datetime | None = None) -> dict:
    """Store the slips of every upcoming day that does not have them yet. Returns {'days', 'slips'}."""
    now = now or datetime.now(UTC)
    made = 0
    days = _candidates(conn, now)
    for day, by_match in sorted(days.items()):
        existing = {float(t) for (t,) in conn.execute("SELECT target_odds FROM accumulators WHERE slip_date = %s", (day,))}
        for target in TARGETS:
            if float(target) in existing:
                continue
            legs = build_slip(by_match, target)
            if not legs:
                continue
            acc = conn.execute(
                "INSERT INTO accumulators (slip_date, target_odds, fair_odds, win_probability, rules) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (day, target, round(fair_odds(legs), 3), round(win_probability(legs), 7), RULES)).fetchone()[0]
            for i, leg in enumerate(legs):
                conn.execute("INSERT INTO accumulator_legs (accumulator_id, position, prediction_id, match_id) VALUES (%s,%s,%s,%s)", (acc, i, leg.prediction_id, leg.match_id))
            made += 1
    conn.commit()
    return {"days": len(days), "slips": made}


def label(market_id: str, line: float | None, selection: str, home: str, away: str) -> str:
    """The bet as a betting site words it."""
    n = None if line is None else f"{line:g}"
    if market_id == "1x2":
        return {"home": f"{home} to win", "away": f"{away} to win", "draw": "Draw"}[selection]
    if market_id == "double_chance":
        return {"1x": f"{home} or draw", "x2": f"{away} or draw", "12": f"{home} or {away} to win"}[selection]
    if market_id == "ou_total":
        return f"{selection.capitalize()} {n} goals"
    if market_id in ("ou_home", "ou_away"):
        return f"{home if market_id == 'ou_home' else away} {selection} {n} goals"
    if market_id == "btts":
        return "Both teams to score (GG)" if selection == "yes" else "Both teams not to score (NG)"
    return f"{market_id} {selection}"


if __name__ == "__main__":
    _load_env()
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        apply_migrations(c)
        print(build_slips(c))
