"""
Model-improvement groundwork (analysis only - does not touch the live
model in sports/mlb/fetch/mymodel.py or main.py's daily pipeline):

  1. ROLLING WINDOW LENGTH: My model's team-batting factor uses a 15-day
     trailing Statcast xwOBA window (TEAM_XWOBA_WINDOW_DAYS in
     fetch/mymodel.py). This tests whether 7/15/30-day windows actually
     predict a team's real runs-scored better or worse, using this
     project's own logged history (results_log.csv's dates/scores) as
     the test set.

     Scope note: this isolates the team-batting side only - correlating
     a team's trailing xwOBA (at each window length) against that team's
     actual runs scored in the game, rather than re-running the full
     two-sided My model formula. The full model also needs the correct
     opposing starting pitcher for each historical game, which isn't in
     this project's logs (predictions_log.csv records the final
     projected-runs output, not per-game pitcher IDs) - a clean,
     honestly-scoped way to test window length in isolation without
     needing data this project doesn't have.

  2. PITCHER VS. TEAM-BATTING REAL-WORLD SPREAD: the model's formula
     (batting_team_xwoba / league_xwoba) * (pitcher_xwoba_allowed /
     league_xwoba) is symmetric by construction - a 10% swing in either
     factor moves the projection by exactly the same 10%, confirmed by
     inspection of _project_runs() in fetch/mymodel.py. But the formula
     being symmetric doesn't mean the two sides swing by the same amount
     in real data - if one factor's real spread across teams/pitchers is
     wider than the other's, it ends up mattering more in practice
     despite the formula treating them equally. This pulls one day's real
     team-xwoba-across-30-teams and pitcher-xwoba-allowed-across-starters
     to compare their actual standard deviations.

Same reason every other Statcast-touching script in this project is a
probe-style one-off run via GitHub Actions workflow_dispatch: this dev
sandbox cannot reach baseballsavant.mlb.com directly.
"""

import csv
import statistics
import sys
from datetime import date as date_cls
from datetime import timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sports.mlb.fetch.mymodel import HEADERS, _normalize_abbrev  # noqa: E402

RESULTS_LOG_PATH = Path(__file__).resolve().parent.parent / "sports" / "mlb" / "data" / "results_log.csv"
WINDOW_LENGTHS = (7, 15, 30)


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def _load_results():
    with RESULTS_LOG_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("status") == "Final" and r.get("away_score") and r.get("home_score")]


def _team_xwoba_for_window(as_of_date, window_days):
    """Pulls ONE league-wide Statcast slice covering [as_of_date - 30,
    as_of_date - 1] and slices it down to the requested window
    client-side, rather than a separate network pull per window length -
    same idea as fetch_team_xwoba() in mymodel.py, generalized to accept
    any window <= 30 days from a single pull."""
    import pandas as pd
    import pybaseball as pb

    start = as_of_date - timedelta(days=30)
    end = as_of_date - timedelta(days=1)
    df = pb.statcast(str(start), str(end))
    if df is None or len(df) == 0:
        return {}

    df = df[df["woba_denom"] > 0].copy()
    if len(df) == 0:
        return {}
    df["game_date"] = pd.to_datetime(df["game_date"])
    cutoff = pd.Timestamp(as_of_date - timedelta(days=window_days))
    df = df[df["game_date"] >= cutoff]
    if len(df) == 0:
        return {}

    df["batting_team"] = df.apply(lambda r: r["away_team"] if r["inning_topbot"] == "Top" else r["home_team"], axis=1)
    df["xwoba_component"] = df["estimated_woba_using_speedangle"].fillna(df["woba_value"])

    team_xwoba = {}
    for raw_team, group in df.groupby("batting_team"):
        ab = _normalize_abbrev(raw_team)
        if not ab:
            continue
        denom_sum = group["woba_denom"].sum()
        if denom_sum:
            team_xwoba[ab] = float((group["xwoba_component"] * group["woba_denom"]).sum() / denom_sum)
    return team_xwoba


