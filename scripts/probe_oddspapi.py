"""One-off check of OddsPapi (https://docs.oddspapi.io, API v5) for the Odds tab: can the key see SportyBet, and which markets and lines does SportyBet
list on a real upcoming match?

Reads the key from the ODDS_API_KEY environment variable (a GitHub secret in Actions, or a line in the git-ignored .env locally). It never prints the key.
The free plan is said to allow about 250 requests a month, so this makes at most 6: tournaments, bookmakers, markets, fixtures (one or two) and one odds call.

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
from pathlib import Path

BASE = "https://v5.oddspapi.io/en"
FOOTBALL = 10
SITES = ["sportybet", "1xbet", "bet365", "betway"]
# (category, tournament) as OddsPapi names them, compared lower-case with spaces removed.
LEAGUES = {"EPL": ("england", "premierleague"), "LALIGA": ("spain", "laliga"), "BUNDESLIGA": ("germany", "bundesliga"), "SERIEA": ("italy", "seriea"),
           "LIGUE1": ("france", "ligue1"), "CHAMP": ("england", "championship")}


def load_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "").strip().strip("\"'")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ODDS_API_KEY":
                key = value.strip().strip("\"'")
    return key


def call(path: str, key: str, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}" if params else f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json", "User-Agent": "pitchside-probe"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            left = r.headers.get("X-RateLimit-Remaining")
            return json.load(r), left
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300].replace(key, "<key>")
        return {"error": e.code, "message": body}, None


def norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def rows(data):
    """The docs describe arrays; accept an object that wraps one."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "error" not in data:
        return next((v for v in data.values() if isinstance(v, list)), [])
    return []


def main() -> int:
    key = load_key()
    if not key:
        print("ODDS_API_KEY is not set (environment or .env).")
        return 2

    tours, _ = call("/tournaments", key, sportId=FOOTBALL)
    if isinstance(tours, dict) and "error" in tours:
        print("Tournaments call failed:", tours)
        if tours["error"] == 401:
            raw = os.environ.get("ODDS_API_KEY", "")
            stray = raw != raw.strip()
            quoted = raw.strip()[:1] in ('"', "'")
            inner_space = " " in raw.strip()
            print(f"Key as stored: {len(raw)} characters; stray whitespace: {stray}; quotes around it: {quoted}; a space inside: {inner_space}")
            old_url = "https://api.oddspapi.io/v4/sports?" + urllib.parse.urlencode({"apiKey": key})
            old = urllib.request.Request(old_url, headers={"User-Agent": "pitchside-probe"})
            try:
                with urllib.request.urlopen(old, timeout=30) as r:
                    print(f"The older v4 address ACCEPTS this key (HTTP {r.status}): this key is for the v4 API, not v5.")
            except urllib.error.HTTPError as e:
                print(f"The older v4 address also refuses it (HTTP {e.code}): {e.read().decode('utf-8', 'replace')[:120].replace(key, '<key>')}")
            except OSError as e:
                print("The older v4 address could not be reached:", e)
        return 1
    found: dict[str, int] = {}
    print("Our leagues in OddsPapi (football = sportId 10):")
    for lg, (cat, name) in LEAGUES.items():
        hit = next((t for t in rows(tours) if norm(t.get("categoryName")) == cat and norm(t.get("tournamentName")) == name), None)
        if hit:
            found[lg] = hit["tournamentId"]
        print(f"  {lg:11s}", f"tournamentId {hit['tournamentId']}" if hit else "not found by name")
    cups = [(t.get("tournamentId"), t.get("tournamentName")) for t in rows(tours) if norm(t.get("tournamentName")) in ("uefachampionsleague", "uefaeuropaleague", "championsleague", "europaleague")]
    print("  cups:", cups or "not found by name")

    books, left = call("/bookmakers", key)
    if isinstance(books, dict) and "error" in books:
        print("\nBookmakers call failed:", books)
    else:
        slugs = {b.get("slug"): b for b in rows(books)}
        print(f"\nBookmakers visible to this key: {len(slugs)}")
        for s in SITES + ["bet9ja"]:
            b = slugs.get(s)
            print(f"  {s:10s}", "present" + (f" (active={b.get('active')})" if b else "") if b else "not in this key's list")

    markets, _ = call("/markets", key, sportId=FOOTBALL)
    meta: dict[int, dict] = {}
    if isinstance(markets, dict) and "error" in markets:
        print("\nMarkets call failed:", markets)
    else:
        for m in rows(markets):
            meta[m["marketId"]] = m
        kinds: dict[str, int] = defaultdict(int)
        for m in meta.values():
            kinds[m.get("marketType", "?")] += 1
        print(f"\n{len(meta)} football markets in the catalogue; market types: {dict(sorted(kinds.items()))}")

    now = int(time.time())
    fixture = None
    for lg, tid in found.items():
        fx, _ = call("/fixtures", key, sportId=FOOTBALL, tournamentId=tid, statusId=0, startTimeFrom=now, startTimeTo=now + 4 * 86400, bookmakers="sportybet")
        if isinstance(fx, dict) and "error" in fx:
            print(f"\nFixtures call failed for {lg}:", fx)
            continue
        if rows(fx):
            fixture, league = rows(fx)[0], lg
            break
    if not fixture:
        print("\nNo upcoming fixtures found in the next 4 days for our leagues.")
        return 1
    p = fixture.get("participants", {})
    print(f"\nProbe match: {p.get('participant1Name')} v {p.get('participant2Name')} ({league}, fixtureId {fixture['fixtureId']})")
    print("  bookmaker flags on this fixture:", {k: {"hasOdds": v.get("hasOdds"), "suspended": v.get("suspended")} for k, v in (fixture.get("bookmakers") or {}).items()})

    data, left = call("/fixtures/odds", key, fixtureId=fixture["fixtureId"], bookmakers=",".join(SITES))
    if isinstance(data, dict) and "error" in data:
        print("Odds call failed:", data)
        return 1
    print(f"Requests left in the current window (header): {left}")
    odds = data.get("odds") or {}
    for site in SITES:
        quotes = list((odds.get(site) or {}).values())
        if not quotes:
            print(f"\n{site}: no prices on this match")
            continue
        by_market: dict[int, list] = defaultdict(list)
        for q in quotes:
            by_market[q["marketId"]].append(q)
        shown: dict[str, list] = defaultdict(list)
        for mid in by_market:
            m = meta.get(mid, {})
            kind = f"{m.get('marketType', 'market?')}/{m.get('period', '?')}"
            shown[kind].append(m.get("handicap", mid) if m else mid)
        print(f"\n{site}: {len(quotes)} prices in {len(by_market)} markets. By type/period (value = the line, or the market id if the catalogue lacks it):")
        for kind in sorted(shown, key=lambda k: (not k.endswith("/fulltime") and not k.endswith("/result"), k)):
            vals = sorted(shown[kind], key=lambda v: (isinstance(v, str), v))
            print(f"  {kind:34s} {len(vals):3d}  {vals[:12]}{' ...' if len(vals) > 12 else ''}")
        if site == "sportybet":
            one = next((q for q in quotes if q.get("marketId") in meta), None)
            if one:
                m = meta[one["marketId"]]
                print(f"  example: {m.get('marketName')} -> outcome {one['outcomeId']} price {one['price']} active={one.get('active')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
