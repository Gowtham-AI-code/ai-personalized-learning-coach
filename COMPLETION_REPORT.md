# Completion Report

Verification legend: **Auto** = covered by executed automated tests; **Stub** = exercised against a stub Streamlit only; **Manual** = must be verified by you with real Streamlit/Ollama (see `TESTING_REPORT.md`).

## Functional requirements

| ID | Requirement | Implementation | Verification |
|---|---|---|---|
| FR-01 | Requirement input | `app.py` text area + example buttons | Stub; Manual |
| FR-02 | Requirement understanding | `agent.py` Stage 1, `prompts.build_analyzer_prompt`, `validate_analysis` | Auto (fake LLM); Manual (real model) |
| FR-03 | Scenario selection | Stage 2, `validate_scenarios` | Auto (fake LLM); Manual |
| FR-04 | Test case generation | Stage 3, required JSON, `validate_response` | Auto (fake LLM); Manual |
| FR-05 | Priority High/Medium/Low only | `normalize_priority`, DB `CHECK` | Auto |
| FR-06 | Structured table | `st.dataframe` of `test_cases_to_dataframe` | Stub; Manual |
| FR-07 | Edit and delete | `apply_edit`, `delete_test_case`, `database.update/delete_test_case` | Auto (DB), Stub (UI); Manual |
| FR-08 | Save history in SQLite | `database.py`, History page | Auto (incl. new-process reload); Manual |
| FR-09 | CSV export (Pandas) | `export_utils.py`, `st.download_button` | Auto (CSV bytes); Manual (download) |
| FR-10 | Error handling | Custom exceptions in `agent.py`, handlers in `run_generation` | Auto for empty, unclear, invalid JSON, Ollama down, missing model, DB error; Manual for UI messages |

## Mandatory technologies

Python, Streamlit, Ollama + local LLM, LangChain (`ChatOllama`), SQLite, Pandas are all used. No cloud APIs. Git/GitHub: instructions in README section 15.

## Deliverables checklist

| # | Deliverable | Status |
|---|---|---|
| 1 | Source code (9 required files + tests) | Done |
| 2 | requirements.txt | Done (versions not install-tested here) |
| 3 | SQLite implementation | Done, tested |
| 4 | Streamlit application | Written; **not run in real Streamlit** |
| 5 | Ollama and LangChain integration | Written; **not run against real Ollama/LangChain** |
| 6 | Prompts and JSON validation | Done, validation tested |
| 7 | CSV export | Done, tested |
| 8 | README | Done |
| 9 | Testing report | Done (automated results real, manual results pending) |
| 10 | Viva Q&A | Done |
| 11 | GitHub instructions | README section 15 |

## What you must do manually

1. Install Python, Ollama and run `ollama pull llama3.2` (README sections 6-7).
2. `pip install -r requirements.txt`. If a LangChain version conflict appears, run `pip install -U langchain-ollama langchain-core ollama`.
3. Run `streamlit run app.py` and complete tests M1-M13.
4. If `ChatOllama(... client_kwargs=...)` raises an error in your installed version, remove the `client_kwargs` argument in `agent.py` (timeout then uses the default).
5. Push to GitHub.

## Known risks

- Real-model output quality is unverified; small models may need the retry or a larger model.
- Streamlit behaviour was verified only with a stub; minor UI issues are possible on first run.
