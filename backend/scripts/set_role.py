"""Set an existing user's role (admin | accountant).

Usage (from backend/):
    .venv/bin/python -m scripts.set_role --email richard@credarion.com --role admin
"""
from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Set a user's account-level role.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=["admin", "accountant"])
    args = parser.parse_args()

    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"ERROR: no user with email {email}", file=sys.stderr)
            return 1
        user.role = args.role
        db.commit()
        print(f"Set {email} role to '{args.role}'")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
