"""Renders report data into the static HTML page via Jinja2."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parent
CORE_SITE_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "core" / "site_template"


def _env():
    # search this sport's own template dir first, then the shared
    # core/site_template/ dir (base.css, macros.html) - lets
    # artifact_template.html {% include %} the shared CSS/macros without
    # duplicating them per sport.
    return Environment(
        loader=FileSystemLoader([str(TEMPLATE_DIR), str(CORE_SITE_TEMPLATE_DIR)]),
        autoescape=select_autoescape(["html"]),
    )


def render_report(report_data, generated_at, inline_font_css=""):
    """Full standalone page for docs/ (GitHub Pages). Wraps the same content
    used for the Claude Artifact fragment in a <!doctype html><html>...
    shell - the fragment's own leading <title>/<style> tags land in an
    HTML5 "implied head" ahead of the body content, same as how the
    Artifact tool itself wraps this file when publishing it directly.
    show_nav=True here (and only here) - the cross-sport header links to
    sibling pages (mlb.html/epl.html/index.html) that only make sense on
    the real GitHub Pages site, not inside the embedded Artifact."""
    fragment = _env().get_template("artifact_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css, show_nav=True,
    )
    return f'<!doctype html>\n<html lang="en">\n{fragment}\n</html>\n'


def render_artifact_fragment(report_data, generated_at, inline_font_css=""):
    """Content-only fragment (no <html>/<head>/<body>) for publishing as a
    Claude Artifact - see sports/mlb/report/artifact_template.html.
    show_nav=False - see render_report's docstring."""
    return _env().get_template("artifact_template.html").render(
        r=report_data, generated_at=generated_at, inline_font_css=inline_font_css, show_nav=False,
    )
