"""
export_utils.py - Convert test cases to a Pandas DataFrame and to CSV.

The same DataFrame is used for the on-screen table and the CSV download, so
the CSV always contains exactly what the user sees.
"""

import json
import re
from typing import Iterable

import pandas as pd

COLUMNS = [
    "Test Case ID", "Title", "Scenario Type", "Preconditions",
    "Steps", "Test Data", "Expected Result", "Priority",
]

# Spreadsheet programs treat cells starting with these characters as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(text: str) -> str:
    """Prevent CSV/formula injection when the file is opened in Excel."""
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def test_cases_to_dataframe(test_cases: Iterable[dict]) -> pd.DataFrame:
    """Build a display/export DataFrame (one row per test case)."""
    rows = []
    for tc in test_cases:
        rows.append({
            "Test Case ID": _safe_cell(str(tc["test_case_id"])),
            "Title": _safe_cell(str(tc["title"])),
            "Scenario Type": tc["scenario_type"],
            "Preconditions": _safe_cell("\n".join(tc["preconditions"]) if tc["preconditions"] else "None"),
            "Steps": "\n".join(f"{i}. {s}" for i, s in enumerate(tc["steps"], start=1)),
            "Test Data": json.dumps(tc["test_data"], ensure_ascii=False),
            "Expected Result": _safe_cell(str(tc["expected_result"])),
            "Priority": tc["priority"],
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    Encode as UTF-8 with a BOM ('utf-8-sig') so Excel on Windows shows
    non-English characters correctly.
    """
    return df.to_csv(index=False).encode("utf-8-sig")


def export_csv(test_cases: Iterable[dict]) -> bytes:
    """Convenience: test cases -> CSV bytes."""
    return dataframe_to_csv_bytes(test_cases_to_dataframe(test_cases))


def make_filename(feature_name: str) -> str:
    """Safe file name such as 'user_registration_test_cases.csv'."""
    slug = re.sub(r"[^a-z0-9]+", "_", (feature_name or "").lower()).strip("_")
    return f"{slug or 'test_cases'}_test_cases.csv" if slug else "test_cases.csv"
