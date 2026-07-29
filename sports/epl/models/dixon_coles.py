"""
Model 2: Dixon-Coles Monte Carlo. Corrects Model 1's independent-Poisson
assumption (see poisson_xg.py) for a well-documented real bias - plain
independent Poisson underrates low-scoring draws (0-0, 1-1) and
overrates narrow one-goal wins (1-0, 0-1) - then estimates outcome
probabilities and a full scoreline distribution by simulation instead of
exact summation, which is what makes this "Monte Carlo" rather than just
a formula tweak on Model 1.

What's cited vs. calibrated vs. this project's own limitation, same
honesty standard as the other two models:

1. The correction itself - the tau(x,y) function below - is CITED
   directly from Dixon, M.J. and Coles, S.G. (1997), "Modelling
   Association Football Scores and Inefficiencies in the Betting
   Market", Journal of the Royal Statistical Society: Series C, 46(2).
   It only adjusts the four low-score cells (0-0, 1-0, 0-1, 1-1); every
   other scoreline is unadjusted (tau=1), exactly as the paper defines it.

2. rho (the correlation strength parameter) - NOT calibrated from this
   project's own data, unlike Model 3's home-advantage estimate. Doing
   that properly means reconstructing every historical match's
   lambda/mu at the time it was played (team strength changes over a
   season) and maximum-likelihood-fitting rho against real results - a
   real statistical estimation project of its own, out of scope here.
   Instead this uses Dixon & Coles' own published estimate from their
   original paper's English league data: rho = -0.13. This is a real,
   cited number, but it's from their dataset, not refit on current EPL
   results - refitting it properly is a legitimate future improvement,
   not attempted here.

3. Monte Carlo simulation via rejection sampling: samples (home_goals,
   away_goals) independently from Poisson(lambda_home)/Poisson(mu_away)
   (Model 1's rates), then accepts each sample with probability
   tau(x,y)/tau_max - standard rejection sampling against an unnormalized
   target density. This is a real, correct simulation technique for this
   problem, not an approximation shortcut.
"""

import math
import random
from dataclasses import dataclass, field

from sports.epl.models.poisson_xg import poisson_pmf

# Dixon & Coles' (1997) own published estimate, English league data -
# see module docstring point 2 for why this isn't refit here
DEFAULT_RHO = -0.13


@dataclass
class OutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


@dataclass
class SimulationResult:
    outcome: OutcomeProbabilities
    scoreline_counts: dict  # (home_goals, away_goals) -> count, over n_simulations
    n_simulations: int
    rho_used: float


def tau(x, y, lambda_home, mu_away, rho):
    """Dixon & Coles' (1997) low-score correlation adjustment (see module
    docstring point 1). Defined only for x,y in {0,1}; returns 1.0
    (no adjustment) for every other scoreline, exactly as the paper
    specifies."""
    if x == 0 and y == 0:
        return 1.0 - (lambda_home * mu_away * rho)
    if x == 0 and y == 1:
        return 1.0 + (lambda_home * rho)
    if x == 1 and y == 0:
        return 1.0 + (mu_away * rho)
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def simulate_match(lambda_home, mu_away, rho=DEFAULT_RHO, n_simulations=20000, seed=None):
    """Runs a Dixon-Coles-adjusted Monte Carlo simulation of a single
    match and returns a SimulationResult with three-way outcome
    probabilities and the full simulated scoreline distribution (useful
    for e.g. a totals/over-under signal, not just win/draw/loss).

    Rejection sampling (see module docstring point 3): draws
    (home_goals, away_goals) from independent Poisson(lambda_home)/
    Poisson(mu_away), accepts each draw with probability
    tau(x,y)/tau_max, and redraws on rejection - a standard, correct
    technique for sampling from an unnormalized target density
    (independent_poisson(x,y) * tau(x,y)) using the independent Poisson
    itself as the proposal distribution.

    max_goals=15 bounds the sampled range for building the proposal's
    goal-count draws (via inverse-CDF on the Poisson pmf) - negligible
    probability mass exists beyond that for realistic EPL scoring rates,
    verified the same way as poisson_xg.score_distribution's max_goals.
    """
    rng = random.Random(seed)
    max_goals = 15

    home_cdf = _poisson_cdf_table(lambda_home, max_goals)
    away_cdf = _poisson_cdf_table(mu_away, max_goals)

    # tau_max: the adjustment only touches 4 cells, and is always 1.0
    # everywhere else, so the envelope only needs to cover those 4 plus
    # the baseline 1.0 - computing it once per match rather than per draw
    tau_max = max(
        1.0,
        tau(0, 0, lambda_home, mu_away, rho),
        tau(0, 1, lambda_home, mu_away, rho),
        tau(1, 0, lambda_home, mu_away, rho),
        tau(1, 1, lambda_home, mu_away, rho),
    )

    scoreline_counts = {}
    accepted = 0
    attempts = 0
    max_attempts = n_simulations * 20  # generous ceiling - guards against a
    # pathological rho making acceptance rate collapse, rather than looping forever

    while accepted < n_simulations and attempts < max_attempts:
        attempts += 1
        h = _sample_from_cdf(home_cdf, rng)
        a = _sample_from_cdf(away_cdf, rng)
        accept_prob = tau(h, a, lambda_home, mu_away, rho) / tau_max
        if rng.random() < accept_prob:
            accepted += 1
            scoreline_counts[(h, a)] = scoreline_counts.get((h, a), 0) + 1

    if accepted == 0:
        raise RuntimeError("Monte Carlo simulation produced zero accepted samples - check lambda/mu/rho inputs")

    home_wins = sum(c for (h, a), c in scoreline_counts.items() if h > a)
    draws = sum(c for (h, a), c in scoreline_counts.items() if h == a)
    away_wins = sum(c for (h, a), c in scoreline_counts.items() if h < a)

    return SimulationResult(
        outcome=OutcomeProbabilities(
            home_win=home_wins / accepted,
            draw=draws / accepted,
            away_win=away_wins / accepted,
        ),
        scoreline_counts=scoreline_counts,
        n_simulations=accepted,
        rho_used=rho,
    )


def _poisson_cdf_table(lam, max_goals):
    table = []
    cumulative = 0.0
    for k in range(max_goals + 1):
        cumulative += poisson_pmf(k, lam)
        table.append(cumulative)
    return table


def _sample_from_cdf(cdf_table, rng):
    u = rng.random() * cdf_table[-1]  # scale to the table's actual total (slightly <1 due to truncation)
    for k, cum in enumerate(cdf_table):
        if u <= cum:
            return k
    return len(cdf_table) - 1
