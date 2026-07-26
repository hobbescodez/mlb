"""
"What predicts accuracy?" analysis - breaks moneyline win-pick accuracy
out by confidence tier, source-agreement count, and flagged/notable
status, using the metadata log_predictions.py already logs alongside
each day's picks (confidence_label, ml_majority_pick/ml_agree_count/
ml_total_count, notable). Pure computation over the two tracker CSVs,
same shape as scoring.py - no fetching, no network calls.

Two different "pick" concepts are scored here, deliberately not
conflated: confidence tier and flagged/notable both describe
prediction_winner_pick (the report's single best-available pick per
game - BPP sim > MoundEdge Model > DRatings priority, see build.py's
_build_matchups), since that's the pick those two signals are actually
about. Agreement count instead describes ml_majority_pick (the majority
vote among DRatings/BPP/My model for that game), since "how many
sources agreed" is inherently a multi-source question with its own
natural pick - not the same thing as "the single best-available pick."

This needs a real sample to mean anything: three days of data can't
tell you whether "Strong" consensus actually beats "Mixed." MIN_DAYS_FOR_SIGNAL
is the rough threshold this report uses to caveat the section until
there's enough logged history - the numbers are always shown (never
hidden), just clearly labeled as not-yet-meaningful below that bar.
"""

MIN_DAYS_FOR_SIGNAL = 14

# raw confidence_label values (see build.py's _CONFIDENCE_ICONS) in
# strongest-to-weakest display order, mapped to the same short badge
# words used everywhere else in the report.
_CONFIDENCE_ORDER = ["strong consensus", "fairly confident pick", "mixed signals", "not much consensus"]
_CONFIDENCE_DISPLAY = {
    "strong consensus": "Strong",
    "fairly confident pick": "Fairly confident",
    "mixed signals": "Mixed",
    "not much consensus": "Toss-up",
}

_NOTABLE_DISPLAY = {"1": "Flagged/notable", "0": "Routine"}
_NOTABLE_ORDER = ["Flagged/notable", "Routine"]


def _bucket_stats(triples):
    """triples: iterable of (bucket_label, pick, winner_abbrev). Returns
    {bucket_label: {"n": int, "correct": int, "pct": float|None}} for
    whichever buckets actually appear in the data."""
    stats = {}
    for label, pick, winner in triples:
        if not pick or not winner:
            continue
        b = stats.setdefault(label, {"n": 0, "correct": 0})
        b["n"] += 1
        if pick == winner:
            b["correct"] += 1
    for b in stats.values():
        b["pct"] = round(100 * b["correct"] / b["n"], 1) if b["n"] else None
    return stats


def _agreement_sort_key(label):
    agree, total = label.split("/")
    return (-int(total), -int(agree))


def build_accuracy_breakdown(predictions_rows, results_rows):
    """Returns {
        "days_logged": int,          # days with at least one scored game
        "enough_data": bool,         # days_logged >= MIN_DAYS_FOR_SIGNAL
        "min_days": int,
        "by_confidence": [{"label", "n", "correct", "pct"}, ...],  # strong -> toss-up order
        "by_agreement": [...],       # e.g. "3/3", "2/3", "2/2" - most-agreement first
        "by_notable": [...],         # "Flagged/notable" then "Routine"
    }
    A bucket is omitted entirely if no scored game ever landed in it (e.g.
    "Toss-up" simply won't appear until one has), rather than showing a
    fabricated 0/0 row."""
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}

    confidence_triples = []
    agreement_triples = []
    notable_triples = []
    days_scored = set()

    for p in predictions_rows:
        result = results_by_id.get(p.get("game_id"))
        if not result:
            continue  # not final yet - not scoreable
        winner = result.get("winner_abbrev")
        if not winner:
            continue
        days_scored.add(p.get("date"))

        pred_pick = p.get("prediction_winner_pick")
        conf_label = p.get("confidence_label")
        if conf_label and pred_pick:
            confidence_triples.append((conf_label, pred_pick, winner))

        notable_raw = p.get("notable")
        if notable_raw in _NOTABLE_DISPLAY and pred_pick:
            notable_triples.append((_NOTABLE_DISPLAY[notable_raw], pred_pick, winner))

        ml_pick = p.get("ml_majority_pick")
        agree_n = p.get("ml_agree_count")
        total_n = p.get("ml_total_count")
        if ml_pick and agree_n and total_n:
            agreement_triples.append((f"{agree_n}/{total_n}", ml_pick, winner))

    confidence_stats = _bucket_stats(confidence_triples)
    by_confidence = [
        {"label": _CONFIDENCE_DISPLAY[key], **confidence_stats[key]}
        for key in _CONFIDENCE_ORDER if key in confidence_stats
    ]

    agreement_stats = _bucket_stats(agreement_triples)
    by_agreement = [
        {"label": key, **agreement_stats[key]}
        for key in sorted(agreement_stats, key=_agreement_sort_key)
    ]

    notable_stats = _bucket_stats(notable_triples)
    by_notable = [
        {"label": key, **notable_stats[key]}
        for key in _NOTABLE_ORDER if key in notable_stats
    ]

    days_logged = len([d for d in days_scored if d])
    return {
        "days_logged": days_logged,
        "enough_data": days_logged >= MIN_DAYS_FOR_SIGNAL,
        "min_days": MIN_DAYS_FOR_SIGNAL,
        "by_confidence": by_confidence,
        "by_agreement": by_agreement,
        "by_notable": by_notable,
    }
