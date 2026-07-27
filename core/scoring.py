"""
Sport-agnostic accuracy-scoring engine: joins a sport's predictions log and
results log on game_id and scores each source's accuracy. Pure computation
- no fetching, no network calls. Each sport keeps its own wide-format CSVs
(one row per game, one column per source - see e.g.
sports/mlb/tracker/log_predictions.py) rather than a single shared
normalized table, so a sport's already-accumulated history is never
reshaped or touched by another sport's presence; what's shared here is the
scoring *engine* (parameterized by that sport's own source list and field
names) and the accuracy-result shape it returns, tagged with a `sport`
field so cross-sport code (e.g. a future landing page) can tell results
from different sports apart even though each sport still owns its own CSV.

A source's blank/missing pick or projection for a given game is excluded
from that source's own denominator entirely, never counted as a miss: if
a source had no row for a game, that game doesn't count toward its
accuracy % at all. Likewise a game with no matching results-log row yet
(not final) is skipped for every source - it isn't scoreable yet.

Moneyline accuracy is directly comparable across every source in
moneyline_sources - each logs a picked team/side, scored against whether
that side actually won.

Totals accuracy is NOT uniform across sources, and treating it as such
would be a real modeling error: a source in numeric_total_sources logs a
specific projected total (e.g. runs, goals, points), scored as average
absolute error against the actual total. A source in lean_total_sources
(e.g. a betting market) never projects a specific total - it only logs a
lean (over/under) relative to its own market line - so its accuracy is a
hit-rate percentage (did the lean match how the actual total compared to
its line), a different metric on a different scale from "average error."
Reporting them side by side without labeling this difference would be
misleading.
"""

from dataclasses import dataclass


@dataclass
class MoneylineAccuracy:
    source: str
    sport: str
    games_scored: int
    correct_picks: int
    accuracy_pct: float | None


@dataclass
class NumericTotalAccuracy:
    source: str
    sport: str
    games_scored: int
    avg_abs_error_runs: float | None


@dataclass
class LeanTotalAccuracy:
    source: str
    sport: str
    games_scored: int
    correct_leans: int
    accuracy_pct: float | None


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_moneyline(predictions_rows, results_by_id, sources, sport, pick_field=lambda s: f"{s}_pick"):
    """sources: tuple of source keys (e.g. ("dratings", "bpp", "mymodel")).
    pick_field(source) -> the predictions-row column holding that source's
    picked-team abbreviation, defaulting to the "{source}_pick" convention
    every sport's tracker CSV already uses. Returns {source:
    MoneylineAccuracy}."""
    stats = {s: {"n": 0, "correct": 0} for s in sources}
    for p in predictions_rows:
        result = results_by_id.get(p.get("game_id"))
        if not result:
            continue
        winner = result.get("winner_abbrev")
        for source in sources:
            pick = p.get(pick_field(source))
            if not pick:
                continue
            stats[source]["n"] += 1
            if pick == winner:
                stats[source]["correct"] += 1

    out = {}
    for source, s in stats.items():
        pct = round(100 * s["correct"] / s["n"], 1) if s["n"] else None
        out[source] = MoneylineAccuracy(source=source, sport=sport, games_scored=s["n"], correct_picks=s["correct"], accuracy_pct=pct)
    return out


def score_numeric_totals(predictions_rows, results_by_id, sources, sport, actual_field="total_runs",
                          proj_field=lambda s: f"{s}_total_proj"):
    """sources: tuple of source keys with a literal projected-total column
    (e.g. runs, goals). actual_field: the results-row column holding the
    actual total. Returns {source: NumericTotalAccuracy}."""
    stats = {s: {"n": 0, "err_sum": 0.0} for s in sources}
    for p in predictions_rows:
        result = results_by_id.get(p.get("game_id"))
        if not result:
            continue
        actual_total = _to_float(result.get(actual_field))
        for source in sources:
            proj = _to_float(p.get(proj_field(source)))
            if proj is None or actual_total is None:
                continue
            stats[source]["n"] += 1
            stats[source]["err_sum"] += abs(proj - actual_total)

    out = {}
    for source, s in stats.items():
        avg_err = round(s["err_sum"] / s["n"], 2) if s["n"] else None
        out[source] = NumericTotalAccuracy(source=source, sport=sport, games_scored=s["n"], avg_abs_error_runs=avg_err)
    return out


def score_lean_total(predictions_rows, results_by_id, source, sport, actual_field="total_runs",
                      lean_field=None, line_field=None):
    """A single market/reference source (e.g. a prediction market) that
    only logs an over/under lean relative to its own line, not a literal
    projected total - see module docstring. Returns a LeanTotalAccuracy."""
    n, correct = 0, 0
    for p in predictions_rows:
        result = results_by_id.get(p.get("game_id"))
        if not result:
            continue
        actual_total = _to_float(result.get(actual_field))
        lean = p.get(lean_field)
        line = _to_float(p.get(line_field))
        if not lean or line is None or actual_total is None:
            continue
        actual_lean = "over" if actual_total > line else ("under" if actual_total < line else "push")
        if actual_lean == "push":
            continue
        n += 1
        if lean == actual_lean:
            correct += 1
    pct = round(100 * correct / n, 1) if n else None
    return LeanTotalAccuracy(source=source, sport=sport, games_scored=n, correct_leans=correct, accuracy_pct=pct)


def results_by_game_id(results_rows):
    return {r["game_id"]: r for r in results_rows if r.get("game_id")}
