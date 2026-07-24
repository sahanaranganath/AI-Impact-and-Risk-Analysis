"""
Annotation storage — a single local CSV file (pandas), not a database.

Grain: one row per SOC code (a note is overwritten, not appended, when the
same SOC is saved again — the UI has one text_area per SOC in Screen 3).
"""

import os
from datetime import datetime, timezone

import pandas as pd

ANNOTATIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "annotations.csv")
ANNOTATIONS_PATH = os.path.abspath(ANNOTATIONS_PATH)

COLUMNS = ["soc_code", "note", "include_in_report", "updated_at"]


def _ensure_file():
    os.makedirs(os.path.dirname(ANNOTATIONS_PATH), exist_ok=True)
    if not os.path.exists(ANNOTATIONS_PATH):
        pd.DataFrame(columns=COLUMNS).to_csv(ANNOTATIONS_PATH, index=False)


def load_annotations():
    _ensure_file()
    df = pd.read_csv(ANNOTATIONS_PATH, dtype={"soc_code": str})
    if df.empty:
        df = pd.DataFrame(columns=COLUMNS)
    return df


def get_annotation(soc_code):
    df = load_annotations()
    match = df[df["soc_code"] == soc_code]
    if match.empty:
        return {"soc_code": soc_code, "note": "", "include_in_report": True, "updated_at": None}
    row = match.iloc[-1]
    return {
        "soc_code": row["soc_code"],
        "note": "" if pd.isna(row["note"]) else row["note"],
        "include_in_report": bool(row["include_in_report"]),
        "updated_at": row["updated_at"],
    }


def save_annotation(soc_code, note, include_in_report):
    df = load_annotations()
    df = df[df["soc_code"] != soc_code]
    new_row = {
        "soc_code": soc_code,
        "note": note,
        "include_in_report": bool(include_in_report),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(ANNOTATIONS_PATH, index=False)
    return new_row
