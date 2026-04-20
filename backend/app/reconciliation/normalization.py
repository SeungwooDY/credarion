"""Normalization utilities for reconciliation matching.

Builds on app.ingestion.cleaning.normalize_po_number with additional
transformations for fuzzy matching (strip dashes, leading zeros, etc.).
"""
from __future__ import annotations

import re

from app.ingestion.cleaning import normalize_po_number


def normalize_po_for_matching(val: object) -> str | None:
    """Normalize PO number for fuzzy matching.

    Steps beyond basic normalization:
      1. Apply standard PO normalization (float fix, strip whitespace)
      2. Remove dashes, spaces, and underscores
      3. Strip leading zeros
    """
    base = normalize_po_number(val)
    if base is None:
        return None
    # Remove dashes, spaces, underscores
    s = re.sub(r"[-_\s]", "", base)
    # Strip leading zeros
    s = s.lstrip("0") or "0"
    return s


def normalize_material_for_matching(val: object) -> str | None:
    """Normalize material/part number for fuzzy matching.

    Steps:
      1. Strip whitespace
      2. Uppercase
      3. Remove dashes, spaces, underscores
      4. Strip leading zeros
    """
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.upper()
    s = re.sub(r"[-_\s]", "", s)
    s = s.lstrip("0") or "0"
    return s
