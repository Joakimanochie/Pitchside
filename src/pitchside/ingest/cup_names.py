"""Tie the club names of European cup data (openfootball, ESPN) to the clubs already in the database.

Clubs of the five leagues and the Championship already exist under their football-data names ("Internazionale", "Paris Saint-Germain"); cup sources spell them
differently ("FC Internazionale Milano (ITA)", "Paris Saint-Germain FC"). A cup name is matched to a known club of the same country by comparing the words that
identify a club (the filler words FC, CF, SSC and the like are dropped). Anything not matched confidently is a club we have no domestic data for.
"""
import difflib
import re
import unicodedata

# country code in openfootball -> the leagues whose clubs are already in the database
COUNTRY_LEAGUES = {"ENG": ("EPL", "CHAMP"), "ESP": ("LALIGA",), "GER": ("BUNDESLIGA",), "ITA": ("SERIEA",), "FRA": ("LIGUE1",)}
FILLER = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "us", "ud", "sv", "vfl", "vfb", "tsg", "bsc", "fk", "sk", "cd", "rc", "ogc", "de", "del", "la", "le", "club", "bor", "calcio", "futbol"}
# cup name (normalised) -> canonical name in the database, for clubs whose cup spelling shares too little with it
OVERRIDES = {
    "inter": "Internazionale", "fc internazionale milano": "Internazionale", "bayern munchen": "Bayern Munich", "fc bayern munchen": "Bayern Munich",
    "bor monchengladbach": "Borussia Mönchengladbach", "bayer 04 leverkusen": "Bayer Leverkusen", "1899 hoffenheim": "TSG Hoffenheim", "1 fc union berlin": "1. FC Union Berlin",
    "sc freiburg": "SC Freiburg", "fc schalke 04": "Schalke 04", "stade rennais": "Stade Rennais", "olympique marseille": "Marseille", "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon", "lille osc": "Lille", "racing club de lens": "Lens", "rc lens": "Lens", "ogc nice": "Nice", "lazio roma": "Lazio", "ss lazio": "Lazio",
    "atalanta bc": "Atalanta", "bologna fc 1909": "Bologna", "club atletico de madrid": "Atlético Madrid", "atletico madrid": "Atlético Madrid", "real sociedad de futbol": "Real Sociedad",
    "stade brestois 29": "Brest", "fc nantes": "Nantes", "toulouse fc": "Toulouse", "as monaco": "AS Monaco", "athletic club": "Athletic Club", "brighton hove albion": "Brighton & Hove Albion",
    "tottenham hotspur fc": "Tottenham Hotspur", "juventus fc": "Juventus", "fc barcelona": "Barcelona", "ac milan": "AC Milan", "paris saint germain fc": "Paris Saint-Germain",
}


# clubs of other countries that cup sources spell in several ways: normalised spelling -> the one name we keep
CANONICAL_OTHERS = {
    "sporting cp": "Sporting CP", "sporting clube de portugal": "Sporting CP", "sl benfica": "Benfica", "sport lisboa e benfica": "Benfica", "benfica": "Benfica",
    "sporting clube de braga": "Braga", "sporting braga": "Braga", "sc braga": "Braga", "braga": "Braga", "fc porto": "FC Porto", "porto": "FC Porto",
    "feyenoord rotterdam": "Feyenoord", "feyenoord": "Feyenoord", "psv": "PSV Eindhoven", "psv eindhoven": "PSV Eindhoven", "afc ajax": "Ajax", "ajax": "Ajax",
    "olympiakos piraeus": "Olympiacos", "pae olympiakos sfp": "Olympiacos", "olympiacos": "Olympiacos", "fc red bull salzburg": "FC Red Bull Salzburg", "rb salzburg": "FC Red Bull Salzburg",
    "red bull salzburg": "FC Red Bull Salzburg", "dinamo kiev": "Dynamo Kyiv", "dynamo kyiv": "Dynamo Kyiv", "celtic fc": "Celtic", "celtic": "Celtic", "rangers fc": "Rangers", "rangers": "Rangers",
    "club brugge kv": "Club Brugge", "club brugge": "Club Brugge", "kaa gent": "Gent", "krc genk": "Genk", "rsc anderlecht": "Anderlecht", "standard liege": "Standard Liège",
    "fenerbahce": "Fenerbahçe", "besiktas": "Beşiktaş", "istanbul basaksehir": "İstanbul Başakşehir", "zenit st petersburg": "Zenit St. Petersburg", "fk crvena zvezda": "Crvena Zvezda",
    "crvena zvezda": "Crvena Zvezda", "gnk dinamo zagreb": "Dinamo Zagreb", "dinamo zagreb": "Dinamo Zagreb", "ac sparta praha": "Sparta Prague", "sparta praha": "Sparta Prague",
    "sk slavia praha": "Slavia Prague", "slavia praha": "Slavia Prague", "fk shakhtar donetsk": "Shakhtar Donetsk", "shakhtar donetsk": "Shakhtar Donetsk", "fc kobenhavn": "FC København",
    "pfc ludogorets razgrad": "Ludogorets", "royale union saint gilloise": "Union Saint-Gilloise", "union saint gilloise": "Union Saint-Gilloise", "sk sturm graz": "Sturm Graz",
    "sturm graz": "Sturm Graz", "qarabag agdam fk": "Qarabağ", "qarabag fk": "Qarabağ", "bsc young boys": "Young Boys", "young boys": "Young Boys", "fc basel 1893": "Basel",
    "rapid vienna": "Rapid Wien", "fc zorya luhansk": "Zorya Lugansk", "cska moscow": "CSKA Moskva", "spartak moscow": "Spartak Moskva", "rigas futbola skola": "FK RFS",
    "galatasaray sk": "Galatasaray", "galatasaray": "Galatasaray", "as monaco fc": "AS Monaco",
}
# a code that is not one of the five big countries but whose clubs play in one of their leagues
POOL_COUNTRY = {"MCO": "France"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.replace("-", " "))).strip()


def _words(name: str) -> set[str]:
    return {t for t in norm(name).split() if t not in FILLER and not t.isdigit()}


def match_known(name: str, known: list[str]) -> str | None:
    """The database club this cup name refers to, or None. `known` are canonical names of clubs of the right country."""
    key = norm(name)
    if key in OVERRIDES and OVERRIDES[key] in known:
        return OVERRIDES[key]
    nk = {k: norm(k) for k in known}
    for k, v in nk.items():
        if v == key:
            return k
    cw = _words(name)
    best, best_score = None, 0.0
    for k in known:
        kw = _words(k)
        if not cw or not kw:
            continue
        overlap = len(cw & kw) / max(len(cw), len(kw))
        ratio = difflib.SequenceMatcher(None, key, nk[k]).ratio()
        score = max(overlap, ratio if ratio >= 0.9 else 0.0)
        if cw <= kw or kw <= cw:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = k, score
    return best if best_score >= 0.85 else None
