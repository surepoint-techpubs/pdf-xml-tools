########################################################################
### ADMIN -- restricted settings, admin-only
########################################################################
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, session, abort

from app.extensions import get_db_connection, admin_required, logger

bp = Blueprint("admin", __name__)


def _load_users():
    with get_db_connection() as conn:
        return conn.execute("SELECT id, username, is_admin, is_logged_in FROM users ORDER BY username").fetchall()


@bp.route("/admin")
@admin_required
def settings():
    return render_template("admin.html", users=_load_users(), error=None)


@bp.route("/admin/users/new", methods=["GET", "POST"])
@admin_required
def new_user():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        is_admin = request.form.get("is_admin") == "on"

        if not username:
            error = "Username is required."
        elif password != confirm:
            error = "Passwords didn't match."
        elif len(password) < 12:
            error = "Password needs to be at least 12 characters."
        else:
            with get_db_connection() as conn:
                existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
                if existing:
                    error = "That username is already taken."
                else:
                    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    conn.execute(
                        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                        (username, password_hash, int(is_admin)),
                    )
                    conn.commit()
                    logger.info("user created via admin page: %s", username)
                    return redirect(url_for("admin.settings"))

    return render_template("admin_new_user.html", error=error)


@bp.route("/admin/users/<int:user_id>/logout", methods=["POST"])
@admin_required
def force_logout(user_id):
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET is_logged_in = 0 WHERE id = ?", (user_id,))
        conn.commit()
    logger.info("user forced logged out via admin page: id=%s", user_id)
    return redirect(url_for("admin.settings"))


@bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def set_password(user_id):
    password = request.form.get("password", "")
    if len(password) < 12:
        return render_template("admin.html", users=_load_users(), error="Password needs to be at least 12 characters.")

    with get_db_connection() as conn:
        target = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            abort(404)
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        conn.commit()
    logger.info("password changed via admin page: id=%s", user_id)
    return redirect(url_for("admin.settings"))


@bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    if user_id == session.get("user_id"):
        abort(400, description="You can't delete your own account.")

    with get_db_connection() as conn:
        target = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            abort(404)
        if target["is_admin"]:
            admin_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_admin = 1").fetchone()["c"]
            if admin_count <= 1:
                abort(400, description="Can't delete the only admin account.")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    logger.info("user deleted via admin page: id=%s", user_id)
    return redirect(url_for("admin.settings"))
