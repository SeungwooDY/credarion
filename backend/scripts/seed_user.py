"""Seed a paying account + login user, linked to a pilot organization.

Usage (from backend/):
    .venv/bin/python -m scripts.seed_user \
        --email richard@credarion.com \
        --password "change-me" \
        --name "Richard Zhu" \
        --account "Credarion Pilot" \
        --plan growth

If --org-id is given, that existing organization is attached to the account.
Otherwise the most recently created organization is linked (the pilot org),
or a new one is created with --org-name. Re-running with the same email
updates the existing user's password/name rather than erroring.
"""
from __future__ import annotations

import argparse
import sys

from app.db import SessionLocal
from app.models import Account, Organization, User
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a paying customer login.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default=None, help="User's full name")
    parser.add_argument("--account", default="Credarion Customer", help="Account/company name")
    parser.add_argument(
        "--plan", default="growth", choices=["starter", "growth", "enterprise"]
    )
    parser.add_argument("--superuser", action="store_true", help="Grant cross-org access")
    parser.add_argument(
        "--role",
        default="accountant",
        choices=["admin", "accountant"],
        help="Account-level role (admins acknowledge escalations and sign off periods)",
    )
    parser.add_argument("--org-id", default=None, help="Existing org UUID to attach")
    parser.add_argument(
        "--org-name",
        default=None,
        help="Create a new org with this name (if no org is found/given)",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is not None:
            account = user.account
            account.subscription_status = "active"
            account.plan = args.plan
            user.hashed_password = hash_password(args.password)
            user.full_name = args.name or user.full_name
            user.is_active = True
            user.is_superuser = args.superuser or user.is_superuser
            user.role = args.role
            print(f"Updated existing user {email} (account: {account.name})")
        else:
            account = Account(
                name=args.account, plan=args.plan, subscription_status="active"
            )
            db.add(account)
            db.flush()
            user = User(
                account_id=account.id,
                email=email,
                hashed_password=hash_password(args.password),
                full_name=args.name,
                is_active=True,
                is_superuser=args.superuser,
                role=args.role,
            )
            db.add(user)
            print(f"Created account '{account.name}' and user {email}")

        # Attach an organization to the account.
        org: Organization | None = None
        if args.org_id:
            org = db.get(Organization, args.org_id)
            if org is None:
                print(f"ERROR: no organization with id {args.org_id}", file=sys.stderr)
                return 1
        else:
            # Prefer an unowned org (e.g. the pilot org created before auth existed).
            org = (
                db.query(Organization)
                .filter(Organization.account_id.is_(None))
                .order_by(Organization.created_at.desc())
                .first()
            )
            if org is None and args.org_name:
                org = Organization(name=args.org_name)
                db.add(org)
                db.flush()

        if org is not None:
            org.account_id = account.id
            print(f"Linked organization '{org.name}' ({org.id}) to account")
        else:
            print(
                "No organization attached. Pass --org-id or --org-name, or create "
                "one via the API; it will be owned by this account when created."
            )

        db.commit()
        print("Done. You can now log in with the email + password above.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
