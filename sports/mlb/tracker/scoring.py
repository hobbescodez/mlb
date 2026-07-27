"""
MLB's own thin wrapper around core.scoring's generic accuracy engine: just
supplies MLB's source list and CSV field-naming conventions. See
core/scoring.py for the actual join/scoring logic and why moneyline vs.
numeric-total vs. lean-total accuracy are three different shapes.
"""

from core.scoring import results_by_game_id, score_lean_total, score_moneyline, score_numeric_totals

SPORT = "mlb"
MONEYLINE_SOURCES = ("dratings", "bpp", "mymodel", "kalshi")
NUMERIC_TOTAL_SOURCES = ("dratings", "bpp", "mymodel")


def score_predictions(predictions_rows, results_rows):
    """predictions_rows / results_rows: lists of dicts (e.g. from
    csv.DictReader). Returns {
        "moneyline": {source: MoneylineAccuracy, ...},
        "totals": {source: NumericTotalAccuracy, ...},   # dratings/bpp/mymodel
        "kalshi_totals": LeanTotalAccuracy,
    }"""
    results_by_id = results_by_game_id(results_rows)
    moneyline = score_moneyline(predictions_rows, results_by_id, MONEYLINE_SOURCES, SPORT)
    totals = score_numeric_totals(predictions_rows, results_by_id, NUMERIC_TOTAL_SOURCES, SPORT)
    kalshi_totals = score_lean_total(
        predictions_rows, results_by_id, "kalshi", SPORT,
        lean_field="kalshi_total_pick", line_field="kalshi_total_line",
    )
    return {"moneyline": moneyline, "totals": totals, "kalshi_totals": kalshi_totals}
