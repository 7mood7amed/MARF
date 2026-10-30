#!/usr/bin/env python3
"""Create a MARF user. Run from the project folder:

    python scripts/create_user.py accountant --role admin

The password is typed at a hidden prompt, never passed on the command line.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marf import auth, config  # noqa: E402
from marf.storage import Storage  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a MARF user.")
    parser.add_argument("username")
    parser.add_argument("--role", choices=auth.ROLES, default="user", help="admin can see the audit log and purge files")
    args = parser.parse_args()

    password = getpass.getpass(f"Password (at least {config.MIN_PASSWORD_LEN} characters): ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")

    config.ensure_dirs()
    storage = Storage(config.DB_PATH, config.UPLOAD_DIR)
    try:
        auth.create_user(storage, args.username, password, args.role)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"Created {args.role} '{args.username}' in {config.DB_PATH}")


if __name__ == "__main__":
    main()
