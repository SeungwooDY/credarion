"""Data cleaning pipeline for supplier statement rows.

Applied in order: rename → filter summary → normalize POs → normalize numerics
→ strip part numbers → parse dates → build raw_row → drop empty rows.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import pandas as pd

# Summary row keywords — rows containing any of these are dropped
_SUMMARY_KEYWORDS = ["合计", "总计", "小计", "上月结余", "本月实付", "本月余额"]


def rename_columns(df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
    """Rename columns using the mapping (original Chinese → canonical)."""
    reverse = {v: k for k, v in column_map.items()}
    return df.rename(columns=reverse)


def filter_summary_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows that contain summary keywords like 合计, 总计, etc."""

    def _is_summary(row: pd.Series) -> bool:
        row_text = "".join(str(v).replace(" ", "") for v in row if pd.notna(v))
        return any(kw in row_text for kw in _SUMMARY_KEYWORDS)

    mask = df.apply(_is_summary, axis=1)
    return df[~mask].reset_index(drop=True)


def normalize_po_number(val: object) -> str | None:
    """Normalize PO numbers: '428759.0' → '428759', strip whitespace."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    s = str(val).strip()
    # Float-like PO numbers from Excel: "428759.0" → "428759"
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, OverflowError):
        pass
    return s


def normalize_numeric(val: object) -> Decimal | None:
    """Parse a numeric value: remove thousands separators, strip spaces, → Decimal."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    s = str(val).strip()
    # Remove thousands separator commas and spaces
    s = s.replace(",", "").replace(" ", "")
    # Remove trailing/leading whitespace that might remain
    s = s.strip()
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def strip_part_number(val: object) -> str | None:
    """Strip whitespace from material/part numbers."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    return str(val).strip()


def parse_date(val: object) -> pd.Timestamp | None:
    """Parse date values flexibly — handles ISO, slash, M/D/Y formats."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(str(val).strip(), format="mixed", dayfirst=False)
    except Exception:
        return None


def build_raw_row(row: pd.Series, original_columns: list[str]) -> dict[str, str]:
    """Build a JSONB-ready dict of all original column values for audit."""
    raw: dict[str, str] = {}
    for col in original_columns:
        if col in row.index:
            v = row[col]
            raw[col] = str(v) if pd.notna(v) else None
    return raw


def clean_dataframe(
    df: pd.DataFrame,
    column_map: dict[str, str],
) -> pd.DataFrame:
    """Apply the full cleaning pipeline to a raw dataframe.

    Args:
        df: Raw dataframe with original Chinese column headers.
        column_map: Mapping from canonical field name → original column header.

    Returns:
        Cleaned dataframe with canonical column names and normalized values.
    """
    original_columns = list(df.columns)

    # 1. Build raw_row before any transformations
    df["_raw_row"] = df.apply(lambda row: build_raw_row(row, original_columns), axis=1)

    # 2. Rename columns using the mapping
    df = rename_columns(df, column_map)

    # 3. Filter summary rows (before normalization so keywords are still visible)
    df = filter_summary_rows(df)

    # 4. Normalize PO numbers
    if "po_number" in df.columns:
        df["po_number"] = df["po_number"].apply(normalize_po_number)

    # 5. Normalize numerics
    for num_col in ["quantity", "unit_price", "amount"]:
        if num_col in df.columns:
            df[num_col] = df[num_col].apply(normalize_numeric)

    # 6. Strip part numbers
    if "material_number" in df.columns:
        df["material_number"] = df["material_number"].apply(strip_part_number)

    # 7. Parse dates
    if "delivery_date" in df.columns:
        df["delivery_date"] = df["delivery_date"].apply(parse_date)

    # 8. Strip delivery note ref
    if "delivery_note_ref" in df.columns:
        df["delivery_note_ref"] = df["delivery_note_ref"].apply(
            lambda v: str(v).strip() if pd.notna(v) and str(v).strip() else None
        )

    # 9. Drop empty rows — where both po_number and quantity are null
    if "po_number" in df.columns and "quantity" in df.columns:
        df = df.dropna(subset=["po_number", "quantity"], how="all").reset_index(drop=True)

    return df
