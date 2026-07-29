"""
Joins EPL fixtures across sources and runs all three models to build the
per-fixture data the report template renders.

Anchor for "today's fixtures" is football-data.org (the only source with
real kickoff-date fixtures) - DRatings, ClubElo, and Understat entries
are matched onto it by canonical club name (sports.epl.teams), since each
source spells names differently. A fixture with no match in a given
source just gets None for that source's fields (same "degrade gracefully,
never fabricate" posture as every fetch module here) - it is NOT dropped
from the slate.

Model calibration (Elo home-advantage/draw-rate, Poisson/xG league rates)
is computed once per report build, not per fixture, and passed in - see
build_report_data's calibration params.
"""

from dataclasses import dataclass, field

from core import conviction, flagging
from sports.epl.models import dixon_coles, elo, poisson_xg
from sports.epl.teams import canonical_name, short_code


@dataclass
class ModelPick:
    label: str  # "DRatings", "Elo", "Poisson/xG", "Dixon-Coles"
    home_pct: float | None
    draw_pct: float | None
    away_pct: float | None


@dataclass
class Fixture:
    away_team: str
    home_team: str
    away_tla: str | None
    home_tla: str | None
    kickoff: object  # datetime | None
    matchday: int | None

    dratings: object = None       # DRatingsMatch | None
    elo_home: float | None = None
    elo_away: float | None = None

    model_picks: list = field(default_factory=list)  # list[ModelPick]
    dc_scoreline_top: tuple | None = None  # (home_goals, away_goals) most-simulated scoreline

    flags: list = field(default_factory=list)
    conviction_row: object = None  # core.conviction.ConvictionRow | None


def _index_by_name(items, name_fn):
    index = {}
    for item in items:
        canon = canonical_name(name_fn(item))
        if canon:
            index[canon] = item
    return index


def _direction_label(direction, away_tla, home_tla):
    if direction == "home":
        return home_tla or "home"
    if direction == "away":
        return away_tla or "away"
    return "Draw"


def _check_model_disagreement(fx):
    """Flags a fixture where the models don't just lean differently but
    actively favor opposite sides (not merely a close call)."""
    directions = set()
    for pick in fx.model_picks:
        if pick.home_pct is None:
            continue
        if pick.home_pct > pick.away_pct and pick.home_pct > pick.draw_pct:
            directions.add("home")
        elif pick.away_pct > pick.home_pct and pick.away_pct > pick.draw_pct:
            directions.add("away")
        else:
            directions.add("draw")
    if len(directions) >= 3:
        return flagging.Flag(
            code="model_split",
            label="Models split 3 ways",
            detail="Elo, Poisson/xG, and Dixon-Coles each favor a different outcome.",
        )
    if "home" in directions and "away" in directions:
        return flagging.Flag(
            code="model_disagreement",
            label="Models disagree on winner",
            detail="At least one model favors the home side and another favors the away side.",
        )
    return None


def _check_dratings_gap(fx):
    """Flags when DRatings' own win-probability favorite disagrees with
    the models' majority favorite - a real external-vs-internal check,
    same spirit as MLB's model-vs-market checks."""
    if not fx.dratings or fx.dratings.away_win_pct is None or fx.dratings.home_win_pct is None:
        return None
    dr_direction = "home" if fx.dratings.home_win_pct > fx.dratings.away_win_pct else "away"
    if fx.dratings.draw_pct is not None and fx.dratings.draw_pct > fx.dratings.home_win_pct and fx.dratings.draw_pct > fx.dratings.away_win_pct:
        dr_direction = "draw"

    model_directions = []
    for pick in fx.model_picks:
        if pick.home_pct is None:
            continue
        if pick.home_pct > pick.away_pct and pick.home_pct > pick.draw_pct:
            model_directions.append("home")
        elif pick.away_pct > pick.home_pct and pick.away_pct > pick.draw_pct:
            model_directions.append("away")
        else:
            model_directions.append("draw")
    if not model_directions:
        return None
    from collections import Counter
    majority = Counter(model_directions).most_common(1)[0][0]
    if majority != dr_direction:
        return flagging.Flag(
            code="dratings_vs_models",
            label="DRatings vs. models",
            detail=f"DRatings favors {_direction_label(dr_direction, fx.away_tla, fx.home_tla)}; the models' majority favors {_direction_label(majority, fx.away_tla, fx.home_tla)}.",
        )
    return None


EPL_CHECKS = (_check_model_disagreement, _check_dratings_gap)


