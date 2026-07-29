"""
Fetches upcoming EPL match predictions from DRatings.

Schema verified against a real page fetch via scripts/probe_epl_sources.py
(this dev environment can't reach dratings.com directly - see that
script's docstring). Notable things the real page showed:

  - The URL is .../predictor/english-premier-league-predictions/ - the two
    more "obvious" URL guesses (.../soccer-predictions/premier-league/ and
    .../soccer-predictions/) both 404. Confirmed by probe, not assumed.
  - Header row: Time, Teams, Win, Draw, Best ML, Goals, Total Goals,
    Best O/U, Bet Value (icon-only column, no useful text), More Details.
    No separate "pitchers" column (obviously - not baseball), and there's
    a third outcome (Draw) MLB's version doesn't have to handle.
  - "Teams" cell holds both club names stacked, same
    <span>/<br>-separated shape as MLB's version -
    _parse_two_stacked_spans is reused as-is from that module's pattern.
  - "Win" cell holds two percentages (away, home); "Draw" is a single
    percentage in its own column - three-way market, not two-way.
  - "Best ML" holds two American odds (away, home) - no draw price shown
    here even though Draw has its own win-probability column.
  - "Goals" holds two projected-goals values (away, home); "Total Goals"
    is their sum, DRatings' own projection - not the market total.
  - "Best O/U" holds the actual market total line, e.g. "o2½-130 u2½+117"
    - reused _market_total_from_ou_cell-style regex, but note the "½"
      renders as a mangled "Â½" in raw bytes (mojibake from the page's
      declared vs actual encoding) - the number-extraction regex only
      grabs the leading digit before that, so "2½" -> 2.5 needs an
      explicit half-point bump when a fraction glyph (in any mangled form)
      follows the digit.
"""

import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

URL = "https://www.dratings.com/predictor/english-premier-league-predictions/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class DRatingsMatch:
    away_team: str
    home_team: str
    away_win_pct: float | None
    home_win_pct: float | None
    draw_pct: float | None
    away_moneyline: int | None
    home_moneyline: int | None
    away_projected_goals: float | None
    home_projected_goals: float | None
    total_projected_goals: float | None
    market_total: float | None
    detail_url: str | None = None
    time_text: str = ""
    raw: dict = field(default_factory=dict)


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_two_stacked_spans(cell):
    """Cells like <span>Club A</span><br/><span>Club B</span> -> [textA, textB]."""
    spans = cell.find_all("span", recursive=False) if cell else []
    if len(spans) >= 2:
        return [_clean(s.get_text()) for s in spans[:2]]
    if cell is None:
        return [None, None]
    parts = [p for p in cell.stripped_strings]
    if len(parts) >= 2:
        return [_clean(p) for p in parts[:2]]
    return [_clean(parts[0]) if parts else None, None]

def _first_number(text):
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _first_int(text):
    if not text:
        return None
    m = re.search(r"[+-]?\d+", text)
    return int(m.group()) if m else None


def _market_total_from_ou_cell(cell):
    """'o2Â½-130 u2Â½+117' -> 2.5. The half-point glyph after the digit
    (whatever mangled form it renders as - probe showed 'Â½') means "add
    0.5"; a bare digit with no following glyph means a whole number."""
    if cell is None:
        return None
    text = cell.get_text(" ", strip=True)
    m = re.search(r"[ou](\d+)(\D{0,3})", text)
    if not m:
        return None
    whole = float(m.group(1))
    return whole + 0.5 if m.group(2).strip() else whole


def fetch_upcoming_matches(timeout=20):
    """Returns a list of DRatingsMatch for the upcoming EPL slate shown on
    the page (not date-filtered here - unlike MLB's daily slate, this page
    shows several days out; callers filter by date if needed). Raises on
    network/parsing failure at the top level so callers can decide how to
    degrade (this source is optional, same as every source in this
    project)."""
    r = requests.get(URL, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    heading = soup.find(lambda tag: tag.name in ("h1", "h2", "h3") and "Predictions" in tag.get_text())
    table = heading.find_next("table") if heading else soup.find("table")
    if table is None:
        raise ValueError("DRatings: could not locate the predictions table")

    header_cells = [_clean(th.get_text(" ")) for th in table.select("thead th")]
    col_index = {name.lower(): i for i, name in enumerate(header_cells)}

    def col(cells, name, default=None):
        i = col_index.get(name)
        if i is None or i >= len(cells):
            return default
        return cells[i]

    matches = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        try:
            time_cell = col(cells, "time")
            time_text = time_cell.get_text(" ", strip=True) if time_cell is not None else ""

            teams_cell = col(cells, "teams")
            away_team, home_team = _parse_two_stacked_spans(teams_cell)

            win_cell = col(cells, "win")
            win_spans = win_cell.find_all("span", recursive=False) if win_cell else []
            away_win = _first_number(win_spans[0].get_text()) if len(win_spans) > 0 else None
            home_win = _first_number(win_spans[1].get_text()) if len(win_spans) > 1 else None

            draw_cell = col(cells, "draw")
            draw_pct = _first_number(draw_cell.get_text()) if draw_cell is not None else None

            ml_cell = col(cells, "best ml")
            ml_spans = ml_cell.find_all("span", recursive=False) if ml_cell else []
            away_ml = _first_int(ml_spans[0].get_text()) if len(ml_spans) > 0 else None
            home_ml = _first_int(ml_spans[1].get_text()) if len(ml_spans) > 1 else None

            goals_cell = col(cells, "goals")
            away_goals = home_goals = None
            if goals_cell is not None:
                parts = list(goals_cell.stripped_strings)
                if len(parts) >= 2:
                    away_goals, home_goals = _first_number(parts[0]), _first_number(parts[1])

            total_cell = col(cells, "total goals")
            total_goals = _first_number(total_cell.get_text(" ")) if total_cell is not None else None

            ou_cell = col(cells, "best o/u")
            market_total = _market_total_from_ou_cell(ou_cell)

            link = tr.find("a", href=True)
            detail_url = ("https://www.dratings.com" + link["href"]) if link else None

            matches.append(
                DRatingsMatch(
                    away_team=away_team,
                    home_team=home_team,
                    away_win_pct=away_win,
                    home_win_pct=home_win,
                    draw_pct=draw_pct,
                    away_moneyline=away_ml,
                    home_moneyline=home_ml,
                    away_projected_goals=away_goals,
                    home_projected_goals=home_goals,
                    total_projected_goals=total_goals,
                    market_total=market_total,
                    detail_url=detail_url,
                    time_text=time_text,
                )
            )
        except Exception:
            # skip malformed rows rather than failing the whole source
            continue

    return matches
