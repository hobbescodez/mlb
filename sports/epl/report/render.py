"""Renders EPL report data into static HTML via Jinja2 - same pattern as
sports/mlb/report/render.py, different TEMPLATE_DIR/template name."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent
CORE_SITE_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "core" / "site_template"


def _env():
    return Environment(
        loader=FileSystemLoader([str(TEMPLATE_DIR), str(CORE_SITE_TEMPLATE_DIR)]),
        autoescape=select_autoescape(["html"]),
    )


def render_report(report_data, generated_at, inline_font_css=""):
    """Full standalone page for docs/ (GitHub Pages). show_nav=True here
    (and only here) - see sports/mlb/report/render.py's render_report
    docstring for why the Artifact fragment doesn't get the site nav."""
    fragment = _env().get_template("epl_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css, show_nav=True,
    )
    return f'<!doctype html>\n<html lang="en">\n{fragment}\n</html>\n'


def render_artifact_fragment(report_data, generated_at, inline_font_css=""):
    """Content-only fragment for publishing as a Claude Artifact."""
    return _env().get_template("epl_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css, show_nav=False,
    )
