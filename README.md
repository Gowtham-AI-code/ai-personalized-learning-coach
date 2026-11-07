# AI Personalized Learning Coach

A Streamlit web app that builds a personalised, day-wise study plan with Google Gemini, quizzes you on any topic,
scores answers **in Python** (never by the LLM), finds weak topics, recommends what to do next and saves everything in SQLite.

Built for the *Xpert Champs - AI Engineering Internship*.

## Features (mapped to the brief)
| ID | Feature | Where |
|----|---------|-------|
| FR-01 | Learner setup form | `app.py` > Learner Setup |
| FR-02 | Day-wise plan (topics, objectives, minutes, practice) | `ai_service.py`, `learning_plan.py` |
| FR-03 | View / regenerate plan | Study Plan > "Adjust / regenerate plan" |
| FR-04 | Topic selection | Practice Quiz |
| FR-05 | MCQ quiz generation (3-10 questions, default 5) | `ai_service.generate_quiz` |
| FR-06 | Answer submission + correctness | `quiz_manager.score_quiz` |
| FR-07 | Explanations + study suggestions | Results & Feedback |
| FR-08 | Weak-topic detection (< 60%) | `quiz_manager.identify_weak_topics` |
| FR-09 | Next-step recommendation | `quiz_manager.recommend_next_steps` |
| FR-10 | Save plans, attempts, scores, status, dates | `database.py` |
| FR-11 | Progress dashboard | Progress Dashboard |
| FR-12 | Error handling | validation + `AIServiceError` + `DatabaseError` |

## Quick start
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
# open .env and paste your key from https://aistudio.google.com/apikey
streamlit run app.py
```
Run the tests (no API key needed): `python -m unittest discover -s tests -v`

## Files
| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI and page navigation |
| `ai_service.py` | Prompts, Gemini call, JSON extraction, retry, friendly errors |
| `learning_plan.py` | Input validation and plan validation |
| `quiz_manager.py` | Quiz validation, **Python scoring**, weak topics, recommendations |
| `database.py` | SQLite schema and all queries |
| `sample_data/example_learning_plan.json` | Example of the plan JSON format (docs/tests only, not used as app output) |
| `tests/test_project.py` | Automated tests for the brief's 9 test cases |
| `docs/` | Analysis guide, project report, viva Q&A |

## Database tables
`learners` 1-to-many `plans` 1-to-many `plan_days` (topic + status + scores) 1-to-many `quizzes` 1-to-many `quiz_questions`;
`quiz_attempts` links to `quizzes` and `plan_days`.

## Limitations
Single-user (no login); quality depends on the LLM; one short quiz is only an indication of understanding;
topic status is rule-based (>=80% completed, 60-79% keep practising, <60% needs revision).

## Security
Never commit `.env`. It is listed in `.gitignore`. Only `.env.example` (no real key) goes to GitHub.
