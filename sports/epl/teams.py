"""Club name normalization shared across EPL fetchers.

Unlike MLB (a fixed 30-team league), the Premier League has promotion/
relegation every season, so - deliberately, unlike sports/mlb/teams.py -
this is NOT a hardcoded "who's currently in the league" membership list.
Hardcoding that from training knowledge risks being wrong about a given
season's promoted/relegated clubs. Instead this only normalizes name
*variants* different sources use for the same club (DRatings spells out
"Manchester United", ClubElo says "Man United", Reddit threads say
"Man Utd" or "Spurs") into one canonical short name. Whichever clubs are
actually in the league in a given season is determined at fetch time from
live data (e.g. ClubElo's own Country=ENG,Level=1 rows - see clubelo.py),
not from this table.

An unrecognized club name is not an error - callers fall back to using the
raw name as-is (see abbrev_from_name below), same best-effort posture as
every other source in this project.
"""

import re

# canonical_name -> [alias, alias, ...]. Covers clubs that have appeared in
# the Premier League in recent seasons; an unlisted club (newly promoted,
# or one this table missed) still works fine via the raw-name fallback.
CLUB_ALIASES = {
    "Arsenal": [],
    "Aston Villa": ["Villa"],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": [],
    "Brighton": ["Brighton & Hove Albion", "Brighton and Hove Albion"],
    "Burnley": [],
    "Chelsea": [],
    "Crystal Palace": ["Palace"],
    "Everton": [],
    "Fulham": [],
    "Ipswich Town": ["Ipswich"],
    "Leeds United": ["Leeds"],
    "Leicester City": ["Leicester"],
    "Liverpool": [],
    "Luton Town": ["Luton"],
    "Manchester City": ["Man City"],
    "Manchester United": ["Man United", "Man Utd", "Man U"],
    "Newcastle United": ["Newcastle"],
    "Norwich City": ["Norwich"],
    "Nottingham Forest": ["Nott'm Forest", "Forest"],
    "Sheffield United": ["Sheffield Utd"],
    "Southampton": [],
    "Sunderland": [],
    "Tottenham Hotspur": ["Tottenham", "Spurs"],
    "Watford": [],
    "West Bromwich Albion": ["West Brom", "WBA"],
    "West Ham United": ["West Ham"],
    "Wolverhampton Wanderers": ["Wolves", "Wolverhampton"],
}

ALIAS_TO_CANONICAL = {}
for _canonical, _aliases in CLUB_ALIASES.items():
    ALIAS_TO_CANONICAL[_canonical] = _canonical
    for _alias in _aliases:
        ALIAS_TO_CANONICAL[_alias] = _canonical

# longest alias first, so "Tottenham Hotspur" matches before "Tottenham"
_ALIASES_BY_LENGTH = sorted(ALIAS_TO_CANONICAL, key=len, reverse=True)


def canonical_name(name):
    """Best-effort: map any known alias/full-name substring in free text to
    its canonical club name. Falls back to the input stripped of whitespace
    if nothing matches - never returns None for a non-empty input, so
    callers always have *something* to key/display, even for a club this
    table doesn't know about yet."""
    if not name:
        return None
    cleaned = re.sub(r"\s+", " ", name).strip()
    for alias in _ALIASES_BY_LENGTH:
        if alias.lower() in cleaned.lower():
            return ALIAS_TO_CANONICAL[alias]
    return cleaned


def short_code(name):
    """Best-effort 3-letter code from a canonical club name (first letters
    of significant words), for compact table display. Not guaranteed
    globally unique - purely cosmetic, unlike MLB's official abbreviations."""
    canon = canonical_name(name)
    if not canon:
        return None
    words = [w for w in re.split(r"\s+", canon) if w.lower() not in ("united", "city", "town", "hotspur", "wanderers", "albion")]
    if not words:
        words = canon.split()
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()
