########################################################################
### APP FACTORY
########################################################################
import os
import sqlite3

from flask import Flask, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import FLASK_SECRET_KEY, MAX_UPLOAD_BYTES, logger, sweep_old_uploads

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    csrf.init_app(app)
    limiter.init_app(app)

    ### ProxyFix trusts whatever X-Forwarded-For a client sends, so this
    ### must stay off unless a reverse proxy (deploy/pdfxml.nginx.conf) is
    ### the only thing that can reach this process directly -- otherwise
    ### anyone could spoof their IP and dodge the login rate limit.
    ### PDFXML_BEHIND_PROXY is set in deploy/pdfxml.service, not locally.
    ### Same flag also means TLS is actually in front, so the session
    ### cookie can require it -- forcing this on without TLS would break
    ### login entirely (the cookie would never leave the browser).
    if os.environ.get("PDFXML_BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    sweep_old_uploads()

    ### cache-busting -- appends the static file's own mtime as a query
    ### string, so editing it changes the URL and forces a fresh fetch
    ### regardless of what the browser cached under the old URL
    @app.template_global()
    def static_url(filename):
        path = os.path.join(app.static_folder, filename)
        try:
            version = int(os.path.getmtime(path))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.extract import bp as extract_bp
    from app.blueprints.pages import bp as pages_bp
    from app.blueprints.imagecrop import bp as imagecrop_bp
    from app.blueprints.admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(extract_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(imagecrop_bp)

    ########################################################################
    ### ERROR HANDLING -- NOTHING SHOULD EVER SHOW A RAW TRACEBACK.
    def _err_page_from():
        return request.referrer or "/"

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return render_template(
            "errorpage.html",
            err_message="Your session expired -- please try again.",
            err_page_from=_err_page_from(),
        ), 400

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return render_template(
            "errorpage.html", err_message=e.description, err_page_from=_err_page_from()
        ), e.code

    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity_error(e):
        logger.warning("IntegrityError on %s: %s", request.path, e)
        return render_template(
            "errorpage.html",
            err_message="That conflicts with existing data.",
            err_page_from=_err_page_from(),
        ), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        logger.exception("Unhandled exception on %s", request.path)
        return render_template(
            "errorpage.html",
            err_message="Something went wrong. Please try again.",
            err_page_from=_err_page_from(),
        ), 500

    return app
