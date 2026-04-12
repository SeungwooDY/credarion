"""Auto-detect the header row in a supplier statement Excel/CSV file.

Scans rows 0–15 looking for Chinese column keywords that indicate
the header row (订单 + 数量 required, supporting keywords add score).
"""
from __future__ import annotations

import re

import pandas as pd

# Required keywords — both must appear for a row to qualify
_REQUIRED = ["订单", "数量"]
_REQUIRED_SCORE = 10

# Supporting keywords — each adds 1 point
_SUPPORTING = ["单价", "金额", "物料", "型号", "送货", "日期"]


def detect_header_row(df_raw: pd.DataFrame, max_scan: int = 16) -> int:
    """Return the 0-based index of the most likely header row.

    Args:
        df_raw: DataFrame read with ``header=None, dtype=str``.
        max_scan: Number of rows to scan from the top.

    Returns:
        Row index of the detected header.

    Raises:
        ValueError: If no row contains both required keywords.
    """
    best_score = 0
    best_row = -1

    for idx in range(min(max_scan, len(df_raw))):
        row_text = " ".join(str(v) for v in df_raw.iloc[idx] if pd.notna(v))

        # Check required keywords
        has_all_required = all(kw in row_text for kw in _REQUIRED)
        if not has_all_required:
            continue

        score = _REQUIRED_SCORE * len(_REQUIRED)
        for kw in _SUPPORTING:
            if kw in row_text:
                score += 1

        if score > best_score:
            best_score = score
            best_row = idx

    if best_row < 0:
        raise ValueError(
            "Could not detect header row: no row contains both "
            f"required keywords {_REQUIRED} in first {max_scan} rows"
        )

    return best_row


def clean_header_cells(headers: list[str]) -> list[str]:
    """Clean header cell values — handles multi-row headers (newlines) and whitespace."""
    cleaned = []
    for h in headers:
        if pd.isna(h) or str(h).strip() == "":
            cleaned.append("")
            continue
        s = str(h)
        # Replace newlines with nothing (Maiding has multi-row headers with \n)
        s = s.replace("\n", "").replace("\r", "")
        # Normalize whitespace
        s = re.sub(r"\s+", " ", s).strip()
        # Full-width parens → half-width
        s = s.replace("（", "(").replace("）", ")")
        cleaned.append(s)
    return cleaned
