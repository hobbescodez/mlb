"""
Sport-agnostic "flag a notable game" engine. A sport supplies its own list
of check functions (each one closes over that sport's own field names and
thresholds - e.g. sports/mlb/analysis/build.py's six checks) and this
module just runs them and collects whatever Flags come back. The actual
disagreement/threshold logic is inherently sport-specific (different
sports compare different numbers), so it stays in each sport's own
module - what's generic and worth sharing is the Flag shape itself and
the "run every check, collect what fires" loop, so every sport's
build_report_data ends up with the exact same m.flags/m.flag_codes
contract for the template layer to render identically.
"""

from dataclasses import dataclass


@dataclass
class Flag:
    code: str
    label: str
    detail: str


def run_checks(matchup, checks):
    """Runs each check(matchup) -> Flag|None in order and returns the list
    of Flags that fired. A check function receives the sport's own
    matchup/game object - this module doesn't know or care about its
    shape, only that each check returns a Flag or None."""
    flags = []
    for check in checks:
        flag = check(matchup)
        if flag:
            flags.append(flag)
    return flags


def gap_exceeds(value_a, value_b, threshold):
    """Shared primitive for the common "two numbers differ by more than a
    threshold" shape a lot of disagreement checks reduce to. Returns the
    signed gap if it exceeds the threshold (in either direction), else
    None. Sports still write their own check function around this (to
    build the right Flag code/label/detail), but don't have to
    reimplement "is abs(a - b) over the line" each time."""
    if value_a is None or value_b is None:
        return None
    gap = value_a - value_b
    return gap if abs(gap) > threshold else None
