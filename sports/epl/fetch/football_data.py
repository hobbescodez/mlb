"""
Fetches upcoming Premier League fixtures from football-data.org's v4 API.
Requires a free API token (X-Auth-Token header) - see
https://www.football-data.org/client/register. Read from the
FOOTBALL_DATA_TOKEN environment variable (a repo secret in CI).

Schema verified against a real authenticated fetch via
scripts/probe_epl_sources.py (this dev environment can't reach
api.football-data.org directly - see that script's docstring). Real
response for competitions/PL/matches: 380 matches for the 2026-27 season
(season.startDate 2026-08-21), each with id, utcDate, status, matchday,
stage, homeTeam/awayTeam ({id, name, shortName, tla, crest}), and score
({winner, duration, fullTime: {home, away}, halfTime: {home, away}}) -
both null pre-kickoff, populated once the match starts/finishes. An
`odds` key exists but returns {"msg": "Activate Odds-Package..."} on the
free tier - not usable here, hence still needing Kalshi/DRatings for any
market-side signal.

Also confirmed real, not assumed: this season's actual promoted/relegated
clubs (e.g. Coventry City appears in the fixture list) - exactly the kind
of detail sports/epl/teams.py's docstring says not to hardcode from
training-data guesses.

Free tier is rate-limited (10 requests/minute) - this fetcher makes one
request per call, same posture as every other source here.
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

BASE_URL = "https://api.football-data.org/v4"

HEADERS_BASE = {
    "User-Agent": "epl-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}

TOKEN_ENV_VAR = "FOOTBALL_DATA_TOKEN"


@dataclass
class FootballDataMatch:
    match_id: int
    utc_kickoff: datetime
    status: str
    matchday: int | None
    home_team: str
    away_team: str
    home_tla: str | None
    away_tla: str | None
    home_score: int | None = None
    away_score: int | None = None
    winner: str | None = None  # "HOME_TEAM" / "AWAY_TEAM" / "DRAW" / None
    raw: dict = field(default_factory=dict)


class NoTokenError(RuntimeError):
    """Raised when FOOTBALL_DATA_TOKEN isn't set - a real external
    prerequisite (free registration), not something to silently degrade
    around like a flaky scrape target."""


def fetch_upcoming_matches(status="SCHEDULED", timeout=20):
    """Returns a list of FootballDataMatch for Premier League fixtures
    matching the given status filter (default: not-yet-played). Raises
    NoTokenError if FOOTBALL_DATA_TOKEN isn't set, or on network/parsing
    failure, so callers can decide how to degrade (this source is
    optional, same as every source in this project)."""
    token = os.environ.get(TOKEN_ENV_VAR)
    if not token:
        raise NoTokenError(
            f"{TOKEN_ENV_VAR} is not set - register a free token at "
            "https://www.football-data.org/client/register and add it as "
            "a repo secret"
        )
    headers = {**HEADERS_BASE, "X-Auth-Token": token}
    r = requests.get(
        f"{BASE_URL}/competitions/PL/matches",
        headers=headers,
        params={"status": status},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()

    matches = []
    for m in data.get("matches", []):
        try:
            home = m.get("homeTeam", {})
            away = m.get("awayTeam", {})
            score = m.get("score", {})
            full_time = score.get("fullTime", {})
            matches.append(
                FootballDataMatch(
                    match_id=m["id"],
                    utc_kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
                    status=m.get("status", ""),
                    matchday=m.get("matchday"),
                    home_team=home.get("name") or home.get("shortName") or "",
                    away_team=away.get("name") or away.get("shortName") or "",
                    home_tla=home.get("tla"),
                    away_tla=away.get("tla"),
                    home_score=full_time.get("home"),
                    away_score=full_time.get("away"),
                    winner=score.get("winner"),
                    raw=m,
                )
            )
        except (KeyError, ValueError):
            # skip malformed rows rather than failing the whole source
            continue

    return matches


def fetch_todays_matches(timeout=20):
    """Convenience wrapper: fetches the broader upcoming+live+finished set
    (no status filter, since a match live/finished today isn't
    "SCHEDULED" anymore) and filters to today's UTC date client-side -
    same pattern as MLB's Kalshi module filtering an all-future response
    down to today's slate."""
    token = os.environ.get(TOKEN_ENV_VAR)
    if not token:
        raise NoTokenError(
            f"{TOKEN_ENV_VAR} is not set - register a free token at "
            "https://www.football-data.org/client/register and add it as "
            "a repo secret"
        )
    headers = {**HEADERS_BASE, "X-Auth-Token": token}
    today_iso = date.today().isoformat()
    r = requests.get(
        f"{BASE_URL}/competitions/PL/matches",
        headers=headers,
        params={"dateFrom": today_iso, "dateTo": today_iso},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()

    matches = []
    for m in data.get("matches", []):
        try:
            home = m.get("homeTeam", {})
            away = m.get("awayTeam", {})
            score = m.get("score", {})
            full_time = score.get("fullTime", {})
            matches.append(
                FootballDataMatch(
                    match_id=m["id"],
                    utc_kickoff=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
                    status=m.get("status", ""),
                    matchday=m.get("matchday"),
                    home_team=home.get("name") or home.get("shortName") or "",
                    away_team=away.get("name") or away.get("shortName") or "",
                    home_tla=home.get("tla"),
                    away_tla=away.get("tla"),
                    home_score=full_time.get("home"),
                    away_score=full_time.get("away"),
                    winner=score.get("winner"),
                    raw=m,
                )
            )
        except (KeyError, ValueError):
            continue

    return matches
