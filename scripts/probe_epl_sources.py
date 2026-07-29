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

football-data.org's token (FOOTBALL_DATA_TOKEN) was added as a repo
secret 2026-07-29 - probe_football_data_org() now expects a real
authenticated response, not the "no token" branch.

Action Network was dropped 2026-07-29 after 3 probe runs showed it fails
~2/3 of the time (empty 202 responses, not a fixable header/retry issue) -
no probe function for it remains here.
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
    # Passes 1-2 confirmed the old assumption (server-rendered
    # `var xData = JSON.parse('...')` blobs) is dead - the page now only
    # has top-level vars BASE_URL/THEME/flagFontsLoading/j, meaning data
    # loads client-side via an API call this probe hasn't found yet. This
    # pass checks two real possibilities instead of guessing again:
    #  1. Is this now a Next.js app (like Action Network turned out to be)
    #     with a __NEXT_DATA__ blob carrying the table server-side?
    #  2. If not, what does the actual JS bundle reference as its data
    #     endpoint - grep every <script src> bundle for fetch(...)/api
    #     URL patterns instead of guessing endpoint names blind.
    url = "https://understat.com/league/EPL/2026"
    r = get(url)
    text = r.text
    print(f"final URL after redirects: {r.url}")

    next_data_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', text, re.S)
    if next_data_m:
        print("\n__NEXT_DATA__ FOUND - this is a Next.js page after all")
        try:
            data = json.loads(next_data_m.group(1))
            page_props = data.get("props", {}).get("pageProps", {})
            print(f"pageProps top-level keys: {list(page_props.keys())}")
            print(json.dumps(page_props, indent=2, default=str)[:2500])
        except Exception as e:
            print(f"json parse failed: {e}")
        return

    print("\nno __NEXT_DATA__ - not Next.js. Searching <script src> bundles for API endpoint strings.")
    script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', text)
    print(f"script src attributes found: {script_srcs}")
    # BUG in the previous pass: "//host/path" (protocol-relative, e.g.
    # Google's CDN) also starts with "/", so the old `elif src.startswith("/")`
    # branch wrongly treated it as same-origin and mangled it into
    # "https://understat.com//host/path" (confirmed 404 last run). Real
    # first-party bundles here are plain relative paths like
    # "js/league.min.js?t=..." with no leading slash at all, which the old
    # code never matched and so never fetched. Fixed: three real cases -
    # absolute (http/https), protocol-relative (//host/...), and
    # page-relative (everything else, resolved against the page URL).
    resolved = []
    for src in script_srcs:
        if src.startswith("http://") or src.startswith("https://"):
            resolved.append(src)
        elif src.startswith("//"):
            resolved.append("https:" + src)
        else:
            resolved.append("https://understat.com/" + src.lstrip("/"))
    own_bundles = [u for u in resolved if "understat.com" in u]
    print(f"first-party bundle URLs to inspect: {own_bundles}")

    # inspect league.min.js and main.min.js first (most likely to hold
    # this page's own data-fetching logic, by name), then everything else
    own_bundles.sort(key=lambda u: (0 if ("league" in u or "main" in u) else 1, u))

    endpoint_pattern = re.compile(r'["\'](/(?:main|api)/[a-zA-Z0-9_/]+)["\']')
    fetch_pattern = re.compile(r'(?:fetch|axios\.(?:get|post))\(\s*["\']([^"\']+)["\']')
    for bundle_url in own_bundles:
        try:
            br = get(bundle_url)
            btext = br.text
            endpoints = sorted(set(endpoint_pattern.findall(btext)) | set(fetch_pattern.findall(btext)))
            print(f"\n--- {bundle_url} ({len(btext)} chars) - candidate endpoint strings: {endpoints[:20]}")
        except Exception as e:
            print(f"  FAILED fetching {bundle_url}: {e}")


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
    # Action Network dropped (2026-07-29): confirmed unreliable across 3
    # probe runs (1 real 917KB response, 2 empty 202 placeholders) - not a
    # fixable header/retry issue, and not needed (ClubElo + Kalshi's
    # title-winner market already give some market signal for EPL).
    for fn in (
        probe_dratings_epl,
        probe_understat,
        probe_football_data_org,
        probe_clubelo,
        probe_kalshi_epl,
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
