"""
First recon pass for the EPL expansion (see CLAUDE task list: "EPL: build
fetchers"). Same reason this exists as scripts/probe_sources.py did for
MLB originally: this dev sandbox cannot reach any of these hosts directly
(confirmed - plain `curl` to dratings.com and football-data.org both hang/
fail here), so real payload shapes have to come from a GitHub Actions run
(which has real internet access) before sports/epl/fetch/*.py can be
written against actual field names instead of guesses.

Nothing here is a finished fetcher. Each probe_* function is throwaway
reconnaissance - print raw structure, note what a real parser would need to
handle. Once this has run in Actions and the job log shows real data, the
real fetch modules get written the same way MLB's were (see e.g.
sports/mlb/fetch/kalshi.py's docstring for the pattern: cite what the probe
showed, then implement against it).

Known gap going in: football-data.org requires a free API token
(X-Auth-Token header) that this environment doesn't have. That probe will
report clearly whether FOOTBALL_DATA_TOKEN is set rather than silently
skip - if it's missing, that's a real blocker for the user to resolve
(sign up at football-data.org, add the token as a repo secret), not
something to work around.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def get(url, headers=BROWSER_HEADERS, **kwargs):
    r = requests.get(url, headers=headers, timeout=20, **kwargs)
    print(f"status={r.status_code}  bytes={len(r.content)}")
    return r


def probe_dratings_epl():
    hr("DRatings: locate the EPL/soccer predictions page + table structure")
    candidates = [
        "https://www.dratings.com/predictor/soccer-predictions/premier-league/",
        "https://www.dratings.com/predictor/soccer-predictions/",
        "https://www.dratings.com/predictor/english-premier-league-predictions/",
    ]
    for url in candidates:
        print(f"\n--- trying {url} ---")
        try:
            r = get(url)
            if r.status_code != 200:
                print(f"non-200, skipping: {r.text[:300]}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            heading = soup.find(lambda tag: tag.name in ("h1", "h2", "h3") and re.search(r"upcoming|predictions", tag.get_text(), re.I))
            print(f"heading found: {heading.get_text(strip=True) if heading else None!r}")
            table = heading.find_next("table") if heading else soup.find("table")
            if table is None:
                print("no table found on this URL")
                continue
            header_cells = [re.sub(r"\s+", " ", th.get_text(" ")).strip() for th in table.select("thead th")]
            print(f"header cells: {header_cells}")
            rows = table.select("tbody tr")
            print(f"row count: {len(rows)}")
            if rows:
                cells = rows[0].find_all("td", recursive=False)
                print(f"first row: {len(cells)} cells")
                for i, c in enumerate(cells):
                    print(f"  cell[{i}]: {c.get_text(' ', strip=True)[:150]!r}")
            print(f"THIS URL LOOKS VALID: {url}")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")


def probe_understat():
    hr("Understat: EPL league page - locate embedded JSON blob(s)")
    # first pass (no season suffix) returned an 18KB page with none of the
    # expected blobs - trying season-suffixed URLs and dumping enough raw
    # HTML to see what the page actually is (redirect page? paywall?
    # different template entirely?) if all of them still come up empty
    candidates = [
        "https://understat.com/league/EPL/2026",
        "https://understat.com/league/EPL/2025",
        "https://understat.com/league/EPL",
    ]
    for url in candidates:
        print(f"\n--- trying {url} ---")
        r = get(url)
        text = r.text
        print(f"final URL after redirects: {r.url}")
        found_any = False
        for varname in ("datesData", "teamsData", "playersData", "leagueData"):
            m = re.search(rf"var {varname}\s*=\s*JSON\.parse\('(.+?)'\)", text)
            if m:
                found_any = True
                raw = m.group(1)
                print(f"  {varname}: found, raw encoded length: {len(raw)} chars")
                try:
                    decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
                    data = json.loads(decoded)
                    if isinstance(data, dict):
                        keys = list(data.keys())[:5]
                        print(f"    decoded OK - dict with {len(data)} keys, sample: {keys}")
                        first_key = keys[0] if keys else None
                        if first_key:
                            print(f"    data[{first_key!r}] = {json.dumps(data[first_key], indent=2)[:1200]}")
                    elif isinstance(data, list):
                        print(f"    decoded OK - list with {len(data)} items")
                        if data:
                            print(f"    data[0] = {json.dumps(data[0], indent=2)[:1200]}")
                except Exception as e:
                    print(f"    decode FAILED: {type(e).__name__}: {e}")
                    print(f"    first 500 raw chars: {raw[:500]}")
        if not found_any:
            print("  none of the expected JSON.parse blobs found on this URL")
            # dump title + any <script> tag var names, to see what's really here
            title_m = re.search(r"<title>(.*?)</title>", text)
            print(f"  <title>: {title_m.group(1) if title_m else '(none)'}")
            script_vars = sorted(set(re.findall(r"var (\w+)\s*=", text)))
            print(f"  top-level JS var names found anywhere on page: {script_vars}")
            print(f"  first 800 chars of body:\n{text[:800]}")


def probe_football_data_org():
    hr("football-data.org: PL competition matches (requires X-Auth-Token)")
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    print(f"FOOTBALL_DATA_TOKEN set: {bool(token)}")
    if not token:
        print(
            "NO TOKEN AVAILABLE - this is a real, external blocker, not a bug in "
            "this probe. football-data.org's free tier requires registering at "
            "https://www.football-data.org/client/register and adding the token "
            "as a repo secret (FOOTBALL_DATA_TOKEN) consumed by the daily-report "
            "workflow. Skipping the live call."
        )
        return
    headers = {**BROWSER_HEADERS, "X-Auth-Token": token}
    r = get("https://api.football-data.org/v4/competitions/PL/matches?status=SCHEDULED", headers=headers)
    try:
        data = r.json()
        matches = data.get("matches", [])
        print(f"matches returned: {len(matches)}")
        if matches:
            print(json.dumps(matches[0], indent=2, default=str)[:2000])
    except Exception as e:
        print(f"failed to parse JSON: {e}")
        print(r.text[:1000])


def probe_clubelo():
    hr("ClubElo: current ratings CSV (no auth)")
    from datetime import date

    r = get(f"http://api.clubelo.com/{date.today().isoformat()}")
    print(f"content-type: {r.headers.get('content-type')}")
    lines = r.text.strip().split("\n")
    print(f"line count: {len(lines)}")
    print("header:", lines[0] if lines else "(empty)")
    epl_lines = [ln for ln in lines[1:] if ",ENG,1," in ln or ln.split(",")[:1] and "England" in ln]
    print(f"first 10 lines total (unfiltered, to see real column layout):")
    for ln in lines[:11]:
        print(f"  {ln}")


KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"


def probe_kalshi_epl():
    hr("Kalshi: search for EPL/soccer series (ticker unknown - try candidates + category listing)")
    # first pass found KXPREMIERLEAGUE (season-long title-winner futures,
    # confirmed real) but no per-game series among these specific guesses -
    # widening the guess list for a per-game/match-winner market
    candidate_tickers = [
        "KXEPLGAME", "KXEPL", "KXSOCCER", "KXPREMIERLEAGUE",
        "KXEPLWIN", "KXENGPREM", "KXPREM", "KXEPLMATCH", "KXSOCCERGAME",
        "KXUEFAGAME",  # showed up in the broad series list last run - check its shape
    ]
    for ticker in candidate_tickers:
        print(f"\n--- trying series_ticker={ticker} ---")
        r = get(f"{KALSHI_BASE}/markets?series_ticker={ticker}&status=open&limit=5")
        try:
            data = r.json()
            markets = data.get("markets", [])
            print(f"markets returned: {len(markets)}")
            if markets:
                print(json.dumps(markets[0], indent=2, default=str)[:1500])
        except Exception as e:
            print(f"parse failed: {e}; body: {r.text[:300]}")

    # first pass's regex matched against the FULL json.dumps() of each
    # series object, which is why it false-positived on 1510/3035 series
    # (e.g. matched "football" inside unrelated title text). This pass
    # only checks the 'title' field itself, and only for tighter phrases.
    hr("Kalshi: list all series - title-only match this time (first pass's full-object regex was too broad)")
    r = get(f"{KALSHI_BASE}/series?category=Sports&limit=200")
    try:
        data = r.json()
        series_list = data.get("series", [])
        print(f"series returned: {len(series_list)}")
        cursor = data.get("cursor")
        print(f"cursor present (more pages exist): {bool(cursor)}")
        title_matches = [
            s for s in series_list
            if re.search(r"premier league|\bepl\b|english.*soccer|english.*football", s.get("title", ""), re.I)
        ]
        print(f"title-matched series: {len(title_matches)}")
        for s in title_matches[:20]:
            print(f"  ticker={s.get('ticker')!r} title={s.get('title')!r}")
        # also print every ticker that starts with KX and contains "GAME",
        # to eyeball any per-match series regardless of naming
        game_series = [s for s in series_list if "GAME" in s.get("ticker", "")]
        print(f"\nall *GAME* tickers on this page ({len(game_series)}), for manual eyeballing:")
        for s in game_series[:40]:
            print(f"  ticker={s.get('ticker')!r} title={s.get('title')!r}")
    except Exception as e:
        print(f"parse failed: {e}; body: {r.text[:500]}")


def probe_action_network():
    hr("Action Network: EPL odds page - locate widget/embedded JSON")
    # first pass got status=202 bytes=0 with default headers - likely
    # bot-detection or an async placeholder response. Trying an Accept
    # header and printing response headers this time to see what's
    # actually being returned before giving up on this source.
    headers = {**BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    r = get("https://www.actionnetwork.com/soccer/odds", headers=headers)
    print(f"response headers: {dict(r.headers)}")
    text = r.text
    if not text:
        print("still empty body - trying Action Network's public JSON API directly instead of the HTML page")
        r2 = get("https://api.actionnetwork.com/web/v2/scoreboard/soccer/8", headers=headers)
        print(f"api attempt body (first 1500 chars): {r2.text[:1500]}")
        return
    custom_tags = sorted(set(re.findall(r"<([a-z]+-[a-z-]+)[ >]", text)))
    print(f"custom element tag names found: {custom_tags[:20]}")
    for kw in ("__NEXT_DATA__", "window.__INITIAL_STATE__", "matchups", "odds"):
        c = text.count(kw)
        if c:
            idx = text.find(kw)
            print(f"\nkeyword {kw!r} found {c}x, first context:")
            print(text[max(0, idx - 100): idx + 600])
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', text, re.S)
    if m:
        print(f"\n__NEXT_DATA__ blob length: {len(m.group(1))} chars")
        try:
            data = json.loads(m.group(1))
            print(json.dumps(data, indent=2, default=str)[:2000])
        except Exception as e:
            print(f"json parse failed: {e}")


def probe_reddit_soccer_rss():
    hr("Reddit RSS: r/soccer (same pattern as sports/mlb/fetch/reddit.py's r/sportsbook)")
    r = get("https://www.reddit.com/r/soccer/new.rss")
    print(f"content-type: {r.headers.get('content-type')}")
    if r.status_code == 200:
        titles = re.findall(r"<title>(.*?)</title>", r.text)
        print(f"entry count: {len(titles)}")
        for t in titles[:20]:
            print(f"  {t}")
    else:
        print(r.text[:500])


def main():
    for fn in (
        probe_dratings_epl,
        probe_understat,
        probe_football_data_org,
        probe_clubelo,
        probe_kalshi_epl,
        probe_action_network,
        probe_reddit_soccer_rss,
    ):
        try:
            fn()
        except Exception as e:
            hr(f"{fn.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
