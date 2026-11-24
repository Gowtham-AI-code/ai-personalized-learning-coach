"""
prompts.py - All prompt text used by the AI agent.

Keeping prompts in one file makes the prompt design easy to read, explain and
improve without touching application logic.

Prompt design principles (they follow section 10 of the assignment):
  * Understand the requirement BEFORE generating test cases (separate stages).
  * Never invent application rules; list them as assumptions instead.
  * Ask for a fixed JSON structure that Python can validate.
  * Only allow the scenario types Positive / Negative / Edge.
  * Only allow the priorities High / Medium / Low.
  * Ask for concise, non-duplicate test cases.
"""

# --------------------------------------------------------------------------
# System prompt (sent with every request)
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior software QA engineer who writes clear manual test cases.

Strict rules:
1. Reply with ONE valid JSON object only. No markdown, no code fences, no commentary.
2. Use ONLY information that is in the requirement. Do NOT invent business rules,
   limits or messages (for example a minimum password length). If a rule is needed
   but missing, write it in the "assumptions" list and keep the expected result
   generic (for example "A password validation message is displayed").
3. Be concise. Never repeat a test case or write near-duplicates.
4. Every test case must be relevant to the requirement."""

# --------------------------------------------------------------------------
# Stage 1 - Requirement Analyzer
# --------------------------------------------------------------------------
ANALYZER_SCHEMA = """{
  "is_clear": true,
  "clarification_question": "",
  "feature_name": "Short feature name, e.g. User Registration",
  "requirement_summary": "One sentence summary of the requirement.",
  "testing_purpose": "What the tester must verify.",
  "conditions": ["Each important condition, field or rule stated in the requirement"],
  "assumptions": ["Anything you had to assume because the requirement does not say"]
}"""


def build_analyzer_prompt(requirement: str) -> str:
    return f"""STAGE 1 - REQUIREMENT ANALYSIS.
Read the software requirement and extract its meaning. Do not write test cases yet.

Set "is_clear" to false ONLY if the text is too vague to identify a feature
(for example just "login" or "make it better"). In that case put one short
question for the user in "clarification_question".

Requirement:
\"\"\"{requirement}\"\"\"

Return JSON in exactly this shape:
{ANALYZER_SCHEMA}"""


# --------------------------------------------------------------------------
# Stage 2 - Scenario Selector
# --------------------------------------------------------------------------
SCENARIO_SCHEMA = """{
  "scenarios": [
    {"type": "Positive", "description": "Valid input completes the feature successfully"},
    {"type": "Negative", "description": "Required field left empty"},
    {"type": "Edge", "description": "Input at the boundary of an allowed length"}
  ]
}"""


def build_scenario_prompt(requirement: str, analysis: dict) -> str:
    conditions = "\n".join(f"- {c}" for c in analysis.get("conditions", [])) or "- (none listed)"
    return f"""STAGE 2 - SCENARIO SELECTION.
Choose the test scenarios that are worth testing for this requirement.

Feature: {analysis.get("feature_name", "")}
Testing purpose: {analysis.get("testing_purpose", "")}
Conditions:
{conditions}

Original requirement:
\"\"\"{requirement}\"\"\"

Rules:
- "type" must be exactly one of: Positive, Negative, Edge.
- Include at least one Positive scenario.
- Include Negative scenarios for invalid, empty or missing input where applicable.
- Include Edge scenarios (boundaries, very long input, special characters, whitespace)
  only where they make sense for this requirement.
- 4 to 10 scenarios in total. No duplicates.

Return JSON in exactly this shape:
{SCENARIO_SCHEMA}"""


# --------------------------------------------------------------------------
# Stage 3 - Test Case Generator
# --------------------------------------------------------------------------
GENERATION_SCHEMA = """{
  "feature_name": "User Registration",
  "requirement_summary": "Users can register using name, email, and password.",
  "assumptions": [],
  "test_cases": [
    {
      "test_case_id": "TC-001",
      "title": "Valid user registration",
      "scenario_type": "Positive",
      "preconditions": ["Registration page is accessible"],
      "steps": [
        "Open registration page",
        "Enter valid name",
        "Enter valid email",
        "Enter valid password",
        "Click Register"
      ],
      "test_data": {"name": "John", "email": "john@example.com", "password": "ValidPassword123"},
      "expected_result": "User account is created successfully.",
      "priority": "High"
    }
  ]
}"""


def build_generation_prompt(requirement: str, analysis: dict, scenarios: list) -> str:
    conditions = "\n".join(f"- {c}" for c in analysis.get("conditions", [])) or "- (none listed)"
    scenario_lines = "\n".join(f"- [{s['type']}] {s['description']}" for s in scenarios)
    return f"""STAGE 3 - TEST CASE GENERATION.
Write one test case for each selected scenario below (you may split a scenario
into two cases only if the cases are clearly different).

Original requirement:
\"\"\"{requirement}\"\"\"

Feature: {analysis.get("feature_name", "")}
Summary: {analysis.get("requirement_summary", "")}
Conditions:
{conditions}

Selected scenarios:
{scenario_lines}

Rules:
- "test_case_id" values are sequential: TC-001, TC-002, TC-003, ...
- "scenario_type" must be exactly Positive, Negative or Edge.
- "priority" must be exactly High, Medium or Low
  (High = core success path or security/data-loss risk, Medium = common validation, Low = cosmetic or rare).
- "preconditions" and "steps" are lists of short strings. Do not put numbers in the steps.
- "test_data" is a JSON object with realistic example values (use {{}} only if no data is needed).
- "expected_result" is one clear sentence. If the exact message or limit is not in the
  requirement, keep it generic and add the missing rule to "assumptions".
- Do not repeat test cases. Do not add rules that are not in the requirement.

Return JSON in exactly this shape (the example is only a format guide, do not copy its content):
{GENERATION_SCHEMA}"""


# --------------------------------------------------------------------------
# Retry prompt (used when Python validation rejects a response)
# --------------------------------------------------------------------------
def build_retry_prompt(original_prompt: str, error: str, previous_response: str) -> str:
    snippet = (previous_response or "")[:3000]
    return f"""{original_prompt}

Your previous answer was rejected by the validator.
Validation problem: {error}

Previous answer:
{snippet}

Fix the problem and return the COMPLETE corrected JSON object only."""
