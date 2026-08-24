########################################################################
### EXTENSIONS -- SHARED HELPERS: DB, AUTH, TEMP UPLOAD FILES, LOGGING
########################################################################
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from functools import wraps
from threading import BoundedSemaphore

from flask import session, redirect, url_for, request, abort

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("PDFXML_DB_PATH", os.path.join(PROJECT_DIR, "pdfxml.db"))
UPLOAD_DIR = os.environ.get("PDFXML_UPLOAD_DIR", os.path.join(PROJECT_DIR, "uploads"))

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # generous for a scanned/watermarked doc, still bounded
UPLOAD_MAX_AGE_SECONDS = 24 * 60 * 60  # sweep anything older than this

FAILED_ATTEMPT_LIMIT = 5
LOCKOUT_MINUTES = 15
PDF_PROCESSING_SLOTS = BoundedSemaphore(value=3)

### secret key -- generated once, persisted to disk, same pattern as
### the sibling COBWEBS/IMPS apps
SECRET_KEY_PATH = os.path.join(PROJECT_DIR, ".secret_key")
if os.path.exists(SECRET_KEY_PATH):
    with open(SECRET_KEY_PATH, encoding="utf-8") as f:
        FLASK_SECRET_KEY = f.read().strip()
else:
    FLASK_SECRET_KEY = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(FLASK_SECRET_KEY)
    os.chmod(SECRET_KEY_PATH, 0o600)

### logging -- stderr, same shape as the sibling apps' logger
logger = logging.getLogger("pdfxml")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


### checked on every request, not just at login -- is_logged_in flips
### to false on self-logout or an admin's forced logout, and this is
### what makes that actually invalidate the session immediately rather
### than just labeling it stale in the admin table.
def _session_valid():
    if "user_id" not in session:
        return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT is_logged_in FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return row is not None and row["is_logged_in"]


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _session_valid():
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


### is_admin is cached in session at login (see auth.login), not looked
### up here per-request -- a promotion/demotion takes effect on that
### user's next login, same as any other session-cached field.
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _session_valid():
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        if not session.get("is_admin"):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def pdf_processing_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        with PDF_PROCESSING_SLOTS:
            return f(*args, **kwargs)
    return decorated_function


########################################################################
### PER-SESSION UPLOAD STORAGE -- random-token filenames, never a
### user-controllable path. One PDF per session at a time; a fresh
### upload replaces (and deletes) whatever was there before.
########################################################################
def save_upload(file_storage):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    token = secrets.token_hex(16)
    file_storage.save(os.path.join(UPLOAD_DIR, f"{token}.pdf"))
    return token


def upload_path(token):
    ### token always comes from our own secrets.token_hex() output,
    ### written into the signed session -- never taken from request
    ### data directly. Hex-checked anyway as cheap defense in depth.
    if not token or not all(c in "0123456789abcdef" for c in token):
        return None
    path = os.path.join(UPLOAD_DIR, f"{token}.pdf")
    return path if os.path.isfile(path) else None


def delete_upload(token):
    path = upload_path(token)
    if path:
        os.remove(path)
    delete_result(token)


def sweep_old_uploads():
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - UPLOAD_MAX_AGE_SECONDS
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)


########################################################################
### LAST EXTRACTION RESULT -- a full table's XML/HTML can easily exceed
### the ~4KB cookie the default Flask session is stored in, so this
### lives in the same per-session temp directory as the upload itself,
### keyed by the same token, not in session[] directly.
########################################################################
def save_result(token, result_dict):
    path = upload_path(token)
    if path is None:
        return
    with open(f"{path}.result.json", "w", encoding="utf-8") as f:
        json.dump(result_dict, f)


def load_result(token):
    path = upload_path(token)
    if path is None:
        return None
    result_path = f"{path}.result.json"
    if not os.path.isfile(result_path):
        return None
    with open(result_path, encoding="utf-8") as f:
        return json.load(f)


def delete_result(token):
    if not token or not all(c in "0123456789abcdef" for c in token):
        return
    result_path = os.path.join(UPLOAD_DIR, f"{token}.pdf.result.json")
    if os.path.isfile(result_path):
        os.remove(result_path)
