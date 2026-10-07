"""League configuration. Leagues are data, not code: add a row here and a team alias block to add a league."""
from dataclasses import dataclass


@dataclass(frozen=True)
class League:
    id: str
    name: str
    country: str
    fd_code: str      # football-data.co.uk division code
    understat: str    # soccerdata league key
    espn_code: str
    tier: int = 1


LEAGUES: dict[str, League] = {
    lg.id: lg
    for lg in [
        League("EPL", "Premier League", "England", "E0", "ENG-Premier League", "eng.1"),
        League("LALIGA", "La Liga", "Spain", "SP1", "ESP-La Liga", "esp.1"),
        League("BUNDESLIGA", "Bundesliga", "Germany", "D1", "GER-Bundesliga", "ger.1"),
        League("SERIEA", "Serie A", "Italy", "I1", "ITA-Serie A", "ita.1"),
        League("LIGUE1", "Ligue 1", "France", "F1", "FRA-Ligue 1", "fra.1"),
    ]
}
