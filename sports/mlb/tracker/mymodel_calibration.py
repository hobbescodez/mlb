"""
Calibration check for My model's win-probability "confidence" - ANALYSIS
ONLY, reads predictions_log.csv + results_log.csv, never touches the live
model (sports/mlb/fetch/mymodel.py) or main.py's daily pipeline.

Important honesty note: My model (see fetch/mymodel.py) does not itself
output a win probability - only two projected-run numbers and a picked
winner (whichever side projects more runs). To do the calibration check
requested (group picks by confidence bucket, compare to actual win rate),
this module derives an implied win probability from those two projected
runs via independent Poisson distributions - the same technique this
project already uses for real in sports/epl/models/poisson_xg.py, just
applied here for a one-off analysis rather than a shipped model. Two
assumptions specific to this derivation, both documented rather than
silently baked in:
  - Poisson score distributions, independent across the two teams (the
    same simplifying assumption the EPL Poisson model makes, and the
    same one Dixon-Coles' correlation correction exists to soften there -
    no such correction is applied here, since this is a quick calibration
    probe, not a new model).
  - Baseball has no ties (extra innings resolve every game), but the
    Poisson distribution assigns real probability mass to a tied score.
    That mass is split 50/50 between the two sides here, since neither
    projected-runs number carries any information about extra-innings
    performance specifically - not a claim that a 50/50 split is
    correct, just the least-assuming option available with what's logged.

None of this changes what mymodel_pick actually is (still whichever side
has the higher projected-runs number) - it only adds a probability
*around* that same pick, purely to answer "is My model well-calibrated."
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

PREDICTIONS_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "predictions_log.csv"
RESULTS_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "results_log.csv"

MAX_RUNS = 15  # Poisson tail beyond this is negligible for realistic MLB run totals
BUCKET_WIDTH = 5  # percentage points per confidence bucket (50-55%, 55-60%, ...)
MIN_SAMPLE = 15


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _poisson_pmf(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def implied_home_win_prob(away_lambda, home_lambda, max_runs=MAX_RUNS):
    """P(home wins) under independent Poisson(away_lambda)/Poisson(home_lambda)
    score distributions, tied-score mass split 50/50 (see module docstring).
    Returns None if either projection is missing or non-positive."""
    if away_lambda is None or home_lambda is None or away_lambda <= 0 or home_lambda <= 0:
        return None
    home_win = away_win = tie = 0.0
    for a in range(max_runs + 1):
        pa = _poisson_pmf(a, away_lambda)
        for h in range(max_runs + 1):
            p = pa * _poisson_pmf(h, home_lambda)
            if h > a:
                home_win += p
            elif h < a:
                away_win += p
            else:
                tie += p
    total = home_win + away_win + tie  # < 1.0 by a hair due to truncation at max_runs
    if total <= 0:
        return None
    return (home_win + tie / 2) / total


@dataclass
class BucketResult:
    label: str
    low: float
    high: float
    n: int
    correct: int
    win_rate: float | None
    too_small: bool


def _pick_confidence(row):
    """Returns (pick_abbrev, confidence_pct_0_100) for a row's My model
    pick, or (None, None) if projections/pick are missing."""
    away_proj = _to_float(row.get("mymodel_away_proj"))
    home_proj = _to_float(row.get("mymodel_home_proj"))
    pick = row.get("mymodel_pick")
    if not pick or away_proj is None or home_proj is None:
        return None, None
    home_prob = implied_home_win_prob(away_proj, home_proj)
    if home_prob is None:
        return None, None
    is_home_pick = pick == row.get("home_abbrev")
    confidence = home_prob if is_home_pick else (1 - home_prob)
    return pick, round(confidence * 100, 2)


def build_calibration(predictions_rows, results_rows, bucket_width=BUCKET_WIDTH, min_sample=MIN_SAMPLE):
    """Groups My model's decided, resolved picks into confidence buckets
    (50-55%, 55-60%, ... - a pick is always >=50% confident in itself by
    construction) and reports actual win rate per bucket. A
    well-calibrated model's 60-65% bucket should win right around 60-65%
    of the time; systematic over/under-confidence shows up as buckets
    consistently missing their own range."""
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}

    buckets = {}  # low -> [n, correct]
    for row in predictions_rows:
        result = results_by_id.get(row.get("game_id"))
        if not result or not result.get("winner_abbrev"):
            continue
        pick, confidence = _pick_confidence(row)
        if pick is None or confidence is None:
            continue
        low = min(95, (int(confidence) // bucket_width) * bucket_width)  # clamp so 100% lands in the 95-100 bucket
        bucket = buckets.setdefault(low, [0, 0])
        bucket[0] += 1
        if pick == result["winner_abbrev"]:
            bucket[1] += 1

    out = []
    for low in sorted(buckets):
        n, correct = buckets[low]
        high = low + bucket_width
        win_rate = round(100 * correct / n, 1) if n else None
        out.append(BucketResult(
            label=f"{low}-{high}%", low=low, high=high, n=n, correct=correct,
            win_rate=win_rate, too_small=n < min_sample,
        ))
    return out


def _load_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    predictions_rows = _load_csv(PREDICTIONS_LOG_PATH)
    results_rows = _load_csv(RESULTS_LOG_PATH)
    results = build_calibration(predictions_rows, results_rows)
    print(f"{'bucket':>10} {'n':>4} {'correct':>7} {'win_rate':>9}  flag")
    for r in results:
        wr = f"{r.win_rate}%" if r.win_rate is not None else "n/a"
        flag = "TOO FEW GAMES" if r.too_small else ""
        print(f"{r.label:>10} {r.n:>4} {r.correct:>7} {wr:>9}  {flag}")
