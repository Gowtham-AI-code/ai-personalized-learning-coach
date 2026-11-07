"""Learner-input validation and study-plan validation (no network, no database)."""
import json
import os

LEVELS = ["Beginner", "Intermediate", "Advanced"]
MIN_DAYS, MAX_DAYS = 1, 30
MIN_MINUTES, MAX_MINUTES = 10, 480


class ResponseValidationError(ValueError):
    """Raised when an LLM response does not match the structure we asked for."""


def validate_learner_input(subject, goal, level, duration_days, daily_minutes):
    """Return a list of human-readable problems (empty list = input is valid)."""
    errors = []
    if not (subject or "").strip():
        errors.append("Please enter a subject (for example: Python).")
    if not (goal or "").strip():
        errors.append("Please enter your learning goal.")
    if level not in LEVELS:
        errors.append(f"Level must be one of: {', '.join(LEVELS)}.")
    try:
        if not MIN_DAYS <= int(duration_days) <= MAX_DAYS:
            errors.append(f"Target duration must be between {MIN_DAYS} and {MAX_DAYS} days.")
    except (TypeError, ValueError):
        errors.append("Target duration must be a whole number of days.")
    try:
        if not MIN_MINUTES <= int(daily_minutes) <= MAX_MINUTES:
            errors.append(f"Daily study time must be between {MIN_MINUTES} and {MAX_MINUTES} minutes.")
    except (TypeError, ValueError):
        errors.append("Daily study time must be a whole number of minutes.")
    return errors


def _clean_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ResponseValidationError(f"'{field}' is missing or empty.")
    return value.strip()


def validate_plan(data, duration_days, daily_minutes):
    """Check the LLM's plan and return a clean, normalised dictionary.

    Raises ResponseValidationError if anything important is wrong.
    """
    if not isinstance(data, dict):
        raise ResponseValidationError("The plan must be a JSON object.")
    title = _clean_text(data.get("title"), "title")
    summary = data.get("summary") if isinstance(data.get("summary"), str) else ""
    days = data.get("days")
    if not isinstance(days, list) or not days:
        raise ResponseValidationError("'days' must be a non-empty list.")
    if len(days) != int(duration_days):
        raise ResponseValidationError(f"Expected {duration_days} days but got {len(days)}.")

    clean_days = []
    for i, d in enumerate(days, start=1):
        if not isinstance(d, dict):
            raise ResponseValidationError(f"Day {i} must be an object.")
        topic = _clean_text(d.get("topic"), f"day {i} topic")
        objectives = d.get("objectives")
        if isinstance(objectives, str):
            objectives = [objectives]
        if not isinstance(objectives, list) or not objectives:
            raise ResponseValidationError(f"Day {i} needs a non-empty 'objectives' list.")
        objectives = [str(o).strip() for o in objectives if str(o).strip()]
        if not objectives:
            raise ResponseValidationError(f"Day {i} objectives are empty.")
        try:
            minutes = int(float(d.get("estimated_minutes")))
        except (TypeError, ValueError):
            raise ResponseValidationError(f"Day {i} 'estimated_minutes' must be a number.")
        minutes = max(5, min(minutes, int(daily_minutes)))  # never exceed the learner's time
        activity = _clean_text(d.get("practice_activity"), f"day {i} practice_activity")
        clean_days.append({
            "day_number": i, "topic": topic, "objectives": objectives,
            "estimated_minutes": minutes, "practice_activity": activity,
        })
    return {"title": title, "summary": summary.strip(), "days": clean_days}


def load_example_plan(path=None):
    """Load sample_data/example_learning_plan.json (documentation / tests only)."""
    path = path or os.path.join(os.path.dirname(__file__), "sample_data", "example_learning_plan.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