def build_report_data(
    football_data_matches,
    dratings_matches,
    clubelo_ratings,
    understat_histories,
    reddit_result,
    today_iso,
    today_display,
    elo_home_advantage,
    elo_draw_rate,
    poisson_league_rates,
    next_fixture_date=None,
):
    """football_data_matches: list[FootballDataMatch], the fixture anchor.
    dratings_matches/clubelo_ratings/understat_histories: raw fetch
    results, matched onto the anchor by canonical club name here.
    elo_home_advantage/elo_draw_rate: from
    sports.epl.models.elo.calibrate_*, computed once by the caller from a
    real prior season (see main_epl.py). poisson_league_rates: a
    sports.epl.models.poisson_xg.LeagueRates, likewise computed once.
    Every per-fixture model failure degrades that one fixture's own
    fields to None rather than failing the whole report - same posture
    as every build module in this project."""
    # DRatings rows need to be found by either home or away team name
    # (the anchor fixture could match on either side) - index both
    dratings_index = {}
    for m in dratings_matches:
        h = canonical_name(m.home_team)
        a = canonical_name(m.away_team)
        if h:
            dratings_index[h] = m
        if a:
            dratings_index.setdefault(a, m)

    elo_index = _index_by_name(clubelo_ratings.values(), lambda r: r.club)
    understat_index = _index_by_name(understat_histories.values(), lambda h: h.title)

    fixtures = []
    for fdm in football_data_matches:
        home_canon = canonical_name(fdm.home_team)
        away_canon = canonical_name(fdm.away_team)

        dr = dratings_index.get(home_canon) or dratings_index.get(away_canon)
        # only trust a DRatings match if it's actually this exact fixture
        # (both teams match), not just a row that happens to share one club
        if dr and not ({canonical_name(dr.home_team), canonical_name(dr.away_team)} == {home_canon, away_canon}):
            dr = None

        elo_home = elo_index.get(home_canon)
        elo_away = elo_index.get(away_canon)

        fx = Fixture(
            away_team=fdm.away_team,
            home_team=fdm.home_team,
            away_tla=fdm.away_tla or short_code(fdm.away_team),
            home_tla=fdm.home_tla or short_code(fdm.home_team),
            kickoff=fdm.utc_kickoff,
            matchday=fdm.matchday,
            dratings=dr,
            elo_home=elo_home.elo if elo_home else None,
            elo_away=elo_away.elo if elo_away else None,
        )

        picks = []
        if dr and dr.away_win_pct is not None and dr.home_win_pct is not None:
            picks.append(ModelPick("DRatings", home_pct=dr.home_win_pct, draw_pct=dr.draw_pct, away_pct=dr.away_win_pct))

        if elo_home and elo_away:
            try:
                probs = elo.predict_outcome_probabilities(elo_home.elo, elo_away.elo, elo_home_advantage, elo_draw_rate)
                picks.append(ModelPick("Elo", home_pct=probs.home_win * 100, draw_pct=probs.draw * 100, away_pct=probs.away_win * 100))
            except Exception:
                pass

        home_hist_id = understat_index.get(home_canon)
        away_hist_id = understat_index.get(away_canon)
        lam = mu = None
        if home_hist_id and away_hist_id:
            try:
                lam, mu = poisson_xg.expected_goals(home_hist_id.team_id, away_hist_id.team_id, poisson_league_rates)
                probs = poisson_xg.predict_outcome_probabilities(lam, mu)
                picks.append(ModelPick("Poisson/xG", home_pct=probs.home_win * 100, draw_pct=probs.draw * 100, away_pct=probs.away_win * 100))
            except (KeyError, ValueError):
                pass

        if lam is not None and mu is not None:
            try:
                sim = dixon_coles.simulate_match(lam, mu, n_simulations=20000)
                picks.append(ModelPick("Dixon-Coles", home_pct=sim.outcome.home_win * 100, draw_pct=sim.outcome.draw * 100, away_pct=sim.outcome.away_win * 100))
                if sim.scoreline_counts:
                    fx.dc_scoreline_top = max(sim.scoreline_counts.items(), key=lambda kv: kv[1])[0]
            except RuntimeError:
                pass

        fx.model_picks = picks
        fx.flags = flagging.run_checks(fx, EPL_CHECKS)

        votes = []
        for pick in picks:
            if pick.home_pct is None:
                continue
            if pick.home_pct > pick.away_pct and pick.home_pct > pick.draw_pct:
                votes.append((pick.label, "home"))
            elif pick.away_pct > pick.home_pct and pick.away_pct > pick.draw_pct:
                votes.append((pick.label, "away"))
            else:
                votes.append((pick.label, "draw"))
        fx.conviction_row = conviction.tally_votes(
            votes, min_sources=2, max_dissent=1,
            direction_to_label=lambda d: _direction_label(d, fx.away_tla, fx.home_tla),
        )

        fixtures.append(fx)

    notable_fixtures = [fx for fx in fixtures if fx.flags]

    # A real off-season/between-matchdays gap produces an honest but
    # repetitive page (every section says "no fixtures"/"not built yet"
    # in a row) - this banner gives a visitor the one-line explanation up
    # front instead of making them read six empty boxes to piece it
    # together. next_fixture_date, when given, is a real value the caller
    # fetched (the earliest real upcoming kickoff) - never guessed here.
    no_fixtures_banner = None
    if not fixtures:
        if next_fixture_date is not None:
            no_fixtures_banner = (
                f"No Premier League fixtures today. The next one is "
                f"{next_fixture_date.strftime('%A, %B %-d')} - check back then for model predictions."
            )
        else:
            no_fixtures_banner = (
                "No Premier League fixtures today, and no upcoming fixture could be found either "
                "(likely between seasons). Check back once the schedule is confirmed."
            )

    return {
        "sport": "epl",
        "date_iso": today_iso,
        "date_display": today_display,
        "fixtures": fixtures,
        "no_fixtures_banner": no_fixtures_banner,
        "notable_fixtures": notable_fixtures,
        "reddit": reddit_result,
        "source_urls": {
            "DRatings": "https://www.dratings.com/predictor/english-premier-league-predictions/",
            "ClubElo": "http://clubelo.com/",
            "Understat": "https://understat.com/league/EPL",
            "football-data.org": "https://www.football-data.org/",
        },
    }
