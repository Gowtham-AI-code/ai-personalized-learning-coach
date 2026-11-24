"""
Automated tests (standard library unittest, no extra packages needed).

Run from the project folder:
    python -m unittest discover -s tests -v

The AI model is replaced by a scripted FakeLLM, so these tests check the
agent workflow, validation, database and CSV logic. They do NOT measure the
quality of a real Ollama model's answers (see docs/TESTING_REPORT.md).
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent  # noqa: E402
import database as db  # noqa: E402
from agent import (  # noqa: E402
    CaseGeneratorAgent, EmptyRequirementError, InvalidLLMResponseError, ModelNotFoundError,
    OllamaConnectionError, UnclearRequirementError,
)
from export_utils import COLUMNS, export_csv, make_filename, test_cases_to_dataframe  # noqa: E402
from test_case_generator import (  # noqa: E402
    ResponseValidationError, extract_json, validate_response, validate_test_case,
)


# --------------------------------------------------------------------------
# Test helpers
# --------------------------------------------------------------------------
def tc(n, title, kind="Positive", priority="High", **extra):
    item = {
        "test_case_id": f"TC-{n:03d}", "title": title, "scenario_type": kind,
        "preconditions": ["Page is accessible"], "steps": ["Open page", "Enter data", "Submit"],
        "test_data": {"field": "value"}, "expected_result": "Expected behaviour occurs.", "priority": priority,
    }
    item.update(extra)
    return item


def analysis(clear=True, feature="User Registration"):
    return json.dumps({
        "is_clear": clear, "clarification_question": "" if clear else "Which feature do you mean?",
        "feature_name": feature, "requirement_summary": f"{feature} summary.",
        "testing_purpose": "Verify behaviour.", "conditions": ["name", "email", "password"],
        "assumptions": ["Minimum password length is not specified"],
    })


def scenarios():
    return json.dumps({"scenarios": [
        {"type": "Positive", "description": "Valid data"},
        {"type": "Negative", "description": "Empty email"},
        {"type": "Edge", "description": "Very long name"},
    ]})


def generation(cases, feature="User Registration"):
    return json.dumps({"feature_name": feature, "requirement_summary": "Summary.",
                       "assumptions": [], "test_cases": cases})


class FakeLLM:
    """Returns scripted answers in order and counts the calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        return self.replies.pop(0)


def good_replies(feature="User Registration", cases=None):
    cases = cases or [
        tc(1, "Valid registration", "Positive", "High"),
        tc(2, "Empty email", "Negative", "High"),
        tc(3, "Invalid email format", "Negative", "Medium"),
        tc(4, "Very long name", "Edge", "Low"),
    ]
    return [analysis(True, feature), scenarios(), generation(cases, feature)]


