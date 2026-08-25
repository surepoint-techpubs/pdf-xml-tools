########################################################################
### PAGES -- PROCESS INSTRUCTIONS + TROUBLESHOOTING, JSON-BACKED TABS
###
### Both pages share one shape: a JSON file holding a list of
### {label, content} tabs. content is trusted rich HTML straight from
### the edit page's contenteditable editor, rendered with |safe --
### that's why editing is admin-only while viewing is any logged-in
### user.
########################################################################
import json
import os

import bleach
from flask import Blueprint, render_template, request, url_for

from app.extensions import login_required, admin_required, PROJECT_DIR

bp = Blueprint("pages", __name__)

_ALLOWED_HTML_TAGS = {
    "p", "br", "strong", "em", "ul", "ol", "li", "h2", "h3", "hr", "code",
}


def _sanitize_tabs(tabs):
    for tab in tabs:
        tab["content"] = bleach.clean(
            tab["content"],
            tags=_ALLOWED_HTML_TAGS,
            attributes={},
            strip=True,
            strip_comments=True,
        )
    return tabs

PAGES = {
    "process": {
        "title": "Process",
        "path": os.path.join(PROJECT_DIR, "process_tabs.json"),
        "default_tabs": [{"label": "Instructions", "content": "<p></p>"}],
    },
    "troubleshooting": {
        "title": "Troubleshooting",
        "path": os.path.join(PROJECT_DIR, "troubleshooting_tabs.json"),
        "default_tabs": [{"label": "Troubleshooting", "content": "<p></p>"}],
    },
}


def _read_tabs(page_key):
    page = PAGES[page_key]
    if not os.path.exists(page["path"]):
        return page["default_tabs"]
    with open(page["path"], encoding="utf-8") as f:
        tabs = json.load(f)
    return _sanitize_tabs(tabs) if tabs else page["default_tabs"]


def _save_tabs(page_key, tabs):
    _sanitize_tabs(tabs)
    with open(PAGES[page_key]["path"], "w", encoding="utf-8") as f:
        json.dump(tabs, f, ensure_ascii=False, indent=2)


def _parse_submitted_tabs(page_key):
    try:
        tabs = json.loads(request.form.get("tabs", "[]"))
        tabs = [
            {"label": str(tab.get("label", "")).strip() or "Untitled", "content": str(tab.get("content", ""))}
            for tab in tabs
            if isinstance(tab, dict)
        ]
    except (TypeError, ValueError, json.JSONDecodeError):
        tabs = []
    return tabs or PAGES[page_key]["default_tabs"]


def _view(page_key):
    page = PAGES[page_key]
    breadcrumbs = [("Home", url_for("extract.index")), (page["title"], "")]
    return render_template(
        "tabs_view.html",
        page_key=page_key,
        title=page["title"],
        tabs=_read_tabs(page_key),
        breadcrumbs=breadcrumbs,
    )


def _edit(page_key):
    page = PAGES[page_key]
    saved = False
    if request.method == "POST":
        tabs = _parse_submitted_tabs(page_key)
        _save_tabs(page_key, tabs)
        saved = True
    else:
        tabs = _read_tabs(page_key)
    return render_template("tabs_edit.html", page_key=page_key, title=page["title"], tabs=tabs, saved=saved)


@bp.route("/process")
@login_required
def process():
    return _view("process")


@bp.route("/process/edit", methods=["GET", "POST"])
@admin_required
def process_edit():
    return _edit("process")


@bp.route("/troubleshooting")
@login_required
def troubleshooting():
    return _view("troubleshooting")


@bp.route("/troubleshooting/edit", methods=["GET", "POST"])
@admin_required
def troubleshooting_edit():
    return _edit("troubleshooting")
