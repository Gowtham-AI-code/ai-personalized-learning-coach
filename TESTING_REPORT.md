# Testing Report

## 1. What was actually executed

Environment used to build the project: Python 3.12, pandas 3.0.6, **no Streamlit, LangChain or Ollama installed, no internet**.

| Check | Method | Result |
|---|---|---|
| 19 automated tests (`tests/test_project.py`) | `python -m unittest discover -s tests -v` | **19 passed, 0 failed** |
| Syntax of all 6 modules | `python -m py_compile` | Passed |
| UI logic of `app.py` (generate page render, save, edit, invalid edit, delete, history, load) | Run against a **stub** Streamlit object (not the real library) | Ran without errors; DB results verified |
| Real Streamlit UI in a browser | - | **NOT executed** (manual) |
| Real Ollama model + LangChain `ChatOllama` | - | **NOT executed** (manual) |
| Quality of real model output | - | **NOT executed** (manual) |

The automated tests use a scripted `FakeLLM`, so they prove the workflow, validation, retry, database and CSV logic, not the quality of a real model's test cases. The `ollama` module was replaced by a stand-in to test connection-error and missing-model handling.

## 2. Assignment test scenarios

| # | Scenario | Automated test | Expected outcome (verified) |
|---|---|---|---|
| 1 | Empty requirement | `test_01` | `EmptyRequirementError`; LLM never called |
| 2 | Valid registration | `test_02` | Positive + Negative + Edge cases, IDs TC-001.., required JSON keys, assumption kept |
| 3 | Login requirement | `test_03` | Feature "User Login", 3 cases returned |
| 4 | Negative scenario request | `test_04` | Only Negative cases; coverage warning shown, no crash |
| 5 | Unclear requirement | `test_05` | Short text rejected in Python; LLM `is_clear=false` returns clarification question; "Generate anyway" records an assumption |
| 6 | Invalid LLM response | `test_06` | Garbage twice -> `InvalidLLMResponseError` after exactly 1 retry; garbage then valid -> succeeds; bad priority, bad scenario, missing field, duplicate IDs, empty list all rejected |
| 7 | Edit test case | `test_07` | Update persisted; values normalised; invalid priority rejected |
| 8 | Delete test case | `test_08` | Row removed; second delete returns False; deleting requirement cascades |
| 9 | Save and reload history | `test_09` | A **new Python process** reads the same DB file and gets the same requirement and 4 test cases |
| 10 | CSV export | `test_10` | UTF-8 BOM, 8 expected columns, 4 rows, priorities and steps correct, file name `user_registration_test_cases.csv` |

Extra automated checks: JSON extraction (fences, `<think>`, surrounding text), duplicate removal and renumbering, normalisation, Ollama connection error, missing model, error translation, invalid database path, DB `CHECK` constraint, CSV formula-injection protection.

## 3. Manual test procedure (do these before the viva)

Prerequisites: Ollama running, `ollama pull llama3.2`, `streamlit run app.py`.

| # | Steps | Expected result | Status |
|---|---|---|---|
| M1 | Click Generate with empty box | Yellow warning asking for a requirement | Not yet run |
| M2 | Click the **Registration** example, Generate | Progress shows 4 stages; table has valid + invalid email/empty field/short password type cases; priorities only High/Medium/Low | Not yet run |
| M3 | Click **Login** example, Generate | Login-related cases (wrong password, lockout) | Not yet run |
| M4 | Enter "Give invalid input scenarios for the password field." | Mostly Negative/Edge cases | Not yet run |
| M5 | Enter "login" | "Needs more detail" message with a suggestion; "Generate anyway" button appears | Not yet run |
| M6 | Stop Ollama (quit the app), click Generate | Red message "Cannot reach Ollama", app keeps working | Not yet run |
| M7 | Set model name to `doesnotexist`, Generate | Message with `ollama pull doesnotexist` | Not yet run |
| M8 | Edit a test case title and priority, Save changes | Table updates and shows confirmation | Not yet run |
| M9 | Type invalid JSON in Test data, Save changes | Error message; nothing changes | Not yet run |
| M10 | Delete a test case (tick box, click Delete) | Row disappears from table | Not yet run |
| M11 | Click Save to history, close the app (Ctrl+C), start again, open History | Saved requirement is listed with its test cases | Not yet run |
| M12 | Download CSV, open in Excel | Same rows as on screen | Not yet run |
| M13 | Rename/delete `test_cases.db` while app is closed, start app, open History | App recreates the DB, shows "Nothing saved yet" | Not yet run |

Record results (Pass/Fail, date, model used) in the Status column during your own testing.
