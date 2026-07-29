"""
Scans r/soccer's RSS feed for club mentions, as a lightweight sentiment
signal alongside the model-based sources.

Deliberately NOT modeled on MLB's reddit.py, which looks for a single
daily "MLB Discussion" megathread by title+date match. A real fetch via
scripts/probe_epl_sources.py (this dev environment can't reach reddit.com
directly - see that script's docstring) showed r/soccer's /new.rss feed is
a stream of individual match-event and transfer-news submissions (e.g.
"Tigre [1]-2 Nacional [4-2 on agg.] - Santiago Lopez 82'"), not a daily
megathread - no title in the 26 real entries fetched matched any
date/"daily discussion" pattern. Forcing MLB's single-thread model onto
that would either find nothing most days or misidentify a random match
thread as "the" thread. Scanning club mentions across the recent-entries
window is the honest fit for what this feed actually contains.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

from sports.epl.teams import canonical_name, CLUB_ALIASES, ALIAS_TO_CANONICAL

USER_AGENT = "epl-daily-tracker/1.0 (personal project; non-commercial daily digest)"
HEADERS = {"User-Agent": USER_AGENT}

REDDIT_RSS_URL = "https://www.reddit.com/r/soccer/new.rss"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

# longest alias first, same reasoning as teams.py's own matcher
_ALIASES_BY_LENGTH = sorted(ALIAS_TO_CANONICAL, key=len, reverse=True)
_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ALIASES_BY_LENGTH) + r")\b"
)


@dataclass
class ClubMention:
    club: str
    count: int = 0
    snippets: list = field(default_factory=list)


@dataclass
class RedditResult:
    available: bool
    entry_count: int = 0
    mentions: dict = field(default_factory=dict)  # canonical club name -> ClubMention
    note: str = ""


def _fetch_rss_once():
    r = requests.get(REDDIT_RSS_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text


def _parse_rss_entries(xml_text):
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title_el = entry.find(f"{ATOM_NS}title")
        entries.append(html.unescape(title_el.text) if title_el is not None and title_el.text else "")
    return entries


def _extract_mentions(titles):
    mentions = {}
    for title in titles:
        for m in _KEYWORD_PATTERN.finditer(title):
            canon = canonical_name(m.group(1))
            entry = mentions.setdefault(canon, ClubMention(club=canon))
            entry.count += 1
            if len(entry.snippets) < 5 and title not in entry.snippets:
                entry.snippets.append(title)
    return mentions


def fetch_recent_mentions():
    """Best-effort club-mention scan over r/soccer's most recent RSS
    entries. Titles only (RSS is submissions-only, no comment/body text -
    same limitation MLB's reddit.py documents). Not date-filtered: the
    feed is just "most recent N posts" with no daily-thread concept to
    anchor on (see module docstring)."""
    try:
        xml_text = _fetch_rss_once()
        titles = _parse_rss_entries(xml_text)
        if not titles:
            raise ValueError("RSS feed returned zero entries")
        mentions = _extract_mentions(titles)
        return RedditResult(
            available=True,
            entry_count=len(titles),
            mentions=mentions,
            note=(
                "titles only from r/soccer's most recent submissions (no "
                "daily megathread exists on this subreddit the way "
                "r/sportsbook's MLB thread does - see module docstring)"
            ),
        )
    except Exception as e:
        return RedditResult(
            available=False,
            note=f"live RSS fetch failed: {e}",
        )