def probe_window_backtest():
    hr("1. Rolling xwOBA window backtest (team-batting side only)")
    results = _load_results()
    dates = sorted({r["date"] for r in results})
    print(f"Testing {len(dates)} date(s) with final results: {dates}")

    pairs_by_window = {w: [] for w in WINDOW_LENGTHS}
    for date_str in dates:
        y, m, d = (int(x) for x in date_str.split("-"))
        as_of = date_cls(y, m, d)
        games_today = [r for r in results if r["date"] == date_str]
        print(f"\n-- {date_str}: {len(games_today)} final game(s) --")

        for window_days in WINDOW_LENGTHS:
            try:
                team_xwoba = _team_xwoba_for_window(as_of, window_days)
            except Exception as e:
                print(f"  [warn] {window_days}d pull failed for {date_str}: {e}")
                continue
            n_matched = 0
            for g in games_today:
                for team, runs in ((g["away_abbrev"], g["away_score"]), (g["home_abbrev"], g["home_score"])):
                    xwoba = team_xwoba.get(team)
                    if xwoba is not None:
                        pairs_by_window[window_days].append((xwoba, float(runs)))
                        n_matched += 1
            print(f"  {window_days:>2}d window: {len(team_xwoba)} teams with data, {n_matched} team-games matched")

    hr("Window backtest results (correlation between trailing team xwOBA and that team's actual runs scored)")
    print(f"{'window':>8} {'n':>5} {'pearson_r':>10}")
    for window_days in WINDOW_LENGTHS:
        pairs = pairs_by_window[window_days]
        n = len(pairs)
        if n < 3:
            print(f"{window_days:>7}d {n:>5}  not enough data")
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        try:
            r = statistics.correlation(xs, ys)
        except statistics.StatisticsError:
            r = None
        r_str = f"{r:.3f}" if r is not None else "n/a"
        print(f"{window_days:>7}d {n:>5} {r_str:>10}")
    print("\nHigher |pearson_r| = that window length's recent team xwOBA tracked actual runs scored more closely in this sample.")
    print("Small-sample caveat: this is a relative comparison across window lengths on the same handful of logged days, not an absolute accuracy claim.")


def probe_pitcher_vs_team_spread():
    hr("2. Real-world spread: team-batting xwOBA vs. pitcher xwOBA-allowed")
    import pybaseball as pb

    today = date_cls.today()
    team_xwoba = _team_xwoba_for_window(today, 15)
    print(f"Team xwOBA (15d window, {len(team_xwoba)} teams): {sorted(team_xwoba.values())}")
    if len(team_xwoba) >= 2:
        team_stdev = statistics.stdev(team_xwoba.values())
        team_mean = statistics.mean(team_xwoba.values())
        print(f"  mean={team_mean:.4f}  stdev={team_stdev:.4f}  coefficient_of_variation={team_stdev / team_mean:.4f}")

    df = pb.statcast_pitcher_expected_stats(today.year, minPA=30)
    if df is None or len(df) == 0:
        print("statcast_pitcher_expected_stats returned no rows - skipping pitcher spread")
        return
    pitcher_xwoba_allowed = [float(v) for v in df["est_woba"].dropna().tolist()]
    print(f"Pitcher xwOBA-allowed (season, {len(pitcher_xwoba_allowed)} qualified pitchers, minPA=30)")
    if len(pitcher_xwoba_allowed) >= 2:
        p_stdev = statistics.stdev(pitcher_xwoba_allowed)
        p_mean = statistics.mean(pitcher_xwoba_allowed)
        print(f"  mean={p_mean:.4f}  stdev={p_stdev:.4f}  coefficient_of_variation={p_stdev / p_mean:.4f}")

    print("\nA higher coefficient_of_variation means that side of the formula swings further (as a %) across real teams/")
    print("pitchers - i.e. carries more real-world influence on My model's projections in practice, even though the")
    print("formula itself weights both factors identically (see module docstring).")


def main():
    try:
        probe_window_backtest()
    except Exception as e:
        print(f"[error] window backtest failed: {e}")
        raise
    try:
        probe_pitcher_vs_team_spread()
    except Exception as e:
        print(f"[error] pitcher/team spread check failed: {e}")
        raise


if __name__ == "__main__":
    main()
