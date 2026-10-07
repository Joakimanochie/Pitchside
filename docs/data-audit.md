# Data audit (Phase 0)

Run on 2026-10-07 with `scripts/audit_footballdata.py`, `scripts/audit_soccerdata.py` and ad-hoc checks. Raw pulls are in `data/raw/` (git-ignored), summary tables in `data/processed/`. `soccerdata` version 1.9.1.

Status: **draft for HEO review.** Phase 0 is done when HEO agrees the v1 scope at the bottom.

## 1. Source by source

| Source | Verdict | What we verified |
|---|---|---|
| **football-data.co.uk CSVs** | Works. Backbone for families A, B, F, G, H. | All Big 5 leagues, 2025/26 (complete) and 2026/27 (to 20 Sep). Per match: full-time and half-time goals and result, shots, shots on target, fouls, corners, yellow and red cards, many bookmaker odds (opening and closing, 1X2, over/under 2.5, Asian handicap). 100% of rows filled for all of these. **Referee: Premier League only.** **xG (`HxG`, `AxG`): only in the 2026/27 files**, not 2025/26. No goal minutes, scorers, offsides, tackles. |
| **football-data.co.uk `fixtures.csv`** | Not usable for fixtures. | Stale (2-5 Oct) and contains only lower leagues (Conference, League 1/2, Scottish, Spanish 2nd tier), none of the Big 5. |
| **Understat** (`soccerdata`) | Works. Source for goal minutes, scorers, xG, player stats. | Premier League 2025/26: schedule (380), team match stats (380 rows, 29 cols), **player match stats (11,490 rows, 24 cols)**, **shot events (9,524 rows, 21 cols)**. Schedules also load for La Liga, Bundesliga, Serie A, Ligue 1. Player and shot tables not yet pulled for the other four leagues (same code path, to confirm in Phase 1b). |
| **WhoScored** (`soccerdata`) | Works, but slow and fragile. Only source for tackles, offsides, substitutions and minute-level corners and cards. | One Premier League match returned 1,543 events with minute and player: Tackle 36, Foul 34, CornerAwarded 26, OffsideGiven 4, Card 3, SubstitutionOn/Off 9, Goal 6, shots, passes. Schedules load for all Big 5. **Not yet measured:** time and failure rate for a full season (380 matches per league). Treat as a scraper that can break. |
| **ESPN public JSON** (`site.api.espn.com`, not `soccerdata`'s reader) | Works. Best source for upcoming fixtures and lineups. | Scoreboard lists upcoming fixtures for all Big 5 (e.g. Leeds at Arsenal, 2026-10-10). For finished matches: both lineups (20 each) with starter flag, position, subbed in/out, and per-player stats (appearances, fouls committed and suffered, shots, shots on target, goals, assists, yellow and red cards, saves). Team box score includes offsides, corners won, possession, passes, crosses. **No tackles.** Lineups are empty before the match (expected; confirmed about 1 hour before kickoff). Unofficial, undocumented API: can change without notice. |
| **ClubElo** | Down when tested. | `api.clubelo.com` returned HTTP 502 on three attempts. Server-side fault. Fallback: compute our own Elo from results, which we need anyway for non-listed teams. Retry later. |
| **FotMob** | Not available. | BUILD.md assumed `soccerdata.FotMob`. Version 1.9.1 does not have it (it has ClubElo, ESPN, FBref, MatchHistory, SoFIFA, Sofascore, Understat, WhoScored). |
| **Sofascore** (`soccerdata`) | Blocked. | Connection refused on the API. Not relied on. |
| **FBref** | Not used. | Lost its Opta licence in Jan 2026 (see BUILD.md). |
| **Predicted lineups, injuries, suspensions** | **Gap.** | Nothing verified yet that gives expected lineups before the confirmed ones. Needed for player markets and confidence. Candidate: injury and suspension pages, club announcements. Not yet tested. |
| **Transfermarkt datasets (market values)** | Not tested. | Optional feature. |

## 2. Market families against data

"Available" means a verified source has the inputs for the Big 5 historically. "Partial" means some inputs or some leagues.

| Family | Coverage | Inputs and gaps |
|---|---|---|
| **A. Result and goals** | **Available** | Full-time goals, home and away, results (football-data). Many seasons. |
| **B. Halves** | **Available** | Half-time goals in football-data. Second half is derived. |
| **C. Game flow** (1UP, lead by N, goals in a row, first/last goal, win from behind) | **Available for goals** | Goal minutes and scorers from Understat shot events (and WhoScored). Needs a goal-minute profile per league. |
| **D. Minutes** (1X2 and goals up to minute N, time of first goal) | **Available** | Same as C. |
| **E. Combos** | **Available** | Derived from the simulator. |
| **F. Corners** | **Available** for totals and per team; **partial** for first/last corner and half splits | Totals per team in football-data. First/last corner and first-half corners need minute-level events (WhoScored). |
| **G. Bookings** | **Available** for team cards; **partial** for halves and players | Team cards in football-data (referee for Premier League only). Card minutes and player cards from WhoScored or ESPN. |
| **H. Match stats** | **Partial** | Shots and shots on target: available. Offsides: ESPN team box score and WhoScored. Tackles: WhoScored only. Posts and crossbars, first-half substitutions: WhoScored events only. Team assists: Understat or ESPN. |
| **I. Players** | **Partial, weakest** | Goals, assists, shots, xG, xA: Understat. Fouls won, shots on target, cards, minutes: ESPN. Tackles: WhoScored. Lineups: ESPN only about an hour before kickoff, no source yet for earlier expected lineups. |

## 3. Risks and open items

1. **WhoScored scale and fragility.** One match works. A full season across five leagues (about 1,700 matches a season, several seasons) has not been tested for speed, blocking or failure rate. Tackles, offsides, substitutions and half-level corners depend on it.
2. **ESPN is an unofficial API.** Good coverage, no guarantee.
3. **Referee data only for the Premier League** in football-data. Card predictions for other leagues lose that feature unless another source is found.
4. **xG history is short in football-data** (2026/27 only). Understat has xG for earlier seasons.
5. **No pre-lineup source** for expected starters and injuries.
6. **ClubElo down.** Own Elo calculation is the fallback.
7. **Other leagues:** player and shot tables from Understat and the full WhoScored pull are only verified for the Premier League. Confirm in Phase 1b.
8. **Betting-site market coverage per league:** only SportyBet's Arsenal v Leeds page has been read. Smaller league pages may offer fewer markets.

## 4. Proposed v1 scope (for HEO to confirm)

- **Leagues:** Premier League pilot, then La Liga, Bundesliga, Serie A, Ligue 1.
- **Families A to E (goals, halves, game flow, minutes, combos):** in v1. Data is complete for all Big 5.
- **Families F and G (corners, team cards):** in v1 at match and team-total level. First/last corner, half splits and player cards follow if WhoScored proves reliable at scale.
- **Family H:** shots and shots on target in v1. Offsides, tackles, posts, substitutions only if WhoScored scales.
- **Family I (players):** experimental, last. Needs lineups and a stronger data source.
- Odds comparison stays out of the core, as set in BUILD.md.
