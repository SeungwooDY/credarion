"""Accounting-period helpers.

The canonical scoping key across Credarion is the period string "YYYY-MM". This
module owns the small amount of logic around that string: validation, the
human-readable label, and a get-or-create for the `accounting_periods` registry
so every ingest path (GRN, statement, invoice) and the explicit "Create period"
action converge on the same rows.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AccountingPeriod

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_period(period: str) -> str:
    """Return the period unchanged if it is a valid "YYYY-MM", else raise.

    Raises ValueError so callers can surface a 400 to the client.
    """
    if not isinstance(period, str) or not _PERIOD_RE.match(period.strip()):
        raise ValueError(f"Invalid period '{period}'. Expected format 'YYYY-MM', e.g. '2026-07'.")
    return period.strip()


def period_label(period: str) -> str:
    """"2026-07" -> "July 2026" (English month name, locale-independent)."""
    year, month = int(period[:4]), int(period[5:7])
    return datetime(year, month, 1).strftime("%B %Y")


def ensure_period(db: Session, org_id: Any, period: str) -> AccountingPeriod:
    """Get-or-create the registry row for (org_id, period).

    Validates the period string, flushes the new row into the caller's
    transaction (does NOT commit — the caller owns the commit), and returns it.
    """
    period = validate_period(period)
    existing = (
        db.query(AccountingPeriod)
        .filter(AccountingPeriod.org_id == org_id, AccountingPeriod.period == period)
        .first()
    )
    if existing:
        return existing

    row = AccountingPeriod(
        org_id=org_id,
        period=period,
        label=period_label(period),
        status="open",
    )
    db.add(row)
    db.flush()
    return row
