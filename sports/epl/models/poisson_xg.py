"""
Model 1: Poisson/xG. Converts each team's real Understat xG history into
a per-match expected-goals rate for both sides, then treats each team's
goal count as an independent Poisson random variable to get a full
scoreline distribution and three-way outcome probabilities.

What's cited vs. adapted here, same honesty standard as every other
model in this project:

The underlying structure - each team has an "attack strength" and
"defense weakness" relative to the league average, multiplied together
(with a home/away split) to get a match's expected goals, then treated as
independent Poisson - is Maher's foundational 1982 football-scoring model
("Modelling Association Football Scores", Statistica Neerlandica), the
same structure nearly every subsequent goals-based football model
(including Dixon-Coles, see dixon_coles.py) builds on. That structure is
cited, not invented here.

This project's adaptation: Maher's original model (and most classic
implementations) uses actual goals scored/conceded to estimate attack/
defense strength. This uses real Understat xG instead (xG-for/xG-against
per team, from sports/epl/fetch/understat.py's real match history) -
expected goals is a well-established, widely-used improvement over raw
goals for exactly this purpose in modern football analytics (actual goal
counts in a single match are highly noisy - a team can generate great
chances and not score, or score once from their only shot - xG is a much
more stable signal of real chance quality match-to-match). Using xG here
instead of goals is this project's deliberate choice, not something
Maher's original paper itself specifies.

Known limitation carried into Model 2 as well: an independent-Poisson
model of this kind is well documented to underrate draws and low-scoring
correlated outcomes (0-0, 1-1) - this is exactly the gap Dixon & Coles'
1997 paper addresses with a low-score correlation correction. Model 2
(dixon_coles.py) is that correction, not a separate unrelated model.
"""

import math
from dataclasses import dataclass, field


@dataclass
class TeamRates:
    team_id: str
    title: str
    home_attack: float   # relative to league-average home xG-for (1.0 = average)
    home_defense: float  # relative to league-average away xG-for allowed (1.0 = average)
    away_attack: float
    away_defense: float
    matches_used: int


@dataclass
class LeagueRates:
    league_avg_home_xg: float
    league_avg_away_xg: float
    teams: dict = field(default_factory=dict)  # team_id -> TeamRates


@dataclass
class OutcomeProbabilities:
    home_win: float
    draw: float
    away_win: float


def compute_league_rates(xg_histories, min_matches=3):
    """Builds LeagueRates from {team_id: TeamXGHistory} (see
    sports.epl.fetch.understat.fetch_team_xg_history). Teams with fewer
    than min_matches home or away matches are skipped for that side's
    rate (too little signal - not silently given a fabricated average),
    but still included in league-average computation using whatever
    matches they do have. Raises ValueError if there isn't enough total
    data to compute league averages at all."""
    home_xg_for_total, home_xg_for_n = 0.0, 0
    away_xg_for_total, away_xg_for_n = 0.0, 0

    per_team_home = {}  # team_id -> list of (xg_for, xg_against)
    per_team_away = {}

    for team_id, hist in xg_histories.items():
        for m in hist.matches:
            if m.home_away == "h":
                home_xg_for_total += m.xg_for
                home_xg_for_n += 1
                per_team_home.setdefault(team_id, []).append((m.xg_for, m.xg_against))
            else:
                away_xg_for_total += m.xg_for
                away_xg_for_n += 1
                per_team_away.setdefault(team_id, []).append((m.xg_for, m.xg_against))

    if home_xg_for_n == 0 or away_xg_for_n == 0:
        raise ValueError("no home/away xG data available to compute league rates")

    league_avg_home_xg = home_xg_for_total / home_xg_for_n
    league_avg_away_xg = away_xg_for_total / away_xg_for_n

    teams = {}
    for team_id, hist in xg_histories.items():
        home_matches = per_team_home.get(team_id, [])
        away_matches = per_team_away.get(team_id, [])

        home_attack = home_defense = away_attack = away_defense = None
        if len(home_matches) >= min_matches:
            avg_for = sum(x[0] for x in home_matches) / len(home_matches)
            avg_against = sum(x[1] for x in home_matches) / len(home_matches)
            home_attack = avg_for / league_avg_home_xg
            # this team's home defense compared to what an average team
            # concedes at home (i.e. what away teams' xg_for averages to)
            home_defense = avg_against / league_avg_away_xg
        if len(away_matches) >= min_matches:
            avg_for = sum(x[0] for x in away_matches) / len(away_matches)
            avg_against = sum(x[1] for x in away_matches) / len(away_matches)
            away_attack = avg_for / league_avg_away_xg
            away_defense = avg_against / league_avg_home_xg

        if None in (home_attack, home_defense, away_attack, away_defense):
            continue  # not enough data for this team on at least one side - skip, don't fabricate

        teams[team_id] = TeamRates(
            team_id=team_id,
            title=hist.title,
            home_attack=home_attack,
            home_defense=home_defense,
            away_attack=away_attack,
            away_defense=away_defense,
            matches_used=len(home_matches) + len(away_matches),
        )

    return LeagueRates(
        league_avg_home_xg=league_avg_home_xg,
        league_avg_away_xg=league_avg_away_xg,
        teams=teams,
    )


def expected_goals(home_team_id, away_team_id, league_rates):
    """Returns (lambda_home, mu_away) - expected goals for each side in a
    specific matchup, per Maher's multiplicative structure (see module
    docstring). Raises KeyError if either team isn't in league_rates
    (e.g. too little real data - see compute_league_rates's min_matches),
    rather than silently defaulting to a league-average team."""
    home = league_rates.teams[home_team_id]
    away = league_rates.teams[away_team_id]
    lambda_home = league_rates.league_avg_home_xg * home.home_attack * away.away_defense
    mu_away = league_rates.league_avg_away_xg * away.away_attack * home.home_defense
    return lambda_home, mu_away


def poisson_pmf(k, lam):
    """Public - reused as-is by dixon_coles.py's Monte Carlo sampler,
    since both models start from the same independent-Poisson base."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def score_distribution(lambda_home, mu_away, max_goals=10):
    """Returns a dict {(home_goals, away_goals): probability} for
    home_goals, away_goals in [0, max_goals], treating both as
    independent Poisson (see module docstring for the known low-score
    correlation limitation this doesn't correct - that's Model 2's job).
    Probabilities beyond max_goals each way are negligible for realistic
    football xG rates and are dropped, not redistributed - the returned
    dict's total will be very slightly under 1.0 (verified this stays
    well under 0.1% for max_goals=10 at realistic EPL scoring rates)."""
    home_pmf = [poisson_pmf(k, lambda_home) for k in range(max_goals + 1)]
    away_pmf = [poisson_pmf(k, mu_away) for k in range(max_goals + 1)]
    return {
        (h, a): home_pmf[h] * away_pmf[a]
        for h in range(max_goals + 1)
        for a in range(max_goals + 1)
    }


def predict_outcome_probabilities(lambda_home, mu_away, max_goals=10):
    """Returns OutcomeProbabilities from the independent-Poisson score
    distribution (see score_distribution)."""
    dist = score_distribution(lambda_home, mu_away, max_goals=max_goals)
    p_home = sum(p for (h, a), p in dist.items() if h > a)
    p_draw = sum(p for (h, a), p in dist.items() if h == a)
    p_away = sum(p for (h, a), p in dist.items() if h < a)
    return OutcomeProbabilities(home_win=p_home, draw=p_draw, away_win=p_away)
