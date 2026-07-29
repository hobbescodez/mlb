"""
Backtests / forward-tests the "over-only, model total >= market + threshold"
totals rule against this project's own logged history (predictions_log.csv
+ results_log.csv) - a paper/analysis exercise only, with no connection to
order placement anywhere (see log_predictions.py's own module docstring
for that same no-trading guarantee, which this module inherits by only
ever reading the same two CSVs - never writing/submitting anything).

"Model total" here reuses the exact definition build.py's trigger (a)
already uses for the live report's "model vs. market" flag (see
_check_total_gap): BPP's projected total (bpp_total_proj), falling back
to DRatings' projected total (dratings_total_proj) when BPP has no row
for that game - kept consistent with the live report rather than
inventing a second, competing definition of "the model total."

Two separate things live here:
  - backtest_thresholds(): fits/tests every threshold in
    BACKTEST_THRESHOLDS against the FULL logged history - a backtest,
    free to be shaped by what's already happened, so its numbers alone
    are not proof a threshold works going forward.
  - forward_hit_rates(): the ongoing, going-forward companion - scoped to
    CANDIDATE_THRESHOLDS and only counts predictions logged on/after
    FORWARD_TRACKING_START_DATE, so it is never fit to the same data used
    to pick those candidate thresholds. main.py calls this every daily
    run, so the sample keeps growing on genuinely new, out-of-sample
    games instead of re-testing history the backtest already used.
"""

from dataclasses import dataclass

BACKTEST_THRESHOLDS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
# Candidates for ongoing forward-tracking - the 2026-07-29 backtest (89
# logged games) only cleared the >=15-qualifying-game bar at 0.5 and 1.0
# runs (59 and 33 qualifying games respectively, both ~48% hit rate - a
# coin flip, no edge either way in this early sample). Every threshold
# above 1.0 had too few qualifying games to mean anything yet. Tracking
# these two forward is what actually tells us whether ~48% holds up on
# real out-of-sample data or was a small-sample artifact - not a claim
# either one has an edge.
CANDIDATE_THRESHOLDS = (0.5, 1.0)
FORWARD_TRACKING_START_DATE = "2026-07-29"  # date this feature shipped
MIN_SAMPLE = 15  # fewer qualifying decided games than this = "too small to trust"


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _model_total(row):
    bpp = _to_float(row.get("bpp_total_proj"))
    return bpp if bpp is not None else _to_float(row.get("dratings_total_proj"))


@dataclass
class ThresholdResult:
    threshold: float
    qualifying: int  # games where model_total - market_total >= threshold
    pushes: int       # of those, actual total == market line (excluded from hit rate)
    hits: int          # of the non-push qualifying games, actual total > market line
    hit_rate: float | None
    too_small: bool


def _threshold_result(rows, results_by_id, threshold, min_sample):
    qualifying = 0
    pushes = 0
    hits = 0
    for row in rows:
        result = results_by_id.get(row.get("game_id"))
        if not result:
            continue
        model_total = _model_total(row)
        market_total = _to_float(row.get("market_total"))
        actual_total = _to_float(result.get("total_runs"))
        if model_total is None or market_total is None or actual_total is None:
            continue
        if model_total - market_total < threshold:
            continue
        qualifying += 1
        if actual_total == market_total:
            pushes += 1
        elif actual_total > market_total:
            hits += 1
    decided = qualifying - pushes
    hit_rate = round(100 * hits / decided, 1) if decided else None
    return ThresholdResult(
        threshold=threshold, qualifying=qualifying, pushes=pushes, hits=hits,
        hit_rate=hit_rate, too_small=decided < min_sample,
    )


def backtest_thresholds(predictions_rows, results_rows, thresholds=BACKTEST_THRESHOLDS, min_sample=MIN_SAMPLE):
    """Fits/tests every threshold against the full logged history. Returns
    a list of ThresholdResult, one per threshold, in the order given."""
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}
    return [_threshold_result(predictions_rows, results_by_id, t, min_sample) for t in thresholds]


def forward_hit_rates(predictions_rows, results_rows, thresholds=CANDIDATE_THRESHOLDS,
                       start_date=FORWARD_TRACKING_START_DATE, min_sample=MIN_SAMPLE):
    """Same computation as backtest_thresholds, but scoped to predictions
    logged on/after start_date - the genuinely out-of-sample, "tested
    forward on new data" companion the backtest can't be (see module
    docstring)."""
    forward_rows = [r for r in predictions_rows if (r.get("date") or "") >= start_date]
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}
    return [_threshold_result(forward_rows, results_by_id, t, min_sample) for t in thresholds]
