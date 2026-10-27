"""One-off check of The Odds API (https://the-odds-api.com) for the Odds tab: which leagues, markets and bookmakers it covers, and what a call costs.

Reads the key from the ODDS_API_KEY environment variable (a GitHub secret in Actions, or a line in the git-ignored .env locally). It never prints the key.
Spends about 15 of the 500 free monthly credits: /sports and /events are free; /odds costs markets x regions per call.

    uv run python scripts/probe_odds_api.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://api.the-odds-api.com/v4"
LEAGUES = {"EPL": "soccer_epl", "LALIGA": "soccer_spain_la_liga", "BUNDESLIGA": "soccer_germany_bundesliga", "SERIEA": "soccer_italy_serie_a", "LIGUE1": "soccer_france_ligue_one"}
# Markets the Odds tab uses; the API names them its own way. Each is tried alone because one unknown name fails the whole request.
MARKETS = ["h2h", "totals", "btts", "double_chance", "draw_no_bet", "team_totals", "alternate_totals", "spreads"]


def load_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key and os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ODDS_API_KEY":
                key = value.strip().strip("\"'")
    return key


def call(path: str, key: str, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode({'apiKey': key, **params})}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r), {k: r.headers.get(k) for k in ("x-requests-remaining", "x-requests-used", "x-requests-last")}
    except urllib.error.HTTPError as e:
        return {"error": e.code, "message": e.read().decode("utf-8", "replace")[:200].replace(key, "<key>")}, {}


def main() -> int:
    key = load_key()
    if not key:
        print("ODDS_API_KEY is not set (environment or .env).")
        return 2

    sports, _ = call("/sports", key, all="true")
    if isinstance(sports, dict):
        print("Key was refused or the call failed:", sports)
        return 1
    soccer = [s for s in sports if s["key"].startswith("soccer_")]
    print(f"{len(soccer)} soccer competitions listed. Ours:")
    for lg, sk in LEAGUES.items():
        row = next((s for s in soccer if s["key"] == sk), None)
        print(f"  {lg:11s} {sk:28s}", f"active={row['active']}" if row else "NOT LISTED")
    cups = [s["key"] for s in soccer if "champions" in s["key"] or "europa" in s["key"] or "efl" in s["key"] or "championship" in s["title"].lower()]
    print("  other candidates:", ", ".join(cups) or "none")

    for lg, sk in LEAGUES.items():
        events, _ = call(f"/sports/{sk}/events", key)
        if isinstance(events, list) and events:
            event, league = events[0], lg
            break
    else:
        print("No upcoming events found in any of our leagues.")
        return 1
    print(f"\nProbe match: {event['home_team']} v {event['away_team']} ({league}, {event['commence_time']})")

    seen: dict[str, Counter] = {}
    books: set[str] = set()
    for market in MARKETS:
        data, hdr = call(f"/sports/{LEAGUES[league]}/events/{event['id']}/odds", key, regions="uk,eu", markets=market, oddsFormat="decimal")
        if "error" in data:
            print(f"  {market:17s} not available ({data['error']}: {data['message'][:90]})")
            continue
        lines = Counter()
        for b in data.get("bookmakers", []):
            books.add(b["key"])
            for m in b["markets"]:
                for o in m["outcomes"]:
                    if o.get("point") is not None:
                        lines[o["point"]] += 1
        seen[market] = lines
        n = sum(1 for b in data.get("bookmakers", []) if any(m["key"] == market for m in b["markets"]))
        print(f"  {market:17s} {n} bookmakers; lines: {sorted(lines) if lines else 'no line'}   (credits left {hdr.get('x-requests-remaining')}, cost {hdr.get('x-requests-last')})")

    print("\nBookmakers seen:", ", ".join(sorted(books)))
    print("SportyBet-like (sporty, 1xbet, bet9ja, betway, bet365) present:", sorted(b for b in books if any(t in b for t in ("sporty", "1xbet", "bet9ja", "betway", "bet365"))) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
