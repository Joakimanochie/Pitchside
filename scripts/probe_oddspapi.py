"""One-off check of OddsPapi v4 (https://oddspapi.io/en/docs) for the Odds tab: can the key see SportyBet, and which markets and lines does SportyBet list on a real
upcoming match?

Reads the key from the ODDS_API_KEY environment variable (a GitHub secret in Actions, or a line in the git-ignored .env locally). It never prints the key.
The free plan allows 250 billable requests a month (/v4/account is free), so this makes about 6: tournaments, bookmakers, markets, fixtures (one or two) and one odds call.

    uv run python scripts/probe_oddspapi.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASE = "https://api.oddspapi.io/v4"
FOOTBALL = 10
SITES = ["sportybet", "1xbet", "bet365", "betway", "bet9ja"]
# (category, tournament) as OddsPapi names them, compared lower-case with spaces removed.
LEAGUES = {"EPL": ("england", "premierleague"), "LALIGA": ("spain", "laliga"), "BUNDESLIGA": ("germany", "bundesliga"), "SERIEA": ("italy", "seriea"),
           "LIGUE1": ("france", "ligue1"), "CHAMP": ("england", "championship")}
COOLDOWN = {"/fixtures": 2.1, "/odds": 0.6}      # seconds the docs ask us to leave between calls to one endpoint; the others are 1 s


def load_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "").strip().strip("\"'")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ODDS_API_KEY":
                key = value.strip().strip("\"'")
    return key


def call(path: str, key: str, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode({'apiKey': key, **params})}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "pitchside-probe"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        out = {"error": e.code, "message": e.read().decode("utf-8", "replace")[:300].replace(key, "<key>")}
    time.sleep(COOLDOWN.get(path, 1.1))
    return out


def failed(data) -> bool:
    return isinstance(data, dict) and "error" in data


def norm(s) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def rows(data):
    """The docs describe arrays; accept an object that wraps one."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and not failed(data):
        return next((v for v in data.values() if isinstance(v, list)), [])
    return []


def quota(key: str, label: str) -> None:
    acct = call("/account", key)
    print(f"Quota {label}:", acct if failed(acct) else {k: acct.get(k) for k in ("request_limit", "request_count")})


def main() -> int:
    key = load_key()
    if not key:
        print("ODDS_API_KEY is not set (environment or .env).")
        return 2
    quota(key, "before")

    tours = call("/tournaments", key, sportId=FOOTBALL)
    if failed(tours):
        print("Tournaments call failed:", tours)
        return 1
    found: dict[str, int] = {}
    print("\nOur leagues in OddsPapi (football = sportId 10):")
    for lg, (cat, name) in LEAGUES.items():
        hit = next((t for t in rows(tours) if norm(t.get("categoryName")) == cat and norm(t.get("tournamentName")) == name), None)
        if hit:
            found[lg] = hit["tournamentId"]
        print(f"  {lg:11s}", f"tournamentId {hit['tournamentId']}  upcoming fixtures: {hit.get('upcomingFixtures')}" if hit else "not found by name")
    cups = [(t.get("tournamentId"), t.get("tournamentName")) for t in rows(tours) if norm(t.get("tournamentName")) in ("uefachampionsleague", "uefaeuropaleague", "championsleague", "europaleague")]
    print("  cups:", cups or "not found by name")

    books = call("/bookmakers", key)
    slugs: dict[str, dict] = {}
    if failed(books):
        print("\nBookmakers call failed:", books)
    else:
        slugs = {b.get("slug"): b for b in rows(books)}
        print(f"\nBookmakers visible to this key: {len(slugs)}")
        for s in SITES:
            print(f"  {s:10s}", "present" if s in slugs else "not in the list")
    sites = [s for s in SITES if s in slugs] or ["sportybet"]

    markets = call("/markets", key)
    meta: dict[int, dict] = {}
    if failed(markets):
        print("\nMarkets call failed:", markets)
    else:
        for m in rows(markets):
            meta[int(m["marketId"])] = m
        names = sorted({m.get("marketName", "?") for m in meta.values()})
        print(f"\n{len(meta)} markets in the catalogue ({len(names)} names). Names mentioning double / team / goals / score:")
        for n in names:
            if any(t in n.lower() for t in ("double", "team", "score", "goals")):
                print("  ", n)

    today = datetime.now(UTC).date()
    fixture = None
    league = None
    tried = 0
    for lg, tid in found.items():
        if tried == 2:
            break
        tried += 1
        fx = call("/fixtures", key, tournamentId=tid, **{"from": today.isoformat(), "to": (today + timedelta(days=4)).isoformat()}, statusId=0, hasOdds="true", bookmakers="sportybet")
        if failed(fx):
            print(f"\nFixtures call failed for {lg}:", fx)
            continue
        if rows(fx):
            fixture, league = rows(fx)[0], lg
            break
    if not fixture:
        print("\nNo upcoming fixtures with SportyBet prices found in the next 4 days (first two leagues tried).")
        quota(key, "after")
        return 1
    print(f"\nProbe match: {fixture.get('participant1Name')} v {fixture.get('participant2Name')} ({league}, fixtureId {fixture['fixtureId']})")

    data = call("/odds", key, fixtureId=fixture["fixtureId"], bookmakers=",".join(sites), oddsFormat="decimal")
    if failed(data):
        print("Odds call failed:", data)
        quota(key, "after")
        return 1
    book_odds = data.get("bookmakerOdds") or {}
    for site in sites:
        info = book_odds.get(site)
        if not info:
            print(f"\n{site}: no prices on this match")
            continue
        groups: dict[tuple, list] = defaultdict(list)
        live = 0
        unknown = 0
        for mid, market in (info.get("markets") or {}).items():
            m = meta.get(int(mid))
            unknown += m is None
            prices = [p for o in (market.get("outcomes") or {}).values() for p in (o.get("players") or {}).values() if p.get("price")]
            live += bool(market.get("marketActive", True) and any(p.get("active", True) for p in prices))
            groups[(m.get("marketName") if m else f"market {mid}", m.get("period") if m else "?")].append(m.get("handicap") if m else None)
        print(f"\n{site}: {len(info.get('markets') or {})} markets on this match ({live} open, {unknown} not in the catalogue), {len(groups)} kinds. Full-time kinds and their lines:")
        shown = sorted(groups.items(), key=lambda kv: (kv[0][1] not in ("fulltime", "result"), kv[0][0]))
        for (name, period), lines in shown[:45 if site == "sportybet" else 12]:
            vals = sorted(v for v in lines if v is not None)
            print(f"  {name[:38]:38s} {period:9s} {len(lines):3d}  {vals[:14]}{' ...' if len(vals) > 14 else ''}")
        if len(shown) > (45 if site == "sportybet" else 12):
            print(f"  ... and {len(shown) - (45 if site == 'sportybet' else 12)} more kinds")
    quota(key, "after")
    return 0


if __name__ == "__main__":
    sys.exit(main())
