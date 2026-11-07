"""SQLite persistence layer for the AI Personalized Learning Coach.

Every function opens a short-lived connection, so data written here is
still available after the Streamlit app is restarted.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DEFAULT_DB_PATH = "learning_coach.db"


class DatabaseError(Exception):
    """Raised when a database operation fails (wraps sqlite3.Error)."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT    NOT NULL,
    goal          TEXT    NOT NULL,
    level         TEXT    NOT NULL,
    duration_days INTEGER NOT NULL,
    daily_minutes INTEGER NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    summary    TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL
);

-- One row per study day/topic. Also holds the topic's performance + status.
CREATE TABLE IF NOT EXISTS plan_days (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id            INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day_number         INTEGER NOT NULL,
    topic              TEXT    NOT NULL,
    objectives         TEXT    NOT NULL,           -- JSON list
    estimated_minutes  INTEGER NOT NULL,
    practice_activity  TEXT    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','in_progress','completed','needs_revision')),
    attempts_count     INTEGER NOT NULL DEFAULT 0,
    last_score         REAL,                       -- percentage 0-100
    best_score         REAL,
    last_attempt_at    TEXT,
    UNIQUE (plan_id, day_number)
);

CREATE TABLE IF NOT EXISTS quizzes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_day_id INTEGER NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
    topic       TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id       INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    question      TEXT    NOT NULL,
    options       TEXT    NOT NULL,                -- JSON list
    correct_index INTEGER NOT NULL,                -- the answer key
    explanation   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id     INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    plan_day_id INTEGER NOT NULL REFERENCES plan_days(id) ON DELETE CASCADE,
    score       INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    percentage  REAL    NOT NULL,
    answers     TEXT    NOT NULL,                  -- JSON list of chosen indexes
    taken_at    TEXT    NOT NULL
);
"""


def _now():
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_connection():
    """Open a connection, commit on success, roll back on error, always close."""
    path = os.getenv("DB_PATH", DEFAULT_DB_PATH)
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Database error: {exc}") from exc


def init_db():
    """Create all tables if they do not exist yet."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


# ------------------------------------------------------------------ plans
def create_learner(profile):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO learners (subject, goal, level, duration_days, daily_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile["subject"], profile["goal"], profile["level"],
             int(profile["duration_days"]), int(profile["daily_minutes"]), _now()),
        )
        return cur.lastrowid


def save_plan(learner_id, plan):
    """Save a validated plan; older plans become inactive (history is kept)."""
    with get_connection() as conn:
        conn.execute("UPDATE plans SET is_active = 0")
        cur = conn.execute(
            "INSERT INTO plans (learner_id, title, summary, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            (learner_id, plan["title"], plan.get("summary", ""), _now()),
        )
        plan_id = cur.lastrowid
        for d in plan["days"]:
            conn.execute(
                "INSERT INTO plan_days (plan_id, day_number, topic, objectives, estimated_minutes, practice_activity) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (plan_id, d["day_number"], d["topic"], json.dumps(d["objectives"]),
                 d["estimated_minutes"], d["practice_activity"]),
            )
        return plan_id


def get_active_plan():
    """Return the newest active plan joined with its learner profile, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT p.id, p.learner_id, p.title, p.summary, p.created_at, "
            "l.subject, l.goal, l.level, l.duration_days, l.daily_minutes "
            "FROM plans p JOIN learners l ON l.id = p.learner_id "
            "WHERE p.is_active = 1 ORDER BY p.id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_plan_days(plan_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_days WHERE plan_id = ? ORDER BY day_number", (plan_id,)
        ).fetchall()
    days = []
    for r in rows:
        d = dict(r)
        d["objectives"] = json.loads(d["objectives"])
        days.append(d)
    return days


# ---------------------------------------------------------------- quizzes
def save_quiz(plan_day_id, topic, questions):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO quizzes (plan_day_id, topic, created_at) VALUES (?, ?, ?)",
            (plan_day_id, topic, _now()),
        )
        quiz_id = cur.lastrowid
        for pos, q in enumerate(questions):
            conn.execute(
                "INSERT INTO quiz_questions (quiz_id, position, question, options, correct_index, explanation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (quiz_id, pos, q["question"], json.dumps(q["options"]),
                 q["correct_index"], q["explanation"]),
            )
        return quiz_id


def get_quiz(quiz_id):
    with get_connection() as conn:
        quiz = conn.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        if not quiz:
            return None
        rows = conn.execute(
            "SELECT question, options, correct_index, explanation FROM quiz_questions "
            "WHERE quiz_id = ? ORDER BY position", (quiz_id,)
        ).fetchall()
    result = dict(quiz)
    result["questions"] = [
        {"question": r["question"], "options": json.loads(r["options"]),
         "correct_index": r["correct_index"], "explanation": r["explanation"]}
        for r in rows
    ]
    return result


def save_attempt(quiz_id, plan_day_id, result, answers, new_status):
    """Store one attempt and update the topic's performance + status."""
    now = _now()
    pct = result["percentage"]
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO quiz_attempts (quiz_id, plan_day_id, score, total, percentage, answers, taken_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (quiz_id, plan_day_id, result["score"], result["total"], pct, json.dumps(answers), now),
        )
        conn.execute(
            "UPDATE plan_days SET attempts_count = attempts_count + 1, last_score = ?, "
            "best_score = CASE WHEN best_score IS NULL OR best_score < ? THEN ? ELSE best_score END, "
            "status = ?, last_attempt_at = ? WHERE id = ?",
            (pct, pct, pct, new_status, now, plan_day_id),
        )
        return cur.lastrowid


def get_attempts(plan_id=None):
    """All attempts (newest first). Pass plan_id to filter to one plan."""
    sql = (
        "SELECT a.id, a.quiz_id, a.plan_day_id, a.score, a.total, a.percentage, a.taken_at, "
        "d.topic, d.day_number, p.id AS plan_id, p.title AS plan_title "
        "FROM quiz_attempts a JOIN plan_days d ON d.id = a.plan_day_id "
        "JOIN plans p ON p.id = d.plan_id "
    )
    params = ()
    if plan_id is not None:
        sql += "WHERE p.id = ? "
        params = (plan_id,)
    sql += "ORDER BY a.id DESC"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_attempt_detail(attempt_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not row:
        return None
    attempt = dict(row)
    attempt["answers"] = json.loads(attempt["answers"])
    attempt["quiz"] = get_quiz(attempt["quiz_id"])
    return attempt
