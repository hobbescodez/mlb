"""
Builds the cross-sport landing page at docs/index.html - three boxes
linking to each sport's own page (MLB, NFL, EPL). No fetching involved
(static except for the shared inline font cache), so this doesn't need
to run on the same schedule as any sport's daily report - re-run it
whenever the sport roster or box states change (e.g. once NFL ships,
flip its box from "Coming soon" to live).

MLB's own daily workflow used to write directly to docs/index.html
before this page existed - it now writes docs/mlb.html instead (see
main.py), freeing the root path for this landing page.

Usage: python build_landing_page.py
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sports.mlb.report import fonts  # sport-agnostic (Oswald/Inter) - reused as-is

TEMPLATE_DIR = Path(__file__).resolve().parent / "core" / "site_template"
OUTPUT_PATH = Path(__file__).resolve().parent / "docs" / "index.html"
FONT_CACHE_PATH = Path(__file__).resolve().parent / "sports" / "mlb" / "report" / "inline_fonts.cache.css"


def _inline_font_css():
    # reuses MLB's existing font cache file rather than fetching/caching
    # a third copy - same Oswald/Inter subset every page here embeds
    if FONT_CACHE_PATH.exists():
        return FONT_CACHE_PATH.read_text(encoding="utf-8")
    return fonts.build_inline_font_css()


def build():
    env = Environment(
        loader=FileSystemLoader([str(TEMPLATE_DIR)]),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("landing_template.html").render(inline_font_css=_inline_font_css())
    full_page = f'<!doctype html>\n<html lang="en">\n{html}\n</html>\n'

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(full_page, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
