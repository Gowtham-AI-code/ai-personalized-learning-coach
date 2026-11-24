"""
test_case_generator.py - Stage 4 "Response Validator" and test case processing.

The LLM can return broken, incomplete or surprising JSON. Nothing the model says
is shown or saved until it has passed the functions in this file.

What this module does:
  * extract_json()        - pull a JSON object out of raw model text
  * validate_analysis()   - check the Stage 1 output
  * validate_scenarios()  - check the Stage 2 output
  * validate_test_case()  - check / clean ONE test case (also used for user edits)
  * validate_response()   - check the Stage 3 output (required JSON structure),
                            remove duplicates, renumber IDs, add coverage warnings
"""

import json
import re
from typing import Any

# --------------------------------------------------------------------------
# Allowed values (single source of truth for the whole project)
# --------------------------------------------------------------------------
VALID_SCENARIOS = ("Positive", "Negative", "Edge")
VALID_PRIORITIES = ("High", "Medium", "Low")
ID_PATTERN = re.compile(r"^TC-\d{3,}$")
MAX_TEST_CASES = 30

_SCENARIO_ALIASES = {
    "positive": "Positive",
    "negative": "Negative",
    "edge": "Edge",
    "edgecase": "Edge",
    "boundary": "Edge",
}


class ResponseValidationError(Exception):
    """Raised when model output does not match the required structure."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _to_text(value: Any) -> str:
    """Convert a value to a stripped string ('' for None)."""
    if value is None:
        return ""
    return str(value).strip()


def _to_str_list(value: Any, field: str, strip_numbering: bool = False) -> list:
    """Accept a list of strings (or one multi-line string) and return a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [line for line in value.splitlines()]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ResponseValidationError(f"'{field}' must be a list of strings.")
    cleaned = []
    for item in items:
        text = _to_text(item)
        if strip_numbering:
            text = re.sub(r"^\s*(step\s*)?\d+\s*[.):]\s+", "", text, flags=re.IGNORECASE)
        if text:
            cleaned.append(text)
    return cleaned


def normalize_scenario_type(value: Any) -> str:
    """Map 'edge case', 'Edge-Case', 'POSITIVE' ... to Positive / Negative / Edge."""
    key = re.sub(r"[^a-z]", "", _to_text(value).lower())
    if key in _SCENARIO_ALIASES:
        return _SCENARIO_ALIASES[key]
    raise ResponseValidationError(
        f"scenario type '{_to_text(value)}' is not allowed. Use one of: {', '.join(VALID_SCENARIOS)}."
    )


def normalize_priority(value: Any) -> str:
    """Accept only High / Medium / Low (case-insensitive)."""
    text = _to_text(value).capitalize()
    if text in VALID_PRIORITIES:
        return text
    raise ResponseValidationError(
        f"priority '{_to_text(value)}' is not allowed. Use one of: {', '.join(VALID_PRIORITIES)}."
    )


