"""Draft data/processed/team_aliases_draft.csv (the curated data/team_aliases.csv is edited by hand): map every source's spelling of a club to one canonical name.

Canonical name = ESPN's full club name for the current season. Each source name is matched by
normalised text (exact first, then close match). Anything not matched confidently is written to
data/processed/team_aliases_review.csv and is NOT added: a human decides.

Run: uv run python scripts/build_team_aliases.py
"""
import csv
import difflib
import json
import re
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ESPN = {"EPL": "eng.1", "LALIGA": "esp.1", "BUNDESLIGA": "ger.1", "SERIEA": "ita.1", "LIGUE1": "fra.1"}
NOISE = re.compile(r"\b(fc|cf|afc|ac|as|ss|sc|us|rc|ud|cd|sv|fsv|tsg|vfl|vfb|1\.|rb|ssc|calcio|club|de|the)\b")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace(".", " ").replace("-", " ")
    s = NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def espn_teams(code: str) -> list[str]:
    r = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/teams", timeout=30)
    r.raise_for_status()
    return [t["team"]["displayName"] for t in r.json()["sports"][0]["leagues"][0]["teams"]]


def match(name: str, canon: dict[str, str]) -> tuple[str | None, str]:
    n = norm(name)
    if n in canon:
        return canon[n], "exact"
    # one side contains the other as whole words (e.g. "brighton" in "brighton and hove albion")
    hits = [c for k, c in canon.items() if n and (n in k.split() or k in n.split() or k.startswith(n + " ") or n.startswith(k + " "))]
    if len(set(hits)) == 1:
        return hits[0], "contains"
    close = difflib.get_close_matches(n, list(canon), n=1, cutoff=0.86)
    if close:
        return canon[close[0]], "close"
    return None, "none"


def main() -> None:
    src = json.loads((ROOT / "data" / "processed" / "source_team_names.json").read_text())
    rows, review = [], []
    for league, code in ESPN.items():
        canon_names = espn_teams(code)
        canon = {norm(c): c for c in canon_names}
        for c in canon_names:
            rows.append((league, c, "espn", c))
        for source, names in src[league].items():
            for alias in names:
                target, how = match(alias, canon)
                if target and how in ("exact", "contains"):
                    rows.append((league, target, source, alias))
                else:
                    review.append((league, source, alias, target or "", how))
    out = ROOT / "data" / "processed" / "team_aliases_draft.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["league", "canonical", "source", "alias"])
        w.writerows(sorted(set(rows)))
    rev = ROOT / "data" / "processed" / "team_aliases_review.csv"
    with rev.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["league", "source", "alias", "suggested_canonical", "match_type"])
        w.writerows(review)
    print(f"{len(set(rows))} aliases written, {len(review)} need review")
    for r in review:
        print("  REVIEW", r)


if __name__ == "__main__":
    main()
