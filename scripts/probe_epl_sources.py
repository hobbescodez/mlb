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
    url = "https://understat.com/league/EPL"
    r = get(url)
    text = r.text
    # understat embeds JSON.parse('...') blobs for datesData / teamsData / playersData
    for varname in ("datesData", "teamsData", "playersData", "leagueData"):
        m = re.search(rf"var {varname}\s*=\s*JSON\.parse\('(.+?)'\)", text)
        print(f"\n{varname}: {'found' if m else 'NOT FOUND'}")
        if m:
            raw = m.group(1)
            print(f"  raw encoded length: {len(raw)} chars")
            # understat encodes as escaped JSON (\x hex escapes for unicode)
            try:
                decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin1").decode("utf-8")
                data = json.loads(decoded)
                if isinstance(data, dict):
                    keys = list(data.keys())[:5]
                    print(f"  decoded OK - dict with {len(data)} keys, sample: {keys}")
                    first_key = keys[0] if keys else None
                    if first_key:
                        print(f"  data[{first_key!r}] = {json.dumps(data[first_key], indent=2)[:1500]}")
                elif isinstance(data, list):
                    print(f"  decoded OK - list with {len(data)} items")
                    if data:
                        print(f"  data[0] = {json.dumps(data[0], indent=2)[:1500]}")
            except Exception as e:
                print(f"  decode FAILED: {type(e).__name__}: {e}")
                print(f"  first 500 raw chars: {raw[:500]}")


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
    candidate_tickers = ["KXEPLGAME", "KXEPL", "KXSOCCER", "KXPREMIERLEAGUE"]
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

    hr("Kalshi: list all series (to find real EPL ticker name if candidates above missed)")
    r = get(f"{KALSHI_BASE}/series?category=Sports&limit=200")
    try:
        data = r.json()
        series_list = data.get("series", [])
        print(f"series returned: {len(series_list)}")
        soccer_like = [s for s in series_list if re.search(r"soccer|premier|epl|football", json.dumps(s), re.I)]
        print(f"soccer/EPL-looking series: {len(soccer_like)}")
        for s in soccer_like[:15]:
            print(f"  ticker={s.get('ticker')!r} title={s.get('title')!r} category={s.get('category')!r}")
    except Exception as e:
        print(f"parse failed: {e}; body: {r.text[:500]}")


def probe_action_network():
    hr("Action Network: EPL odds page - locate widget/embedded JSON")
    r = get("https://www.actionnetwork.com/soccer/odds")
    text = r.text
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
