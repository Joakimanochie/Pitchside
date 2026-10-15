"""Announced lineups from ESPN's public match summary (unofficial API: it can change without notice).

A summary has no roster until the club names its team, about an hour before kickoff. `parse_summary` then returns each side's starters,
bench and formation. `match_names` ties ESPN's spelling of a player to the spelling in our shot data (Understat).
"""
import difflib
import re
import unicodedata

import requests

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary"


def parse_summary(payload: dict) -> dict[str, dict] | None:
    """{'home': {'formation', 'starters', 'bench'}, 'away': {...}} once both elevens are named, else None."""
    out = {}
    for r in payload.get("rosters") or []:
        players = r.get("roster") or []
        starters = [p["athlete"]["displayName"] for p in players if p.get("starter")]
        if len(starters) < 11:
            return None
        bench = [p["athlete"]["displayName"] for p in players if not p.get("starter")]
        out[r["homeAway"]] = {"formation": r.get("formation"), "starters": starters, "bench": bench}
    return out if set(out) == {"home", "away"} else None


def fetch_lineup(espn_code: str, event_id: str, session: requests.Session | None = None) -> dict[str, dict] | None:
    r = (session or requests).get(SUMMARY.format(code=espn_code), params={"event": event_id}, timeout=30)
    r.raise_for_status()
    return parse_summary(r.json())


def norm(name: str) -> str:
    """Lower-case, accents and punctuation removed: 'N’Golo Kanté' and "N'Golo Kante" compare equal."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).strip()


def _same_player(a: str, b: str) -> bool:
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    if ta and tb and ta[-1] == tb[-1] and (ta[0][0] == tb[0][0] or len(ta) == 1 or len(tb) == 1):
        return True          # same surname and first initial ("Bukayo Saka" / "B. Saka")
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88


def match_names(known: list[str], named: list[str]) -> set[str]:
    """Which of the `known` player names (our spelling) appear in `named` (the lineup's spelling)."""
    targets = [norm(n) for n in named]
    return {k for k in known if any(_same_player(norm(k), t) for t in targets)}
