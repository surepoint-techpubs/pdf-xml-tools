# PDF-XML -- Setup & Configuration

Converts unstructured PDFs into DocBook XML fragments (paragraphs,
lists, tables) plus cropped/watermarked images, for hand-off into
Paligo. Flask app, SQLite-backed accounts, PyMuPDF for all PDF
handling.

## Requirements

- Python 3.12
- XML validation is handled by `lxml` from `requirements.txt`.

Everything else is in `requirements.txt` (and `requirements-dev.txt`
for Playwright-based UI tests, optional).

## First-time setup (any environment)

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

sqlite3 pdfxml.db < deploy/schema.sql   # fresh install only -- this DROPs and
                                         # recreates the users table

.venv/bin/python3 deploy/create_user.py <username> --admin
```

`deploy/create_user.py` prompts for a password (never on the command
line). There's no public signup route -- accounts are always
provisioned this way or from the in-app Admin settings page.

## Environment variables

All optional; sane defaults if unset.

| Variable | Default | Purpose |
|---|---|---|
| `PDFXML_DB_PATH` | `<project>/pdfxml.db` | SQLite file location |
| `PDFXML_UPLOAD_DIR` | `<project>/uploads` | per-session upload/result scratch space |
| `PDFXML_BEHIND_PROXY` | unset | set only in `deploy/pdfxml.service` -- see Production deployment |

## Secrets

`.secret_key` (session signing / CSRF) is generated on first run and
`chmod 600`'d automatically -- nothing to configure. Deleting it
forces a new key, which invalidates every existing session.

## User accounts & administration

- Bootstrap the first admin via `deploy/create_user.py --admin`; every
  account after that can be added from the Admin settings page (gear
  icon, admin-only) once you're logged in as one.
- Passwords are bcrypt-hashed, minimum 12 characters, enforced in both
  the CLI script and the admin page. The admin page can also change
  an existing user's password.
- 5 failed logins locks an account for 15 minutes; a successful login
  clears the counter.
- `is_admin` is a single flag, full trust -- admins can rewrite the
  Process/Troubleshooting pages with raw HTML (rendered unescaped for
  every logged-in viewer, by design -- see the comment in
  `app/blueprints/pages.py`) and manage/delete other accounts. Only
  grant it to people you'd trust with that.

## Local development

```
.venv/bin/python3 run.py
```

Runs Flask's own dev server (`debug=False` always, regardless of
environment). `TEMPLATES_AUTO_RELOAD` is on, so template edits show up
without a restart; Python changes still need one. `PDFXML_BEHIND_PROXY`
stays unset locally, so `http://localhost` works without TLS.

Note `run.py` binds port 89, which is privileged -- expect to need
elevated rights to bind it locally too, same as production.

## Production deployment (gunicorn + nginx + systemd)

Templates live in `deploy/`, each with its own install instructions in
a header comment:

- **`deploy/pdfxml.service`** -- systemd unit. gunicorn bound to
  `127.0.0.1:8089` only (never reachable directly), single worker
  (more would silently fragment the in-memory login rate limit across
  workers), sets `PDFXML_BEHIND_PROXY=1`.
- **`deploy/pdfxml.nginx.conf`** -- TLS-terminating reverse proxy in
  front of gunicorn, HTTP->HTTPS redirect.

Rough order of operations for a new host:

1. Copy the app over -- **not** `.venv/`, `pdfxml.db`, `.secret_key`,
   or `uploads/`. Those are either architecture-specific (`.venv`) or
   this dev box's own state/test data.
2. Rebuild the venv on the target host (`python3 -m venv .venv && ...`)
   and install `libxml2-utils`.
3. Run First-time setup above to get a clean DB and a real first admin.
4. Edit the placeholder values in both `deploy/` files (user, paths,
   `server_name`, cert paths) for the actual host.
5. Get a TLS cert for the host. A private LAN address isn't publicly
   resolvable, so Let's Encrypt won't issue for it -- self-signed or an
   internal CA instead.
6. Install and enable both units (see each file's header comment).
7. Firewall the host to just 80/443 plus however you administer it --
   it'll be reachable from the whole building LAN, not just this app's
   users.

## Maintenance

- Uploaded PDFs and their extraction results auto-sweep after 24h
  (`UPLOAD_MAX_AGE_SECONDS` in `app/extensions.py`) -- nothing manual.
- Worth backing up: `pdfxml.db` (accounts) and
  `process_tabs.json`/`troubleshooting_tabs.json` (Process/
  Troubleshooting content). `uploads/` is disposable; `.secret_key`
  regenerates itself (at the cost of logging everyone out).
- Max upload size is 50MB (`MAX_UPLOAD_BYTES` in `app/extensions.py`),
  mirrored in `deploy/pdfxml.nginx.conf`'s `client_max_body_size` --
  keep both in sync if you change it.
