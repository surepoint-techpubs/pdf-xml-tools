########################################################################
### AUTH -- PER-USER ACCOUNTS, BCRYPT, DB-BACKED LOCKOUT
########################################################################
from datetime import datetime, timedelta

import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, session

from app import limiter
from app.extensions import get_db_connection, delete_upload, logger, FAILED_ATTEMPT_LIMIT, LOCKOUT_MINUTES

bp = Blueprint("auth", __name__)

### used to normalize response time when the username doesn't exist at
### all, so a login attempt can't distinguish "no such user" from
### "wrong password" by timing -- checkpw() alone is only constant-time
### for a real comparison, not for the "skip it entirely" case.
_DUMMY_HASH = bcrypt.hashpw(b"not a real password", bcrypt.gensalt()).decode()


### only ever redirect to a path within this app -- an unchecked ?next=
### is an open redirect (CWE-601), e.g. /login?next=https://evil.example
def _safe_next_path(next_path):
    if next_path and next_path.startswith("/") and not next_path.startswith(("//", "/\\")):
        return next_path
    return None


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if "user_id" in session:
        return redirect(url_for("extract.index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db_connection() as conn:
            user = conn.execute(
                "SELECT id, username, password_hash, is_admin, failed_attempts, locked_until FROM users WHERE username = ?",
                (username,),
            ).fetchone()

            if user is None:
                bcrypt.checkpw(password.encode(), _DUMMY_HASH.encode())
                error = "Invalid username or password."
            elif user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > datetime.now():
                error = f"Account locked. Try again after {user['locked_until']}."
            elif bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
                conn.execute(
                    "UPDATE users SET failed_attempts = 0, locked_until = NULL, is_logged_in = 1 WHERE id = ?",
                    (user["id"],),
                )
                conn.commit()
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["is_admin"] = bool(user["is_admin"])
                logger.info("login success: %s", user["username"])
                next_path = _safe_next_path(request.args.get("next"))
                return redirect(next_path or url_for("extract.index"))
            else:
                attempts = user["failed_attempts"] + 1
                locked_until = None
                if attempts >= FAILED_ATTEMPT_LIMIT:
                    locked_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                    logger.warning("account locked after %d failed attempts: %s", attempts, username)
                conn.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, locked_until, user["id"]),
                )
                conn.commit()
                error = "Invalid username or password."

    return render_template("login.html", error=error)


@bp.route("/logout", methods=["POST"])
def logout():
    if "user_id" in session:
        with get_db_connection() as conn:
            conn.execute("UPDATE users SET is_logged_in = 0 WHERE id = ?", (session["user_id"],))
            conn.commit()
    delete_upload(session.get("pdf_token"))
    session.clear()
    return redirect(url_for("auth.login"))
