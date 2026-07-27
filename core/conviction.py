"""
Sport-agnostic "how many models agree" engine, used by both the
Conviction Board and Track Record's highest-conviction-pick lookups. This
generalizes cleanly (unlike flagging.py's checks) because it never touches
a sport's own field names - it only ever sees abstract (source, direction)
vote tuples that each sport's own vote-extractor function builds (e.g.
sports/mlb/analysis/build.py's _moneyline_votes/_totals_votes, which know
about DRatings/BPP/My model's specific fields), plus a min-sources/
max-dissent bar and a function to turn the winning raw direction into a
display label. Every sport that wants a Conviction-Board-style "who do the
counted sources agree on" table calls tally_votes with its own votes and
thresholds and gets the same shape back.
"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class ConvictionRow:
    label: str                 # the winning direction, already turned into display text
    agree_count: int
    total_count: int
    agreeing_sources: list = field(default_factory=list)
    dissenting: list = field(default_factory=list)  # [(source, direction_label), ...]


def tally_votes(votes, min_sources, max_dissent, direction_to_label):
    """votes: [(source, direction), ...] - direction is any hashable value
    ('away'/'home', 'over'/'under', a team abbrev, etc.), abstract to this
    function. Returns a ConvictionRow, or None if there aren't enough
    votes (fewer than min_sources) or too many of them dissent from the
    majority (more than max_dissent) - the same "don't force a pick that
    isn't actually well-supported" bar the Conviction Board and Track
    Record both apply. Ties are broken by Counter.most_common's insertion
    order, same as the pre-refactor behavior this replaces."""
    if len(votes) < min_sources:
        return None
    counts = Counter(d for _, d in votes)
    top_dir, top_count = counts.most_common(1)[0]
    total = len(votes)
    if total - top_count > max_dissent:
        return None
    agreeing = [src for src, d in votes if d == top_dir]
    dissenting = [(src, direction_to_label(d)) for src, d in votes if d != top_dir]
    return ConvictionRow(
        label=direction_to_label(top_dir),
        agree_count=top_count,
        total_count=total,
        agreeing_sources=agreeing,
        dissenting=dissenting,
    )


def majority_pick(votes):
    """Simpler sibling of tally_votes with no min-sources/max-dissent gate
    - every game gets a majority pick and an agreement count recorded
    (used by prediction loggers so accuracy-breakdown analysis has an
    agreement count for every scored game, not just the ones that clear
    the Conviction Board's bar). Returns (winning_direction, agree_count,
    total_count), or (None, 0, 0) if there were no votes at all."""
    if not votes:
        return None, 0, 0
    counts = Counter(d for _, d in votes)
    top_dir, top_count = counts.most_common(1)[0]
    return top_dir, top_count, len(votes)
