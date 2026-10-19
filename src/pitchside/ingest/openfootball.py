"""Champions League and Europa League results from the openfootball project (public domain, plain text on GitHub).

https://github.com/openfootball/europe-champions-league has one file per season and competition (`2023-24/cl.txt`, `2023-24/el.txt`). A line is
    18:45  AC Milan (ITA)  v Newcastle United FC (ENG)  0-0
           BSC Young Boys (SUI)  v RB Leipzig (GER)  1-3 (1-1)                       <- full time (half time)
           Arsenal FC (ENG)  v FC Porto (POR)  4-2 pen. 1-0 a.e.t. (1-0, 1-0)          <- after extra time; (full time at 90 minutes, half time)
The score of record here is the 90-minute score, because that is what every market is settled on.
"""
import re
from dataclasses import dataclass
from datetime import date

import requests

RAW = "https://raw.githubusercontent.com/openfootball/europe-champions-league/master/{season}/{comp}.txt"
DATE = re.compile(r"^\s{2}(?:[A-Z][a-z]{2}\s+)?([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
STAGE = re.compile(r"^▪\s*(.+)$")
SCORE = re.compile(r"(?:(?P<pen>\d+-\d+)\s+pen\.\s+)?(?P<ft>\d+-\d+)(?P<aet>\s+a\.e\.t\.)?\s*(?P<paren>\([^)]*\))?\s*$")
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
COUNTRY = re.compile(r"\s*\(([A-Z]{3})\)\s*$")


@dataclass(frozen=True)
class CupMatch:
    day: date
    stage: str
    home: str
    away: str
    home_country: str
    away_country: str
    ft: tuple[int, int]          # 90 minutes
    ht: tuple[int, int] | None
    extra_time: bool


def _pair(text: str) -> tuple[int, int]:
    a, b = text.split("-")
    return int(a), int(b)


def parse(text: str, season_start: int) -> list[CupMatch]:
    """Matches of one file. `season_start` is the year the season began (2023 for 2023/24); dates without a year take it from the month."""
    out: list[CupMatch] = []
    stage, day = "", None
    for line in text.splitlines():
        s = STAGE.match(line)
        if s:
            stage = s.group(1).strip()
            continue
        d = DATE.match(line)
        if d and " v " not in line:
            month = MONTHS[d.group(1)]
            year = int(d.group(3)) if d.group(3) else (season_start if month >= 7 else season_start + 1)
            day = date(year, month, int(d.group(2)))
            continue
        if " v " not in line or day is None:
            continue
        body = re.sub(r"^\s*\d\d:\d\d\s+", "", line).strip()
        m = SCORE.search(body)
        if not m:
            continue                                   # not played yet
        teams = body[: m.start()].strip()
        home, away = (t.strip() for t in teams.split(" v ", 1))
        ft, ht, aet = _pair(m.group("ft")), None, m.group("aet") is not None
        paren = m.group("paren")
        if aet:
            # after extra time the brackets hold (score at 90 minutes, half time); the score before them is the extra-time result
            nums = re.findall(r"\d+-\d+", paren or "")
            if len(nums) != 2:
                continue                               # cannot recover the 90-minute score: leave the match out
            ft, ht = _pair(nums[0]), _pair(nums[1])
        elif paren:
            nums = re.findall(r"\d+-\d+", paren)
            ht = _pair(nums[0]) if nums else None
        hc, ac = COUNTRY.search(home), COUNTRY.search(away)
        out.append(CupMatch(day, stage, COUNTRY.sub("", home).strip(), COUNTRY.sub("", away).strip(), hc.group(1) if hc else "", ac.group(1) if ac else "", ft, ht, aet))
    return out


def fetch(season_start: int, comp: str, session: requests.Session | None = None) -> list[CupMatch]:
    """comp is 'cl' or 'el'. Returns [] if the repository has no such file."""
    season = f"{season_start}-{str(season_start + 1)[2:]}"
    r = (session or requests).get(RAW.format(season=season, comp=comp), timeout=40)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    r.encoding = "utf-8"        # GitHub serves plain text without a charset, which requests would read as Latin-1
    return parse(r.text, season_start)