# --------------------------------------------------------------------------
# The ten assignment scenarios
# --------------------------------------------------------------------------
class TestAssignmentScenarios(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    # 1
    def test_01_empty_requirement(self):
        for text in ("", "   \n\t "):
            llm = FakeLLM([])
            with self.assertRaises(EmptyRequirementError):
                CaseGeneratorAgent(llm_call=llm).run(text)
            self.assertEqual(llm.calls, 0, "LLM must not be called for empty input")

    # 2
    def test_02_valid_registration(self):
        out = CaseGeneratorAgent(llm_call=FakeLLM(good_replies())).run(
            "A user should be able to register using name, email, and password.")
        types_ = {t["scenario_type"] for t in out.result["test_cases"]}
        self.assertEqual(types_, {"Positive", "Negative", "Edge"})
        self.assertEqual([t["test_case_id"] for t in out.result["test_cases"]], ["TC-001", "TC-002", "TC-003", "TC-004"])
        self.assertEqual(set(out.result), {"feature_name", "requirement_summary", "assumptions", "test_cases"})
        self.assertIn("Minimum password length is not specified", out.result["assumptions"])

    # 3
    def test_03_login_requirement(self):
        cases = [tc(1, "Valid login"), tc(2, "Wrong password", "Negative"), tc(3, "Account locked after 3 attempts", "Edge", "Medium")]
        out = CaseGeneratorAgent(llm_call=FakeLLM(good_replies("User Login", cases))).run(
            "A registered user can log in with email and password.")
        self.assertEqual(out.result["feature_name"], "User Login")
        self.assertEqual(len(out.result["test_cases"]), 3)

    # 4
    def test_04_negative_scenario_request(self):
        cases = [tc(1, "Empty password", "Negative"), tc(2, "Password too short", "Negative", "Medium")]
        out = CaseGeneratorAgent(llm_call=FakeLLM(good_replies("Password Field", cases))).run(
            "Give invalid input scenarios for the password field.")
        self.assertTrue(all(t["scenario_type"] == "Negative" for t in out.result["test_cases"]))
        self.assertTrue(any("No Positive" in w for w in out.warnings))  # coverage warning, not a crash

    # 5
    def test_05_unclear_requirement(self):
        # (a) too short: rejected by Python before any LLM call
        llm = FakeLLM([])
        with self.assertRaises(UnclearRequirementError) as ctx:
            CaseGeneratorAgent(llm_call=llm).run("login")
        self.assertEqual(llm.calls, 0)
        self.assertTrue(ctx.exception.question)
        # (b) LLM says unclear: clarification question is returned
        with self.assertRaises(UnclearRequirementError) as ctx:
            CaseGeneratorAgent(llm_call=FakeLLM([analysis(False)])).run("make the thing work better please")
        self.assertEqual(ctx.exception.question, "Which feature do you mean?")
        # (c) user continues anyway: assumption is recorded
        out = CaseGeneratorAgent(
            llm_call=FakeLLM([analysis(False), scenarios(), generation([tc(1, "Basic case")])])
        ).run("make the thing work better please", allow_unclear=True)
        self.assertTrue(any("unclear" in a.lower() for a in out.result["assumptions"]))

    # 6
    def test_06_invalid_llm_response(self):
        req = "A user should be able to register using name, email, and password."
        # garbage twice -> clear error, no crash, exactly 1 retry
        llm = FakeLLM(["not json at all", "still { broken"])
        with self.assertRaises(InvalidLLMResponseError):
            CaseGeneratorAgent(llm_call=llm).run(req)
        self.assertEqual(llm.calls, 2)
        # garbage once, then valid -> safe retry succeeds
        llm = FakeLLM(["oops"] + good_replies())
        out = CaseGeneratorAgent(llm_call=llm).run(req)
        self.assertEqual(llm.calls, 4)
        self.assertEqual(len(out.result["test_cases"]), 4)
        # bad priority / bad scenario / missing field / duplicate ids are rejected by the validator
        for bad in (tc(1, "x", priority="Critical"), tc(1, "x", kind="Smoke"),
                    {k: v for k, v in tc(1, "x").items() if k != "steps"}):
            with self.assertRaises(ResponseValidationError):
                validate_response(json.loads(generation([bad])))
        with self.assertRaises(ResponseValidationError):
            validate_response(json.loads(generation([tc(1, "a"), tc(1, "b")])))
        with self.assertRaises(ResponseValidationError):
            validate_response({"feature_name": "x"})
        with self.assertRaises(ResponseValidationError):
            validate_response(json.loads(generation([])))

    # 7
    def test_07_edit_test_case(self):
        result = {"feature_name": "F", "requirement_summary": "S", "assumptions": [], "test_cases": [tc(1, "Old title")]}
        req_id, ids = db.save_result("req text", result, self.db_path)
        edited = validate_test_case({**tc(1, "New title", priority="low"), "steps": "1. A\n2. B"})
        self.assertTrue(db.update_test_case(ids[0], edited, self.db_path))
        saved = db.get_test_cases(req_id, self.db_path)[0]
        self.assertEqual((saved["title"], saved["priority"], saved["steps"]), ("New title", "Low", ["A", "B"]))
        with self.assertRaises(ResponseValidationError):
            validate_test_case({**tc(1, "x"), "priority": "Urgent"})

    # 8
    def test_08_delete_test_case(self):
        result = {"feature_name": "F", "requirement_summary": "S", "assumptions": [],
                  "test_cases": [tc(1, "A"), tc(2, "B", "Negative")]}
        req_id, ids = db.save_result("req", result, self.db_path)
        self.assertTrue(db.delete_test_case(ids[0], self.db_path))
        left = db.get_test_cases(req_id, self.db_path)
        self.assertEqual([t["title"] for t in left], ["B"])
        self.assertFalse(db.delete_test_case(ids[0], self.db_path))  # already gone
        self.assertTrue(db.delete_requirement(req_id, self.db_path))
        self.assertEqual(db.get_history(self.db_path), [])

    # 9
    def test_09_save_and_reload_history_after_restart(self):
        out = CaseGeneratorAgent(llm_call=FakeLLM(good_replies())).run(
            "A user should be able to register using name, email, and password.")
        req_id, _ = db.save_result("A user should be able to register...", out.result, self.db_path)
        # Simulate an app restart: a brand-new Python process reads the same file.
        code = (
            "import sys, json; sys.path.insert(0, sys.argv[1]); import database as db;"
            "db.init_db(sys.argv[2]); h = db.get_history(sys.argv[2]);"
            "r = db.load_result(h[0]['id'], sys.argv[2]);"
            "print(json.dumps({'n': len(h), 'feature': r['feature_name'], 'cases': len(r['test_cases'])}))"
        )
        proc = subprocess.run([sys.executable, "-c", code, str(ROOT), str(self.db_path)],
                              capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        self.assertEqual(data, {"n": 1, "feature": "User Registration", "cases": 4})
        loaded = db.load_result(req_id, self.db_path)
        self.assertEqual(loaded["test_cases"][0]["steps"], out.result["test_cases"][0]["steps"])
        self.assertEqual(loaded["test_cases"][0]["test_data"], out.result["test_cases"][0]["test_data"])

    # 10
    def test_10_csv_export(self):
        out = CaseGeneratorAgent(llm_call=FakeLLM(good_replies())).run(
            "A user should be able to register using name, email, and password.")
        data = export_csv(out.result["test_cases"])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM for Excel
        df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
        self.assertEqual(list(df.columns), COLUMNS)
        self.assertEqual(len(df), 4)
        self.assertEqual(df["Priority"].tolist(), ["High", "High", "Medium", "Low"])
        self.assertTrue(df["Steps"][0].startswith("1. Open page"))
        self.assertEqual(json.loads(df["Test Data"][0]), {"field": "value"})
        self.assertEqual(make_filename("User Registration"), "user_registration_test_cases.csv")


# --------------------------------------------------------------------------
# Extra checks: validator details, errors, database
# --------------------------------------------------------------------------
class TestValidatorAndErrors(unittest.TestCase):

    def test_extract_json_variants(self):
        obj = {"a": 1}
        self.assertEqual(extract_json(json.dumps(obj)), obj)
        self.assertEqual(extract_json("```json\n" + json.dumps(obj) + "\n```"), obj)
        self.assertEqual(extract_json("Sure! Here it is: " + json.dumps(obj) + " Hope it helps."), obj)
        self.assertEqual(extract_json("<think>hmm</think>" + json.dumps(obj)), obj)
        for bad in ("", None, "[1,2]", "no json", "{broken"):
            with self.assertRaises(ResponseValidationError):
                extract_json(bad)

    def test_duplicates_removed_and_ids_renumbered(self):
        data = json.loads(generation([tc(1, "Valid login"), tc(2, "valid LOGIN!"), tc(3, "Wrong password", "Negative")]))
        result, warnings = validate_response(data)
        self.assertEqual([t["test_case_id"] for t in result["test_cases"]], ["TC-001", "TC-002"])
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_normalisation(self):
        clean = validate_test_case(tc(1, "x", kind="edge case", priority="MEDIUM", steps=["1. Open", "Step 2: Click"]))
        self.assertEqual((clean["scenario_type"], clean["priority"], clean["steps"]), ("Edge", "Medium", ["Open", "Click"]))

    def test_ollama_connection_error(self):
        fake = types.ModuleType("ollama")

        class Client:
            def __init__(self, **kw): pass
            def list(self): raise ConnectionError("refused")
        fake.Client = Client
        sys.modules["ollama"] = fake
        try:
            with self.assertRaises(OllamaConnectionError):
                agent.check_ollama("http://localhost:11434", "llama3.2")
        finally:
            del sys.modules["ollama"]

    def test_missing_model_error(self):
        fake = types.ModuleType("ollama")

        class Client:
            def __init__(self, **kw): pass
            def list(self): return {"models": [{"model": "mistral:latest"}]}
        fake.Client = Client
        sys.modules["ollama"] = fake
        try:
            with self.assertRaises(ModelNotFoundError):
                agent.check_ollama("http://localhost:11434", "llama3.2")
            self.assertIn("mistral:latest", agent.check_ollama("http://localhost:11434", "mistral"))
        finally:
            del sys.modules["ollama"]

    def test_llm_error_translation(self):
        self.assertIsInstance(agent._translate_llm_error(ConnectionError("x"), "m", "u"), OllamaConnectionError)
        self.assertIsInstance(agent._translate_llm_error(Exception("model 'm' not found"), "m", "u"), ModelNotFoundError)
        self.assertIsInstance(agent._translate_llm_error(Exception("read timed out"), "m", "u"), agent.LLMInvocationError)

    def test_database_error_is_wrapped(self):
        bad = Path(tempfile.gettempdir()) / "no_such_folder_xyz" / "x.db"
        with self.assertRaises(db.DatabaseError):
            db.init_db(bad)

    def test_database_rejects_invalid_priority(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.db"
            db.init_db(path)
            req = db.save_requirement("r", "f", db_path=path)
            with self.assertRaises(db.DatabaseError):
                db.save_test_cases(req, [tc(1, "x", priority="Urgent")], path)

    def test_csv_formula_injection_is_neutralised(self):
        df = test_cases_to_dataframe([tc(1, "=HYPERLINK(\"evil\")")])
        self.assertTrue(df["Title"][0].startswith("'="))


if __name__ == "__main__":
    unittest.main(verbosity=2)
