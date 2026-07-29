"""
Fetches per-team, per-match xG history from Understat's internal
getLeagueData endpoint.

Understat changed its site structure around Dec 2025, breaking the old
server-rendered `var datesData = JSON.parse('...')` pattern that every
established scraper (this project's earlier attempts, and e.g.
oseymour/ScraperFC's still-open GitHub issue #71 as of this writing) was
built against. The real replacement, found via scripts/probe_epl_sources.py
after three probe passes plus checking how other scrapers are currently
coping (none had a working fix yet) and testing a candidate endpoint
directly: understat.com/getLeagueData/{league}/{season_start_year} - an
internal XHR endpoint returning real JSON, not embedded in the page at
all anymore.

Confirmed real response shape (GET .../getLeagueData/EPL/2025, 530KB):
    {
      "teams": {
        "<team_id>": {
          "id": "<team_id>",
          "title": "Aston Villa",
          "history": [
            {
              "h_a": "h" | "a",
              "xG": 0.318601, "xGA": 1.40098,
              "npxG": 0.318601, "npxGA": 1.40098,   # non-penalty xG
              "npxGD": -1.082379,                    # npxG - npxGA, this match
              "ppda": {"att": 227, "def": 12},        # passes per defensive action (pressing)
              "ppda_allowed": {"att": 146, "def": 24},
              "deep": 2, "deep_allowed": 6,           # deep completions for/against
              "scored": 0, "missed": 0,
              "xpts": 0.4258,                          # Understat's own expected points
              "result": "d" | "w" | "l",
              "date": "2025-08-16 11:30:00",
              "wins": 0, "draws": 1, "loses": 0, "pts": 1
            },
            ...
          ]
        },
        ...
      },
      "players": {...},   # not parsed here - not needed for a team-level xG model
      "dates": [...]       # not parsed here
    }

`season` is the season's *start* year (2025 for the 2025-26 season, which
is what's fully populated right now since 2026-27 hasn't started - see
`current_season_start_year()`). An empty {"teams": [], "players": [],
"dates": []} response (confirmed for /2026 - the not-yet-started season)
is not an error, just genuinely no data yet; this is left to callers to
handle (e.g. fall back to the prior completed season for early-season
model calibration), not silently masked here.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

import requests

BASE_URL = "https://understat.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/plain, */*",
}


@dataclass
class TeamMatchXG:
    home_away: str  # "h" or "a"
    xg_for: float
    xg_against: float
    npxg_for: float
    npxg_against: float
    npxgd: float
    deep_completions_for: int
    deep_completions_against: int
    goals_scored: int
    goals_conceded: int
    expected_points: float
    result: str  # "w" / "d" / "l"
    match_date: datetime
    raw: dict = field(default_factory=dict)


@dataclass
class TeamXGHistory:
    team_id: str
    title: str
    matches: list = field(default_factory=list)  # list[TeamMatchXG], chronological


def current_season_start_year(today=None):
    """EPL seasons run August-May. If it's currently Jun/Jul (off-season,
    next season not yet started), the *upcoming* season's start year is
    still returned here - callers needing data (not just "what season is
    it") should be ready to fall back to the prior year if this season's
    getLeagueData response comes back empty (see module docstring)."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def fetch_team_xg_history(season=None, league="EPL", timeout=20):
    """Returns a dict of {team_id: TeamXGHistory} for the given season
    (defaults to current_season_start_year()). Raises on network/parsing
    failure at the top level so callers can decide how to degrade (this
    source is optional, same as every source in this project). An empty
    dict is a valid, non-error result (season hasn't started - see module
    docstring), not raised as an exception."""
    season = season if season is not None else current_season_start_year()
    url = f"{BASE_URL}/getLeagueData/{league}/{season}"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    teams_raw = data.get("teams", {})
    if not teams_raw:
        return {}

    result = {}
    for team_id, team in teams_raw.items():
        matches = []
        for h in team.get("history", []):
            try:
                ppda = h.get("ppda", {})
                matches.append(
                    TeamMatchXG(
                        home_away=h["h_a"],
                        xg_for=float(h["xG"]),
                        xg_against=float(h["xGA"]),
                        npxg_for=float(h["npxG"]),
                        npxg_against=float(h["npxGA"]),
                        npxgd=float(h["npxGD"]),
                        deep_completions_for=int(h.get("deep", 0)),
                        deep_completions_against=int(h.get("deep_allowed", 0)),
                        goals_scored=int(h["scored"]),
                        goals_conceded=int(h["missed"]),
                        expected_points=float(h["xpts"]),
                        result=h["result"],
                        match_date=datetime.strptime(h["date"], "%Y-%m-%d %H:%M:%S"),
                        raw=h,
                    )
                )
            except (KeyError, ValueError, TypeError):
                # skip malformed rows rather than failing the whole team
                continue
        result[team_id] = TeamXGHistory(
            team_id=team_id,
            title=team.get("title", ""),
            matches=matches,
        )

    return result
