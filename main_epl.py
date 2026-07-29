"""
Orchestrates the daily EPL analysis report: fetches all sources
(isolating failures so one bad source doesn't take down the report),
calibrates the models from real prior-season data, builds the joined
report data, renders static HTML, and writes it to docs/ (epl-prefixed,
so it never overwrites MLB's index.html/dated pages).

Usage: python main_epl.py
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sports.epl.analysis.build import build_report_data
from sports.epl.fetch import clubelo, dratings, football_data, reddit, understat
from sports.epl.models import elo, poisson_xg
from sports.epl.report import render
from sports.mlb.report import fonts  # sport-agnostic (Oswald/Inter) - reused as-is, not duplicated

UTC = ZoneInfo("UTC")
PT = ZoneInfo("America/Los_Angeles")
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
FONT_CACHE_PATH = Path(__file__).resolve().parent / "sports" / "epl" / "report" / "inline_fonts.cache.css"


def _inline_font_css():
    if FONT_CACHE_PATH.exists():
        return FONT_CACHE_PATH.read_text(encoding="utf-8")
    css = fonts.build_inline_font_css()
    FONT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FONT_CACHE_PATH.write_text(css, encoding="utf-8")
    return css


def _fetch_safe(label, fn, default):
    try:
        return fn()
    except Exception as e:
        print(f"[warn] {label} fetch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return default


def main():
    now_utc = datetime.now(UTC)
    today_iso = now_utc.strftime("%Y-%m-%d")
    today_display = now_utc.strftime("%A, %B %-d, %Y")
    generated_at = datetime.now(PT).strftime("%Y-%m-%d %H:%M %Z")

    print(f"Building EPL daily analysis for {today_display} ({today_iso})")

    fd_matches = _fetch_safe("football-data.org", football_data.fetch_todays_matches, [])
    print(f"football-data.org: {len(fd_matches)} fixture(s) today")

    next_fixture_date = None
    if not fd_matches:
        # real value for the "no fixtures today" banner, not a guess -
        # the earliest actual upcoming scheduled kickoff, if any exists
        upcoming = _fetch_safe("football-data.org (upcoming)", football_data.fetch_upcoming_matches, [])
        if upcoming:
            next_fixture_date = min(m.utc_kickoff for m in upcoming)
            print(f"Next real fixture: {next_fixture_date.isoformat()}")

    dr_matches = _fetch_safe("DRatings", dratings.fetch_upcoming_matches, [])
    print(f"DRatings: {len(dr_matches)} upcoming match(es)")

    clubelo_ratings = _fetch_safe("ClubElo", clubelo.fetch_current_ratings, {})
    print(f"ClubElo: {len(clubelo_ratings)} club(s)")

    current_season = understat.current_season_start_year()
    understat_histories = _fetch_safe(
        "Understat (current season)", lambda: understat.fetch_team_xg_history(season=current_season), {}
    )
    if not understat_histories:
        # current season may not have started yet (see understat.py's
        # module docstring) - fall back to the last completed season so
        # the models still have real data to calibrate from
        print(f"Understat: no data for season {current_season} (likely not started yet) - trying {current_season - 1}")
        understat_histories = _fetch_safe(
            "Understat (prior season)", lambda: understat.fetch_team_xg_history(season=current_season - 1), {}
        )
    print(f"Understat: {len(understat_histories)} team(s) with xG history")

    reddit_result = _fetch_safe("Reddit", reddit.fetch_recent_mentions, reddit.RedditResult(available=False, note="fetch raised an exception"))
    print(f"Reddit: available={reddit_result.available}")

    # Model calibration - real prior-season data, not guessed constants
    # (see sports/epl/models/elo.py's module docstring for why)
    elo_home_advantage, elo_draw_rate = 60.0, 0.24  # sane fallback if calibration data is unavailable
    try:
        calibration_matches = football_data.fetch_season_matches(current_season - 1, status="FINISHED")
        if calibration_matches:
            elo_home_advantage = elo.calibrate_home_advantage_elo(calibration_matches)
            elo_draw_rate = elo.calibrate_draw_rate(calibration_matches)
            print(f"Elo calibration: home_advantage={elo_home_advantage:.1f} elo pts, draw_rate={elo_draw_rate:.3f} (from {len(calibration_matches)} finished matches, season {current_season - 1})")
        else:
            print(f"[warn] no finished matches found for season {current_season - 1} - using fallback Elo calibration ({elo_home_advantage}, {elo_draw_rate})")
    except Exception as e:
        print(f"[warn] Elo calibration failed: {e} - using fallback ({elo_home_advantage}, {elo_draw_rate})", file=sys.stderr)

    poisson_league_rates = None
    try:
        if understat_histories:
            poisson_league_rates = poisson_xg.compute_league_rates(understat_histories, min_matches=3)
            print(f"Poisson/xG calibration: {len(poisson_league_rates.teams)} team(s) with enough matches")
    except ValueError as e:
        print(f"[warn] Poisson/xG league-rate calibration failed: {e}", file=sys.stderr)

    if poisson_league_rates is None:
        # no real xG data to calibrate from at all - Poisson/xG and
        # Dixon-Coles simply won't produce picks for any fixture (see
        # build_report_data's per-fixture graceful degrade), rather than
        # fabricate rates. An empty LeagueRates keeps build_report_data's
        # signature simple without a None-check at every call site.
        poisson_league_rates = poisson_xg.LeagueRates(league_avg_home_xg=0.0, league_avg_away_xg=0.0, teams={})

    report_data = build_report_data(
        fd_matches, dr_matches, clubelo_ratings, understat_histories, reddit_result,
        today_iso, today_display,
        elo_home_advantage, elo_draw_rate, poisson_league_rates,
        next_fixture_date=next_fixture_date,
    )

    inline_font_css = _fetch_safe("Google Fonts (Oswald/Inter)", _inline_font_css, "")
    if inline_font_css:
        print(f"Inline fonts: {len(inline_font_css) // 1024}KB embedded")

    html = render.render_report(report_data, generated_at, inline_font_css)
    fragment_html = render.render_artifact_fragment(report_data, generated_at, inline_font_css)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = OUTPUT_DIR / f"epl-{today_iso}.html"
    index_path = OUTPUT_DIR / "epl.html"
    fragment_path = OUTPUT_DIR / "epl_artifact_fragment.html"
    dated_path.write_text(html, encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")
    fragment_path.write_text(fragment_html, encoding="utf-8")

    print(f"Wrote {dated_path}, {index_path}, and {fragment_path}")


if __name__ == "__main__":
    main()