def _clean_json_value(value: Any) -> Any:
    """Keep simple JSON values as-is; turn anything else into text."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False)


# --------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------
def extract_json(raw: Any) -> dict:
    """
    Convert raw model text to a Python dict.
    Handles <think> blocks, ```json fences and text around the JSON object.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ResponseValidationError("The model returned an empty response.")

    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ResponseValidationError("The response does not contain a JSON object.")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ResponseValidationError(
                f"The response is not valid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})."
            ) from exc

    if not isinstance(data, dict):
        raise ResponseValidationError("The JSON must be an object, not a list or a single value.")
    return data


# --------------------------------------------------------------------------
# Stage 1 validator
# --------------------------------------------------------------------------
def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _to_text(value).lower() in ("true", "yes", "1")


def validate_analysis(data: dict) -> dict:
    """Validate and normalise the requirement-analysis result."""
    if "is_clear" not in data:
        raise ResponseValidationError("Missing field 'is_clear'.")
    is_clear = _to_bool(data["is_clear"])
    question = _to_text(data.get("clarification_question"))
    feature = _to_text(data.get("feature_name"))
    summary = _to_text(data.get("requirement_summary"))

    if is_clear and not feature:
        raise ResponseValidationError("Missing field 'feature_name'.")
    if is_clear and not summary:
        raise ResponseValidationError("Missing field 'requirement_summary'.")
    if not is_clear and not question:
        question = "Please describe the feature and its main rules in more detail."

    return {
        "is_clear": is_clear,
        "clarification_question": question,
        "feature_name": feature or "Unclear requirement",
        "requirement_summary": summary,
        "testing_purpose": _to_text(data.get("testing_purpose")),
        "conditions": _to_str_list(data.get("conditions"), "conditions"),
        "assumptions": _to_str_list(data.get("assumptions"), "assumptions"),
    }


# --------------------------------------------------------------------------
# Stage 2 validator
# --------------------------------------------------------------------------
def validate_scenarios(data: dict) -> list:
    """Validate the selected scenarios. Returns [{'type': ..., 'description': ...}]."""
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        raise ResponseValidationError("'scenarios' must be a non-empty list.")

    scenarios, seen = [], set()
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ResponseValidationError(f"scenarios[{i}] must be an object with 'type' and 'description'.")
        try:
            s_type = normalize_scenario_type(item.get("type"))
        except ResponseValidationError as exc:
            raise ResponseValidationError(f"scenarios[{i}]: {exc}") from exc
        description = _to_text(item.get("description"))
        if not description:
            raise ResponseValidationError(f"scenarios[{i}] has an empty description.")
        key = (s_type, description.lower())
        if key not in seen:  # silently drop exact duplicates
            seen.add(key)
            scenarios.append({"type": s_type, "description": description})
    return scenarios


# --------------------------------------------------------------------------
# Stage 3 / 4 validators
# --------------------------------------------------------------------------
def validate_test_case(tc: Any, label: str = "test case", require_id: bool = True) -> dict:
    """
    Validate one test case and return a clean copy containing exactly the
    required fields. Raises ResponseValidationError with a readable message.
    """
    if not isinstance(tc, dict):
        raise ResponseValidationError(f"{label} must be a JSON object.")

    problems = []

    tc_id = _to_text(tc.get("test_case_id"))
    if require_id and not ID_PATTERN.match(tc_id):
        problems.append("'test_case_id' must look like TC-001")

    title = _to_text(tc.get("title"))
    if not title:
        problems.append("'title' is empty")

    scenario = ""
    try:
        scenario = normalize_scenario_type(tc.get("scenario_type"))
    except ResponseValidationError as exc:
        problems.append(f"'scenario_type': {exc}")

    priority = ""
    try:
        priority = normalize_priority(tc.get("priority"))
    except ResponseValidationError as exc:
        problems.append(f"'priority': {exc}")

    preconditions, steps = [], []
    try:
        preconditions = _to_str_list(tc.get("preconditions"), "preconditions")
    except ResponseValidationError as exc:
        problems.append(str(exc))
    try:
        steps = _to_str_list(tc.get("steps"), "steps", strip_numbering=True)
    except ResponseValidationError as exc:
        problems.append(str(exc))
    if not steps:
        problems.append("'steps' must contain at least one step")

    test_data = tc.get("test_data")
    if test_data is None:
        test_data = {}
    elif isinstance(test_data, str) and test_data.strip():
        test_data = {"input": test_data.strip()}
    elif isinstance(test_data, str):
        test_data = {}
    if not isinstance(test_data, dict):
        problems.append("'test_data' must be a JSON object")
        test_data = {}
    test_data = {_to_text(k): _clean_json_value(v) for k, v in test_data.items()}

    expected = _to_text(tc.get("expected_result"))
    if not expected:
        problems.append("'expected_result' is empty")

    if problems:
        raise ResponseValidationError(f"{label}: " + "; ".join(problems) + ".")

    return {
        "test_case_id": tc_id,
        "title": title,
        "scenario_type": scenario,
        "preconditions": preconditions,
        "steps": steps,
        "test_data": test_data,
        "expected_result": expected,
        "priority": priority,
    }


def fill_defaults(data: dict, analysis: dict) -> dict:
    """Fill missing TOP-LEVEL fields from the Stage 1 analysis (small models often omit them)."""
    data = dict(data)
    if not _to_text(data.get("feature_name")):
        data["feature_name"] = analysis.get("feature_name", "")
    if not _to_text(data.get("requirement_summary")):
        data["requirement_summary"] = analysis.get("requirement_summary", "")
    if data.get("assumptions") is None:
        data["assumptions"] = []
    return data


def _dedupe_key(tc: dict) -> tuple:
    return (tc["scenario_type"], re.sub(r"\W+", " ", tc["title"].lower()).strip())


def validate_response(data: dict) -> tuple:
    """
    Validate the full Stage 3 JSON.

    Returns (clean_result, warnings) where clean_result has exactly the
    required structure: feature_name, requirement_summary, assumptions, test_cases.
    Raises ResponseValidationError if the structure is wrong.
    """
    if not isinstance(data, dict):
        raise ResponseValidationError("The response must be a JSON object.")

    missing = [k for k in ("feature_name", "requirement_summary", "assumptions", "test_cases") if k not in data]
    if missing:
        raise ResponseValidationError("Missing required field(s): " + ", ".join(missing) + ".")

    feature = _to_text(data["feature_name"])
    summary = _to_text(data["requirement_summary"])
    if not feature:
        raise ResponseValidationError("'feature_name' is empty.")
    if not summary:
        raise ResponseValidationError("'requirement_summary' is empty.")

    assumptions = _to_str_list(data["assumptions"], "assumptions")

    raw_cases = data["test_cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ResponseValidationError("'test_cases' must be a non-empty list.")

    warnings = []
    if len(raw_cases) > MAX_TEST_CASES:
        warnings.append(f"The model returned {len(raw_cases)} test cases; only the first {MAX_TEST_CASES} were kept.")
        raw_cases = raw_cases[:MAX_TEST_CASES]

    # Validate every test case; collect up to 5 problems so a retry can fix them all at once.
    cleaned, errors = [], []
    for i, tc in enumerate(raw_cases, start=1):
        try:
            cleaned.append(validate_test_case(tc, label=f"test_cases[{i}]"))
        except ResponseValidationError as exc:
            errors.append(str(exc))
    if errors:
        raise ResponseValidationError(" ".join(errors[:5]))

    # IDs must be unique.
    ids = [tc["test_case_id"] for tc in cleaned]
    duplicates = sorted({x for x in ids if ids.count(x) > 1})
    if duplicates:
        raise ResponseValidationError("Duplicate test_case_id value(s): " + ", ".join(duplicates) + ".")

    # Remove duplicate test cases (same scenario type + same title).
    unique, seen = [], set()
    for tc in cleaned:
        key = _dedupe_key(tc)
        if key in seen:
            continue
        seen.add(key)
        unique.append(tc)
    removed = len(cleaned) - len(unique)
    if removed:
        warnings.append(f"{removed} duplicate test case(s) were removed.")

    # Renumber so IDs are always TC-001, TC-002, ... without gaps.
    renumbered = False
    for n, tc in enumerate(unique, start=1):
        new_id = f"TC-{n:03d}"
        if tc["test_case_id"] != new_id:
            tc["test_case_id"] = new_id
            renumbered = True
    if renumbered:
        warnings.append("Test case IDs were renumbered to a continuous sequence.")

    # Coverage warnings (not errors: the requirement may not need every type).
    present = {tc["scenario_type"] for tc in unique}
    for needed in VALID_SCENARIOS:
        if needed not in present:
            warnings.append(f"No {needed} test case was generated. Check whether the requirement needs one.")

    result = {
        "feature_name": feature,
        "requirement_summary": summary,
        "assumptions": assumptions,
        "test_cases": unique,
    }
    return result, warnings
