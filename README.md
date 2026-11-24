# AI Test Case Generator Agent

A local, privacy-friendly web app that turns a plain-English software requirement into structured **positive, negative and edge-case test cases**. Built for the *Xpert Champs AI Engineering Internship* (Agentic AI / Software Testing).

> AI-generated test cases must be reviewed by a human before they are used for real testing.

## 1. Problem statement

Writing test cases by hand for every feature is slow, and testers often miss negative or boundary situations. This project converts a written requirement into organised test cases that the tester can review, edit, save and export.

## 2. Objectives

- Accept a requirement in simple English.
- Identify the feature and its important conditions.
- Generate positive, negative and edge-case scenarios with steps, test data, expected results and priority (High / Medium / Low).
- Let users edit, delete, save and export (CSV) the results.
- Keep saved history after the app restarts.

## 3. Technology stack

| Technology | Purpose |
|---|---|
| Python 3.10+ | Application logic, validation |
| Streamlit | Dashboard / user interface |
| Ollama + local LLM (default `llama3.2`) | Local requirement understanding and generation |
| LangChain (`langchain-ollama`) | Connects Python to the Ollama model |
| SQLite | Stores requirements and test cases |
| Pandas | Results table and CSV export |
| Git / GitHub | Version control and submission |

No cloud APIs are used. All AI processing happens on your computer.

## 4. System architecture

```
 User ──> Streamlit UI (app.py)
              │
              ▼
        CaseGeneratorAgent (agent.py)
   ┌──────────┴───────────────────────────────────────────────┐
   │ Stage 1 Requirement Analyzer  ─┐                          │
   │ Stage 2 Scenario Selector      ├─ LangChain ChatOllama ─> Ollama (local LLM)
   │ Stage 3 Test Case Generator   ─┘   prompts from prompts.py│
   │ Stage 4 Response Validator  (pure Python: test_case_generator.py)
   └──────────┬───────────────────────────────────────────────┘
              ▼
   Stage 5 Result Manager (app.py)
        ├─ table + edit/delete
        ├─ database.py  ──> SQLite file test_cases.db
        └─ export_utils.py ──> Pandas ──> CSV download
```

## 5. Folder structure and file responsibilities

```
ai-test-case-generator-agent/
├── app.py                   Streamlit UI: Home, Generate, History pages; edit/delete/save/export controls
├── agent.py                 Agent workflow, Ollama + LangChain connection, retry logic, custom errors
├── test_case_generator.py   JSON extraction and Python validation, duplicate removal, ID renumbering
├── prompts.py               All prompt text for the three LLM stages
├── database.py              SQLite tables and all create/read/update/delete functions
├── export_utils.py          Pandas DataFrame creation and CSV export
├── requirements.txt         Python dependencies
├── .gitignore               Files Git must ignore (database, venv, caches)
├── README.md                This file
├── tests/test_project.py    Automated tests (unittest, no Ollama needed)
└── docs/                    TESTING_REPORT.md, VIVA_QA.md, COMPLETION_REPORT.md
```

## 6. Installation (Windows, step by step)

### 6.1 Install Python
Install Python 3.10 or newer from https://www.python.org/downloads/ and tick **"Add Python to PATH"**. Check:

```powershell
python --version
```

### 6.2 Create a virtual environment and install packages
Open PowerShell in the project folder:

