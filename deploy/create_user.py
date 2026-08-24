#!/usr/bin/env python3
### One-off: create or reset a user account. No public signup route --
### the user list is small and admin-provisioned.
###
### Usage: .venv/bin/python3 deploy/create_user.py <username> [--admin]
### Prompts for a password (not echoed, not passed on the command line).
### --admin grants (or keeps) admin rights; omitting it never demotes
### an existing admin -- it just leaves is_admin as it already was.
import getpass
import os
import sqlite3
import sys

import bcrypt

PROJECT_DIR = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.environ.get("PDFXML_DB_PATH", os.path.join(PROJECT_DIR, "pdfxml.db"))

if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--admin"):
    print("Usage: create_user.py <username> [--admin]")
    sys.exit(1)

username = sys.argv[1].strip()
is_admin = len(sys.argv) == 3
password = getpass.getpass("Password: ")
confirm = getpass.getpass("Confirm password: ")
if password != confirm:
    print("Passwords didn't match.")
    sys.exit(1)
if len(password) < 12:
    print("Password needs to be at least 12 characters.")
    sys.exit(1)

password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

conn = sqlite3.connect(DB_PATH)
conn.execute(
    """ INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)
        ON CONFLICT (username) DO UPDATE SET
            password_hash = excluded.password_hash, failed_attempts = 0, locked_until = NULL,
            is_admin = CASE WHEN excluded.is_admin = 1 THEN 1 ELSE users.is_admin END """,
    (username, password_hash, int(is_admin)),
)
conn.commit()
conn.close()
print(f"user '{username}' created/updated" + (" (admin)" if is_admin else ""))
