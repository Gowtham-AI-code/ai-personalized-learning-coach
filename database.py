"""
database.py - SQLite storage for requirements and generated test cases.

Tables
------
requirements
    id, requirement_text, feature_name, requirement_summary,
    assumptions (JSON text), created_at

test_cases   (many test cases belong to one requirement)
    id, requirement_id -> requirements.id (ON DELETE CASCADE),
    test_case_id, title, scenario_type, preconditions (JSON text),
    steps (JSON text), test_data (JSON text), expected_result,
    priority, created_at

Lists and dictionaries are stored as JSON text. All functions raise
DatabaseError (with a readable message) instead of raw sqlite3 errors.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "test_cases.db"

EDITABLE_FIELDS = (
    "title", "scenario_type", "preconditions", "steps",
    "test_data", "expected_result", "priority",
)
_JSON_FIELDS = ("preconditions", "steps", "test_data")


class DatabaseError(Exception):
    """Raised for any database problem."""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _connect(db_path=DB_PATH):
    """Open a connection, commit on success, roll back on error, always close."""
    conn = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        if conn is not None:
            conn.rollback()
        raise DatabaseError(f"Database error: {exc}") from exc
    finally:
        if conn is not None:
            conn.close()


# --------------------------------------------------------------------------
# Create tables
# --------------------------------------------------------------------------
def init_db(db_path=DB_PATH) -> None:
    """Create the tables if they do not exist yet."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS requirements (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_text    TEXT NOT NULL,
                feature_name        TEXT NOT NULL,
                requirement_summary TEXT NOT NULL DEFAULT '',
                assumptions         TEXT NOT NULL DEFAULT '[]',
                created_at          TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_cases (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id   INTEGER NOT NULL,
                test_case_id     TEXT NOT NULL,
                title            TEXT NOT NULL,
                scenario_type    TEXT NOT NULL CHECK (scenario_type IN ('Positive','Negative','Edge')),
                preconditions    TEXT NOT NULL DEFAULT '[]',
                steps            TEXT NOT NULL DEFAULT '[]',
                test_data        TEXT NOT NULL DEFAULT '{}',
                expected_result  TEXT NOT NULL,
                priority         TEXT NOT NULL CHECK (priority IN ('High','Medium','Low')),
                created_at       TEXT NOT NULL,
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_test_cases_requirement ON test_cases(requirement_id);
            """
        )


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def _insert_requirement(conn, requirement_text, feature_name, summary, assumptions) -> int:
    cur = conn.execute(
        "INSERT INTO requirements (requirement_text, feature_name, requirement_summary, assumptions, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (requirement_text, feature_name, summary, json.dumps(assumptions or [], ensure_ascii=False), _now()),
    )
    return cur.lastrowid


def _insert_test_cases(conn, requirement_id: int, test_cases: list) -> list:
    ids = []
    for tc in test_cases:
        cur = conn.execute(
            "INSERT INTO test_cases (requirement_id, test_case_id, title, scenario_type, preconditions, steps, "
            "test_data, expected_result, priority, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                requirement_id, tc["test_case_id"], tc["title"], tc["scenario_type"],
                json.dumps(tc["preconditions"], ensure_ascii=False),
                json.dumps(tc["steps"], ensure_ascii=False),
                json.dumps(tc["test_data"], ensure_ascii=False),
                tc["expected_result"], tc["priority"], _now(),
            ),
        )
        ids.append(cur.lastrowid)
    return ids


def _row_to_test_case(row: sqlite3.Row) -> dict:
    return {
        "db_id": row["id"],
        "test_case_id": row["test_case_id"],
        "title": row["title"],
        "scenario_type": row["scenario_type"],
        "preconditions": json.loads(row["preconditions"]),
        "steps": json.loads(row["steps"]),
        "test_data": json.loads(row["test_data"]),
        "expected_result": row["expected_result"],
        "priority": row["priority"],
    }


# --------------------------------------------------------------------------
# Save
# --------------------------------------------------------------------------
def save_requirement(requirement_text: str, feature_name: str, summary: str = "",
                     assumptions: Optional[list] = None, db_path=DB_PATH) -> int:
    """Save one requirement and return its new id."""
    with _connect(db_path) as conn:
        return _insert_requirement(conn, requirement_text, feature_name, summary, assumptions)


def save_test_cases(requirement_id: int, test_cases: list, db_path=DB_PATH) -> list:
    """Save test cases for an existing requirement. Returns the new database ids."""
    with _connect(db_path) as conn:
        return _insert_test_cases(conn, requirement_id, test_cases)


def save_result(requirement_text: str, result: dict, db_path=DB_PATH) -> tuple:
    """
    Save a requirement and all its test cases in ONE transaction
    (either everything is saved or nothing is).
    Returns (requirement_id, [database ids of the test cases]).
    """
    with _connect(db_path) as conn:
        req_id = _insert_requirement(
            conn, requirement_text, result["feature_name"],
            result.get("requirement_summary", ""), result.get("assumptions", []),
        )
        ids = _insert_test_cases(conn, req_id, result["test_cases"])
    return req_id, ids


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
def get_history(db_path=DB_PATH) -> list:
    """All saved requirements, newest first, with their test case counts."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT r.id, r.requirement_text, r.feature_name, r.created_at, COUNT(t.id) AS test_case_count "
            "FROM requirements r LEFT JOIN test_cases t ON t.requirement_id = r.id "
            "GROUP BY r.id ORDER BY r.id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_test_cases(requirement_id: int, db_path=DB_PATH) -> list:
    """All test cases of a requirement (each includes its 'db_id')."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM test_cases WHERE requirement_id = ? ORDER BY id", (requirement_id,)
        ).fetchall()
    return [_row_to_test_case(r) for r in rows]


def load_result(requirement_id: int, db_path=DB_PATH) -> Optional[dict]:
    """Load a saved requirement together with its test cases. Returns None if not found."""
    with _connect(db_path) as conn:
        req = conn.execute("SELECT * FROM requirements WHERE id = ?", (requirement_id,)).fetchone()
        if req is None:
            return None
        rows = conn.execute(
            "SELECT * FROM test_cases WHERE requirement_id = ? ORDER BY id", (requirement_id,)
        ).fetchall()
    return {
        "requirement_id": req["id"],
        "requirement_text": req["requirement_text"],
        "feature_name": req["feature_name"],
        "requirement_summary": req["requirement_summary"],
        "assumptions": json.loads(req["assumptions"]),
        "created_at": req["created_at"],
        "test_cases": [_row_to_test_case(r) for r in rows],
    }


# --------------------------------------------------------------------------
# Update / delete
# --------------------------------------------------------------------------
def update_test_case(db_id: int, fields: dict, db_path=DB_PATH) -> bool:
    """
    Update the given fields of one test case.
    Only EDITABLE_FIELDS are accepted. Returns True if a row was changed.
    """
    updates = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not updates:
        raise DatabaseError("No editable fields were provided.")
    columns, values = [], []
    for name, value in updates.items():
        columns.append(f"{name} = ?")
        values.append(json.dumps(value, ensure_ascii=False) if name in _JSON_FIELDS else value)
    values.append(db_id)
    with _connect(db_path) as conn:
        cur = conn.execute(f"UPDATE test_cases SET {', '.join(columns)} WHERE id = ?", values)
        return cur.rowcount > 0


def delete_test_case(db_id: int, db_path=DB_PATH) -> bool:
    """Delete one test case. Returns True if a row was deleted."""
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM test_cases WHERE id = ?", (db_id,)).rowcount > 0


def delete_requirement(requirement_id: int, db_path=DB_PATH) -> bool:
    """Delete a requirement and (through ON DELETE CASCADE) all of its test cases."""
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM requirements WHERE id = ?", (requirement_id,)).rowcount > 0
