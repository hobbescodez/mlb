"""
Fetches current club Elo ratings from ClubElo's public CSV API
(http://api.clubelo.com/) - no auth required.

Schema verified against a real fetch via scripts/probe_epl_sources.py
(this dev environment can't reach api.clubelo.com directly - see that
script's docstring). Real response: plain CSV, header
"Rank,Club,Country,Level,Elo,From,To", one row per club *across every
country/league ClubElo tracks* (589 rows total in the probe, not just
England) - filtering to Country == "ENG" and Level == 1 is required and
done client-side here, same as MLB's Kalshi module filters its
all-future-games response down to today's slate client-side.

Deliberately not hardcoding "which clubs are in the Premier League this
season" anywhere (see sports/epl/teams.py's docstring for why) - this
Country/Level filter on live data is the actual source of truth for
current EPL membership, which is exactly why this fetcher exists rather
than a static list.

Each club's rating has a "From"/"To" validity window (ClubElo updates
ratings after each match, so old rows persist with a bounded window) -
only current rows matter here, so this fetcher requests today's date
explicitly rather than the unbounded/latest endpoint, and does not surface
From/To to callers.
"""

from datetime import date
from dataclasses import dataclass

import requests

BASE_URL = "http://api.clubelo.com"

HEADERS = {
    "User-Agent": "epl-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}

COUNTRY = "ENG"
TOP_FLIGHT_LEVEL = "1"


@dataclass
class ClubEloRating:
    club: str
    elo: float
    rank: int | None = None


def fetch_current_ratings(as_of=None, timeout=20):
    """Returns a dict of {club_name: ClubEloRating} for current Premier
    League clubs (Country=ENG, Level=1) as of the given date (defaults to
    today). Raises on network/parsing failure at the top level so callers
    can decide how to degrade (this source is optional, same as every
    source in this project)."""
    as_of = as_of or date.today()
    url = f"{BASE_URL}/{as_of.isoformat()}"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()

    lines = r.text.strip().split("\n")
    if not lines:
        raise ValueError("ClubElo: empty response")

    header = [h.strip() for h in lines[0].split(",")]
    col_index = {name: i for i, name in enumerate(header)}
    required = ("Club", "Country", "Level", "Elo", "Rank")
    missing = [c for c in required if c not in col_index]
    if missing:
        raise ValueError(f"ClubElo: response missing expected column(s) {missing} - header was {header}")

    ratings = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        # club names don't contain commas in ClubElo's data, so a plain
        # split is safe (same assumption ClubElo's own docs make)
        fields = line.split(",")
        if len(fields) != len(header):
            continue
        try:
            country = fields[col_index["Country"]].strip()
            level = fields[col_index["Level"]].strip()
            if country != COUNTRY or level != TOP_FLIGHT_LEVEL:
                continue
            club = fields[col_index["Club"]].strip()
            elo = float(fields[col_index["Elo"]])
            rank = int(fields[col_index["Rank"]])
            ratings[club] = ClubEloRating(club=club, elo=elo, rank=rank)
        except (ValueError, IndexError):
            # skip malformed rows rather than failing the whole source
            continue

    return ratings
