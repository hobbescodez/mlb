"""
Model 3: Elo baseline. Converts two teams' ClubElo ratings into a
three-way (home win / draw / away win) outcome probability.

What's cited vs. calibrated vs. approximated here, explicitly, since this
model mixes a real published formula with this project's own simplified
extension - same honesty standard as every other piece of this project:

1. Win expectancy E - CITED, not invented. ClubElo's own published
   formula (clubelo.com/System): E = 1 / (1 + 10^(-dr/400)), where dr is
   the Elo point difference. This is the standard Elo expected-score
   formula (same one chess uses), applied by ClubElo itself. Note E is an
   *expected points share* (win=1, draw=0.5, loss=0), not a win
   probability by itself - a football match has three outcomes, not two.

2. Home advantage (in Elo points) - CALIBRATED from real data, not
   guessed. ClubElo's own site describes home advantage as a value their
   system continuously recalibrates internally per country
   (HFA += sum(ΔElo)*0.075 per their own docs) - that internal value
   isn't exposed via their public API, so it can't be read directly. This
   module instead computes its own estimate from real football-data.org
   match results (see calibrate_home_advantage_elo): the average
   home-team points-share edge across a real completed season, converted
   to an Elo-point equivalent by inverting the same E formula. This is a
   real number computed from real results, not ClubElo's exact internal
   value and not a made-up constant either.

3. Splitting E into three outcomes (home win / draw / away win) - this
   project's OWN SIMPLIFIED APPROXIMATION, explicitly not the peer-
   reviewed approach. The established academic method for this
   (Hvattum & Arntzen, 2010, "Using ELO ratings for match result
   prediction in association football", International Journal of
   Forecasting) fits an ordered logit regression on historical
   Elo-difference-vs-outcome data. That requires per-match Elo ratings
   *at kickoff time* for many historical matches, which isn't available
   here (ClubElo's API gives current/date-specific snapshots, not an
   easy bulk historical join against football-data.org's fixture list).
   Lacking that, this module uses a simpler closed-form approximation:
   draw probability is the league's real empirical draw rate (also
   calibrated from real football-data.org results), tapered down as the
   match becomes more mismatched (closer to 50/50 -> draw rate near the
   league average; heavily lopsided -> draw rate shrinks toward 0, which
   matches the well-documented general pattern that draws cluster among
   evenly-matched teams). The taper is linear and this project's own
   choice, not a cited statistical result. Home/away win probabilities
   are then solved algebraically so they exactly reproduce E (see
   predict_outcome_probabilities) - i.e. this model's three-way output is
   guaranteed consistent with ClubElo's own real formula, even though the
   specific draw-split shape is an approximation, not the Hvattum-Arntzen
   method.

Improving #3 to the real ordered-logit approach is a legitimate future
enhancement, not attempted here given the historical-data gap above.
"""

import math
from dataclasses import dataclass


@dataclass
class OutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


def win_expectancy(elo_home, elo_away, home_advantage_elo=0.0):
    """ClubElo's own published formula (see module docstring, point 1):
    expected points share for the home team, win=1/draw=0.5/loss=0 scale."""
    dr = (elo_home + home_advantage_elo) - elo_away
    return 1.0 / (1.0 + 10 ** (-dr / 400.0))


def calibrate_home_advantage_elo(matches):
    """Estimates a home-advantage Elo-point offset from a list of
    finished sports.epl.fetch.football_data.FootballDataMatch (see module
    docstring, point 2). Computes the average home-team points share
    (win=1/draw=0.5/loss=0) across all given matches, then inverts the
    win_expectancy formula to find the Elo-point difference that would
    produce that average share for an otherwise-even matchup. Raises
    ValueError if given no matches with valid scores - callers should
    have a real prior season's finished results before calling this."""
    shares = []
    for m in matches:
        if m.home_score is None or m.away_score is None:
            continue
        if m.home_score > m.away_score:
            shares.append(1.0)
        elif m.home_score == m.away_score:
            shares.append(0.5)
        else:
            shares.append(0.0)

    if not shares:
        raise ValueError("no finished matches with valid scores to calibrate from")

    avg_share = sum(shares) / len(shares)
    # clip away from the exact 0/1 boundary - log-odds is undefined there,
    # and a real sample is never going to be a perfect 0% or 100% anyway
    clipped = min(max(avg_share, 0.01), 0.99)
    return 400.0 * math.log10(clipped / (1.0 - clipped))


def calibrate_draw_rate(matches):
    """Empirical draw rate from a list of finished FootballDataMatch (see
    module docstring, point 3). Raises ValueError if given no matches
    with valid scores."""
    finished = [m for m in matches if m.home_score is not None and m.away_score is not None]
    if not finished:
        raise ValueError("no finished matches with valid scores to calibrate from")
    draws = sum(1 for m in finished if m.home_score == m.away_score)
    return draws / len(finished)


def predict_outcome_probabilities(elo_home, elo_away, home_advantage_elo, league_draw_rate):
    """Returns OutcomeProbabilities(home_win, draw, away_win) for a
    matchup, given calibrated home_advantage_elo and league_draw_rate
    (see calibrate_home_advantage_elo / calibrate_draw_rate). See module
    docstring point 3 for the exact approximation used and its honesty
    caveats. Guarantees home_win + 0.5*draw == win_expectancy(...) by
    construction, so this always stays consistent with ClubElo's own
    real formula regardless of the draw-split approximation."""
    e = win_expectancy(elo_home, elo_away, home_advantage_elo)

    # 1.0 when E=0.5 (dead-even matchup), 0.0 when E=0 or E=1 (total mismatch)
    closeness = max(0.0, 1.0 - 2.0 * abs(e - 0.5))
    p_draw = league_draw_rate * closeness
    p_home = e - 0.5 * p_draw
    p_away = 1.0 - p_home - p_draw

    # guard against float drift at the extremes rather than let a
    # negative-zero-ish probability leak out
    p_home = min(max(p_home, 0.0), 1.0)
    p_away = min(max(p_away, 0.0), 1.0)
    p_draw = min(max(p_draw, 0.0), 1.0)

    return OutcomeProbabilities(home_win=p_home, draw=p_draw, away_win=p_away)
