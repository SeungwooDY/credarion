"""Accounting-period helpers.

Periods are plain "YYYY-MM" strings throughout the app (statements, runs,
sign-offs). There is deliberately no period registry table — the set of
periods that exist is DERIVED from the data (see routers/periods.py), and
open/closed state lives in PeriodSignoff. Explicitly created (still-empty)
months are PeriodSignoff rows with status "open"; see can_create_period for
when creation is allowed.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def validate_period(period: str) -> str:
    """Return the period unchanged if it is a valid "YYYY-MM"; raise ValueError."""
    if not _PERIOD_RE.match(period or ""):
        raise ValueError(f"Invalid period {period!r}; expected 'YYYY-MM'")
    return period


def period_label(period: str) -> str:
    """Human label for a period: "2026-07" → "July 2026".

    English only — the frontend localizes month names itself via Intl; this
    label is informational (API browsing, logs, exports).
    """
    validate_period(period)
    year, month = period.split("-")
    return f"{_MONTHS[int(month) - 1]} {year}"


def current_period(today: date | None = None) -> str:
    """The current calendar month as a period string."""
    d = today or date.today()
    return f"{d.year:04d}-{d.month:02d}"


def next_period(period: str) -> str:
    """The month after a period: "2026-12" → "2027-01"."""
    validate_period(period)
    year, month = map(int, period.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def days_until_month_end(today: date | None = None) -> int:
    """Days from today until the last day of the current month (0 on the last day)."""
    d = today or date.today()
    return calendar.monthrange(d.year, d.month)[1] - d.day


def can_create_period(period: str, today: date | None = None) -> bool:
    """Whether a period may be explicitly created today.

    Any past or current month is creatable — teams reconcile historical
    months, so the calendar is open backwards without limit. Future months
    are creatable through December of NEXT year (current year + 1), which
    covers setting up upcoming periods without letting users wander into
    meaningless far-future months.
    """
    validate_period(period)
    d = today or date.today()
    year = int(period.split("-")[0])
    return year <= d.year + 1
