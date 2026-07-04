"""Accounting-period helpers.

Periods are plain "YYYY-MM" strings throughout the app (statements, runs,
sign-offs). There is deliberately no period registry table — the set of
periods that exist is DERIVED from the data (see routers/periods.py), and
open/closed state lives in PeriodSignoff.
"""
from __future__ import annotations

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
