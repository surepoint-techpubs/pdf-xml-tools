-- PDF-XML table schema
--
-- Table creation only. For FRESH installs (drops and recreates every
-- table) -- do not run against a database with existing accounts.
--
-- Manual usage:
--   sqlite3 pdfxml.db < deploy/schema.sql

DROP TABLE IF EXISTS users;

-- failed_attempts/locked_until drive login throttling directly --
-- no separate attempts-log table, this app has no other use for one.
-- 5 consecutive failures locks the account for 15 minutes; a
-- successful login resets both.
--
-- is_admin: no dedicated roles table -- one flag is all this app
-- needs. Admins are the only ones who can edit the process/
-- troubleshooting pages and use the admin settings page; account
-- provisioning is otherwise CLI-only (deploy/create_user.py --admin).
--
-- is_logged_in: set true at successful login, false at logout (self
-- or admin-forced). login_required/admin_required check this on every
-- request, so a forced logout actually invalidates the session
-- immediately rather than just labeling it in the admin table.
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, -- bcrypt
  is_admin INTEGER NOT NULL DEFAULT 0,
  is_logged_in INTEGER NOT NULL DEFAULT 0,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT, -- ISO datetime, NULL if not locked
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