```powershell
cd ai-test-case-generator-agent
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 6.3 Install Ollama and download a model (manual step)
1. Download and install Ollama from https://ollama.com/download (Windows installer). It runs in the background after installation.
2. Download the default model (about 2 GB):

```powershell
ollama pull llama3.2
ollama list
```

Other models also work (enter the name in the app sidebar): `qwen2.5:3b`, `llama3.1:8b` (better quality, needs more RAM). If Ollama is not running, start it with `ollama serve`.

## 7. Run the application

```powershell
venv\Scripts\activate
streamlit run app.py
```

The browser opens at http://localhost:8501.

## 8. How to use

1. Open **Generate**. Type a requirement or click an example button.
2. Click **Generate test cases**. A progress panel shows each agent stage (analysis, scenario categories, generation, validation).
3. Review the analysis, assumptions and the results table.
4. Under **Edit or delete a test case** pick a test case, change fields and click **Save changes**, or tick the confirmation box and click **Delete test case**.
5. Click **Save to history** to store everything in SQLite, and **Download CSV** to export.
6. Open **History** to see saved requirements, view their test cases, download CSV, **Load into editor**, or delete a requirement.

If the requirement is too vague the app asks for clarification and offers **Generate anyway and list my assumptions**.

## 9. Database

SQLite file `test_cases.db` is created next to `app.py` on first use.

**requirements**: `id`, `requirement_text`, `feature_name`, `requirement_summary`, `assumptions` (JSON), `created_at`

**test_cases**: `id`, `requirement_id` (foreign key, `ON DELETE CASCADE`), `test_case_id`, `title`, `scenario_type`, `preconditions` (JSON), `steps` (JSON), `test_data` (JSON), `expected_result`, `priority`, `created_at`

`CHECK` constraints allow only `Positive/Negative/Edge` and `High/Medium/Low`. A requirement and its test cases are saved in one transaction. Edits and deletes of saved test cases are written immediately.

## 10. AI agent workflow

| Stage | Who | Output |
|---|---|---|
| 1 Requirement Analyzer | LLM | Feature name, summary, testing purpose, conditions, assumptions, `is_clear` |
| 2 Scenario Selector | LLM | List of Positive / Negative / Edge scenarios |
| 3 Test Case Generator | LLM | JSON with test cases |
| 4 Response Validator | Python | Validated, de-duplicated, renumbered data |
| 5 Result Manager | Python / Streamlit | Display, edit, delete, save, export |

Every LLM answer passes Python validation. On failure the agent retries once and tells the model what was wrong; after that a clear error is shown and nothing is saved. Python also blocks empty or too-short requirements before the model is called.

## 11. JSON response format

```json
{
  "feature_name": "User Registration",
  "requirement_summary": "Users can register using name, email, and password.",
  "assumptions": [],
  "test_cases": [
    {
      "test_case_id": "TC-001",
      "title": "Valid user registration",
      "scenario_type": "Positive",
      "preconditions": ["Registration page is accessible"],
      "steps": ["Open registration page", "Enter valid name", "Enter valid email", "Enter valid password", "Click Register"],
      "test_data": {"name": "John", "email": "john@example.com", "password": "ValidPassword123"},
      "expected_result": "User account is created successfully.",
      "priority": "High"
    }
  ]
}
```

Validation rules: all fields present; `test_case_id` matches `TC-001` style and is unique; `scenario_type` ∈ {Positive, Negative, Edge}; `priority` ∈ {High, Medium, Low}; `steps` not empty; `test_data` is an object; `expected_result` not empty. Harmless variations (`"edge case"`, `"HIGH"`, numbered steps) are normalised.

## 12. Testing

Automated tests (no Ollama needed, the model is replaced by a scripted fake):

```powershell
python -m unittest discover -s tests -v
```

Manual end-to-end tests with a real model are listed in `docs/TESTING_REPORT.md`.

## 13. Limitations

- Quality depends on the local model; small models may produce generic or imperfect cases.
- Generation takes from several seconds to a few minutes on CPU-only computers (three model calls).
- The agent cannot know rules that are not in the requirement; it lists them as assumptions.
- Single-user local app, no login, no multi-user sharing.
- Test cases are manual-test descriptions; no automated test scripts are produced.
- English requirements work best.

## 14. Future enhancements

- Import requirements from user stories / Jira / documents.
- Export to Excel or test-management tools (TestRail, Jira Xray).
- Generate automated test code (Selenium / Playwright / pytest).
- Test case coverage report and search/filter inside history.
- Model comparison and prompt tuning settings in the UI.
- User accounts and team sharing.

## 15. Upload to GitHub

```powershell
git init
git add .
git commit -m "AI Test Case Generator Agent - initial version"
git branch -M main
git remote add origin https://github.com/<your-username>/ai-test-case-generator-agent.git
git push -u origin main
```

Create the empty repository on github.com first (no README). `.gitignore` keeps `test_cases.db` and `venv/` out of the repository.
