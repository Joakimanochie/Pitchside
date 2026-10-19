"""Clubs of the European cups: find the database club for a cup spelling, or create it.

Clubs of the five leagues and the Championship already exist (football-data names). A cup spelling (openfootball or ESPN) is matched to them by `cup_names.match_known`;
everything else is a club we have no domestic data for and is created on first sight, with the spelling as its canonical name and as an alias.
"""
import psycopg

from pitchside.ingest.cup_names import CANONICAL_OTHERS, POOL_COUNTRY, match_known, norm

ISO3 = {"ENG": "England", "ESP": "Spain", "GER": "Germany", "ITA": "Italy", "FRA": "France", "BEL": "Belgium", "NED": "Netherlands", "POR": "Portugal", "TUR": "Turkey",
        "AUT": "Austria", "RUS": "Russia", "GRE": "Greece", "CYP": "Cyprus", "CZE": "Czechia", "UKR": "Ukraine", "SUI": "Switzerland", "SWE": "Sweden", "CRO": "Croatia",
        "ISR": "Israel", "POL": "Poland", "DEN": "Denmark", "SRB": "Serbia", "KAZ": "Kazakhstan", "BUL": "Bulgaria", "SCO": "Scotland", "AZE": "Azerbaijan", "NOR": "Norway",
        "ROU": "Romania", "BLR": "Belarus", "SVN": "Slovenia", "HUN": "Hungary", "MDA": "Moldova", "SVK": "Slovakia", "MCO": "Monaco", "IRL": "Ireland", "FIN": "Finland", "LVA": "Latvia"}
LEAGUE_COUNTRY = {"EPL": "England", "CHAMP": "England", "LALIGA": "Spain", "BUNDESLIGA": "Germany", "SERIEA": "Italy", "LIGUE1": "France"}


class CupTeams:
    """Resolve and create clubs. Keeps its own cache so a whole file of matches costs a handful of queries."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.alias = {(s, a): t for s, a, t in conn.execute("SELECT source, alias, team_id FROM team_aliases")}
        self.names = {t: n for t, n in conn.execute("SELECT id, canonical_name FROM teams")}
        self.by_name = {n: t for t, n in self.names.items()}
        self.country = {t: c for t, c in conn.execute("SELECT id, country FROM teams")}
        self.created: list[str] = []
        self.merged: list[str] = []      # ESPN spellings tied to an existing club by name similarity, for a human to check

    def _known_of(self, country: str | None) -> list[str]:
        if not country:
            return []
        return [self.names[t] for t, c in self.country.items() if c == country]

    def _create(self, name: str, country: str | None) -> int:
        team_id = self.conn.execute(
            "INSERT INTO teams (canonical_name, country) VALUES (%s, %s) ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name RETURNING id",
            (name, country)).fetchone()[0]
        self.names[team_id], self.by_name[name], self.country[team_id] = name, team_id, country
        self.created.append(name)
        return team_id

    def resolve(self, source: str, spelling: str, country_code: str = "") -> int:
        """The club's team id; creates the club when no existing one fits. `country_code` is the three-letter code openfootball gives ('' for ESPN)."""
        hit = self.alias.get((source, spelling)) or self.alias.get(("*", spelling))
        if hit:
            return hit
        country = ISO3.get(POOL_COUNTRY.get(country_code, country_code))
        team_id = None
        canon = CANONICAL_OTHERS.get(norm(spelling))
        if canon:
            team_id = self.by_name.get(canon) or self._create(canon, country)
        if team_id is None:
            pool = self._known_of(country) if country else [n for lg in LEAGUE_COUNTRY.values() for n in self._known_of(lg)]
            found = match_known(spelling, sorted(set(pool)))
            team_id = self.by_name.get(found) if found else None
        if team_id is None and not country_code:      # ESPN gives no country: try every club we hold (a club first met under its openfootball name)
            found = match_known(spelling, sorted(self.by_name))
            team_id = self.by_name.get(found) if found else None
            if team_id is not None:
                self.merged.append(f"{spelling} -> {found}")
        if team_id is None:
            same = {n for n in self.by_name if norm(n) == norm(spelling)}
            if same:
                team_id = self.by_name[min(same)]
        if team_id is None:
            team_id = self._create(spelling, country)
        self.conn.execute("INSERT INTO team_aliases (source, alias, team_id) VALUES (%s,%s,%s) ON CONFLICT (source, alias) DO UPDATE SET team_id = EXCLUDED.team_id",
                          (source, spelling, team_id))
        self.alias[(source, spelling)] = team_id
        return team_id
