"""Streamlit user interface for the AI Personalized Learning Coach.

Run with:  streamlit run app.py
"""
import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import ai_service  # noqa: E402  (must come after load_dotenv)
import database  # noqa: E402
import learning_plan  # noqa: E402
import quiz_manager  # noqa: E402
from ai_service import AIServiceError  # noqa: E402
from database import DatabaseError  # noqa: E402

st.set_page_config(page_title="AI Personalized Learning Coach", page_icon="🎓", layout="wide")

PAGES = ["Home", "Learner Setup", "Study Plan", "Practice Quiz",
         "Results & Feedback", "Progress Dashboard", "Learning History"]
STATUS_LABEL = {"pending": "⏳ Pending", "in_progress": "🟡 Keep practising",
                "completed": "✅ Completed", "needs_revision": "🔴 Needs revision"}
LETTERS = "ABCD"

st.markdown("""
<style>
.hero {padding: 1.4rem 1.6rem; border-radius: 14px;
       background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); color: white; margin-bottom: 1rem;}
.hero h1 {color: white; margin: 0 0 .3rem 0;}
.hero p {margin: 0; font-size: 1.05rem; opacity: .95;}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------- helpers
def init_app():
    """Create the database tables once per browser session."""
    if st.session_state.get("db_ready"):
        return
    try:
        database.init_db()
    except DatabaseError as exc:
        st.error(f"Could not open the database: {exc}")
        st.stop()
    st.session_state.db_ready = True
    st.session_state.setdefault("current_quiz", None)
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("advice", None)


def goto(page):
    """Request navigation; applied at the top of the next run."""
    st.session_state.nav_request = page
    st.rerun()


def load_context():
    plan = database.get_active_plan()
    if not plan:
        return None, []
    return plan, database.get_plan_days(plan["id"])


def need_plan_notice():
    st.info("You do not have a study plan yet. Create one first.")
    if st.button("Go to Learner Setup", type="primary"):
        goto("Learner Setup")


def days_table(days):
    return pd.DataFrame([{
        "Day": d["day_number"], "Topic": d["topic"], "Time (min)": d["estimated_minutes"],
        "Status": STATUS_LABEL[d["status"]],
        "Last score": f"{d['last_score']:.0f}%" if d["last_score"] is not None else "-",
        "Attempts": d["attempts_count"],
    } for d in days])


# --------------------------------------------------------------- pages
def page_home():
    st.markdown("""<div class="hero"><h1>🎓 AI Personalized Learning Coach</h1>
    <p>Tell the coach your goal and schedule. It builds a day-wise study plan, quizzes you,
    finds your weak topics and recommends what to do next.</p></div>""", unsafe_allow_html=True)
    plan, days = load_context()
    if plan:
        summary = quiz_manager.progress_summary(days, database.get_attempts(plan["id"]))
        c1, c2, c3 = st.columns(3)
        c1.metric("Current plan", plan["subject"])
        c2.metric("Topics completed", f"{summary['completed']}/{summary['total_topics']}")
        c3.metric("Quizzes taken", summary["attempts"])
        st.progress(summary["completion_pct"] / 100, text=f"{summary['completion_pct']:.0f}% of the plan completed")
        if st.button("Continue learning", type="primary"):
            goto("Practice Quiz")
    else:
        st.write("Get started in about a minute:")
        if st.button("Create my learning plan", type="primary"):
            goto("Learner Setup")
    st.subheader("How it works")
    st.markdown("1. **Set up** your subject, goal, level and time.  \n"
                "2. **Review** the AI-generated day-wise plan.  \n"
                "3. **Pick a topic** and take a short multiple-choice quiz.  \n"
                "4. **Get feedback** - scoring is done by Python, explanations by AI.  \n"
                "5. **Track progress** and follow the revision recommendations.")


def page_setup():
    plan, _ = load_context()
    prev = plan or {}
    st.header("Learner Setup")
    if plan:
        st.warning("You already have an active plan. Submitting this form creates a new plan and "
                   "replaces it on the dashboard (your old quiz history is kept in History).")
    with st.form("setup_form"):
        subject = st.text_input("Subject *", value=prev.get("subject", ""), placeholder="e.g. Python")
        goal = st.text_area("Learning goal *", value=prev.get("goal", ""),
                            placeholder="e.g. Learn Python fundamentals well enough to write small programs")
        level = st.selectbox("Current level", learning_plan.LEVELS,
                             index=learning_plan.LEVELS.index(prev.get("level", "Beginner")))
        c1, c2 = st.columns(2)
        duration = c1.number_input("Target duration (days)", learning_plan.MIN_DAYS, learning_plan.MAX_DAYS,
                                   int(prev.get("duration_days", 7)))
        minutes = c2.number_input("Daily study time (minutes)", learning_plan.MIN_MINUTES,
                                  learning_plan.MAX_MINUTES, int(prev.get("daily_minutes", 45)), step=5)
        submitted = st.form_submit_button("Generate learning plan", type="primary")
    if not submitted:
        return
    errors = learning_plan.validate_learner_input(subject, goal, level, duration, minutes)
    if errors:
        for e in errors:
            st.error(e)
        return
    profile = {"subject": subject.strip(), "goal": goal.strip(), "level": level,
               "duration_days": int(duration), "daily_minutes": int(minutes)}
    try:
        with st.spinner("Your AI coach is designing your plan..."):
            plan_data = ai_service.generate_learning_plan(profile)
    except AIServiceError as exc:
        st.error(str(exc))
        st.info("Nothing was lost. Fix the problem above and press 'Generate learning plan' to retry.")
        return
    learner_id = database.create_learner(profile)
    database.save_plan(learner_id, plan_data)
    st.session_state.current_quiz = None
    st.session_state.last_result = None
    st.session_state.advice = None
    goto("Study Plan")


def page_plan():
    st.header("Your Study Plan")
    plan, days = load_context()
    if not plan:
        return need_plan_notice()
    st.subheader(plan["title"])
    if plan["summary"]:
        st.write(plan["summary"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Subject", plan["subject"])
    c2.metric("Level", plan["level"])
    c3.metric("Days", len(days))
    c4.metric("Total study time", f"{sum(d['estimated_minutes'] for d in days)} min")
    st.caption(f"Goal: {plan['goal']}")
    st.dataframe(days_table(days), hide_index=True, use_container_width=True)
    st.subheader("Day-by-day details")
    for d in days:
        with st.expander(f"Day {d['day_number']}: {d['topic']}  -  {d['estimated_minutes']} min  -  {STATUS_LABEL[d['status']]}"):
            st.markdown("**Objectives**")
            for o in d["objectives"]:
                st.markdown(f"- {o}")
            st.markdown(f"**Practice activity:** {d['practice_activity']}")
    b1, b2 = st.columns(2)
    if b1.button("Practise a topic", type="primary"):
        goto("Practice Quiz")
    if b2.button("Adjust / regenerate plan"):
        goto("Learner Setup")


def page_quiz():
    st.header("Practice Quiz")
    plan, days = load_context()
    if not plan:
        return need_plan_notice()
    by_id = {d["id"]: d for d in days}
    ids = list(by_id)
    suggested = quiz_manager.next_pending_day(days) or days[0]
    weak = quiz_manager.identify_weak_topics(days)
    if weak:
        suggested = weak[0]
    day_id = st.selectbox(
        "Choose a topic", ids, index=ids.index(suggested["id"]),
        format_func=lambda i: f"Day {by_id[i]['day_number']}: {by_id[i]['topic']}  ({STATUS_LABEL[by_id[i]['status']]})",
        key=f"quiz_topic_{plan['id']}")
    day = by_id[day_id]
    n = st.slider("Number of questions", 3, 10, 5)

    if st.button("Generate quiz", type="primary"):
        try:
            with st.spinner("Writing your quiz..."):
                questions = ai_service.generate_quiz(plan["subject"], plan["level"], day["topic"],
                                                     day["objectives"], n)
        except AIServiceError as exc:
            st.error(str(exc))
            st.info("Press 'Generate quiz' again to retry.")
            return
        quiz_id = database.save_quiz(day_id, day["topic"], questions)
        st.session_state.current_quiz = {"quiz_id": quiz_id, "day_id": day_id, "questions": questions,
                                         "nonce": int(time.time() * 1000)}

    quiz = st.session_state.current_quiz
    if not quiz or quiz["day_id"] != day_id:
        st.info("Press 'Generate quiz' to start a quiz on this topic.")
        return

    st.subheader(f"Quiz: {day['topic']}")
    with st.form(f"quiz_form_{quiz['quiz_id']}_{quiz['nonce']}"):
        choices = []
        for i, q in enumerate(quiz["questions"]):
            choices.append(st.radio(
                f"Q{i + 1}. {q['question']}", options=list(range(4)), index=None,
                format_func=lambda k, opts=q["options"]: f"{LETTERS[k]}. {opts[k]}",
                key=f"ans_{quiz['quiz_id']}_{quiz['nonce']}_{i}"))
        submitted = st.form_submit_button("Submit answers", type="primary")
    if not submitted:
        return
    if any(c is None for c in choices):
        st.error("Please answer every question before submitting.")
        return

    result = quiz_manager.score_quiz(quiz["questions"], choices)  # Python scores, not the LLM
    status = quiz_manager.status_for_score(result["percentage"])
    attempt_id = database.save_attempt(quiz["quiz_id"], day_id, result, choices, status)
    fresh_days = database.get_plan_days(plan["id"])
    fresh_day = next(d for d in fresh_days if d["id"] == day_id)
    recommendation = quiz_manager.recommend_next_steps(fresh_day, result["percentage"], fresh_days)

    feedback, source = None, "ai"
    try:
        with st.spinner("Preparing personalised feedback..."):
            feedback = ai_service.generate_feedback(plan["subject"], plan["level"], day["topic"],
                                                    result["score"], result["total"], result["results"])
    except AIServiceError:
        source = "fallback"
        feedback = quiz_manager.build_fallback_feedback(day["topic"], result["percentage"], result["results"])

    st.session_state.last_result = {
        "attempt_id": attempt_id, "quiz_id": quiz["quiz_id"], "day_id": day_id,
        "topic": day["topic"], "day_number": day["day_number"], "result": result,
        "recommendation": recommendation, "feedback": feedback, "feedback_source": source}
    st.session_state.current_quiz = None
    st.session_state.advice = None
    goto("Results & Feedback")


def page_results():
    st.header("Results & Feedback")
    data = st.session_state.get("last_result")
    if not data:
        st.info("Take a quiz first - your latest results will appear here.")
        if st.button("Go to Practice Quiz", type="primary"):
            goto("Practice Quiz")
        return
    res = data["result"]
    st.subheader(f"Day {data['day_number']}: {data['topic']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", f"{res['score']} / {res['total']}")
    c2.metric("Percentage", f"{res['percentage']:.0f}%")
    c3.metric("Attempt ID", f"#{data['attempt_id']}")
    st.progress(res["percentage"] / 100)

    rec = data["recommendation"]
    box = {"weak": st.error, "moderate": st.warning, "strong": st.success}[rec["level"]]
    box(f"**Recommendation:** {rec['message']}")

    fb = data["feedback"]
    st.subheader("Feedback")
    if data["feedback_source"] == "fallback":
        st.warning("AI feedback is unavailable right now, so basic feedback is shown. Your score was saved.")
    st.write(fb["summary"])
    for tip in fb["study_tips"]:
        st.markdown(f"- {tip}")
    if fb["practice_focus"]:
        st.markdown("**Practise next:** " + ", ".join(fb["practice_focus"]))

    st.subheader("Question review")
    for i, r in enumerate(res["results"], start=1):
        icon = "✅" if r["is_correct"] else "❌"
        with st.expander(f"{icon} Q{i}. {r['question']}", expanded=not r["is_correct"]):
            chosen = f"{LETTERS[r['selected']]}. {r['options'][r['selected']]}" if r["selected"] is not None else "(no answer)"
            st.markdown(f"**Your answer:** {chosen}")
            st.markdown(f"**Correct answer:** {LETTERS[r['correct_index']]}. {r['options'][r['correct_index']]}")
            st.markdown(f"**Explanation:** {r['explanation']}")

    b1, b2, b3 = st.columns(3)
    if b1.button("Retake the same quiz"):
        quiz = database.get_quiz(data["quiz_id"])
        st.session_state.current_quiz = {"quiz_id": quiz["id"], "day_id": data["day_id"],
                                         "questions": quiz["questions"], "nonce": int(time.time() * 1000)}
        goto("Practice Quiz")
    if b2.button("New quiz on another topic"):
        goto("Practice Quiz")
    if b3.button("View dashboard"):
        goto("Progress Dashboard")


def page_dashboard():
    st.header("Progress Dashboard")
    plan, days = load_context()
    if not plan:
        return need_plan_notice()
    attempts = database.get_attempts(plan["id"])
    s = quiz_manager.progress_summary(days, attempts)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed topics", f"{s['completed']}/{s['total_topics']}")
    c2.metric("Pending topics", s["pending"])
    c3.metric("Average score", f"{s['average_score']:.0f}%" if s["average_score"] is not None else "-")
    c4.metric("Weak topics", s["weak_topics"])
    st.progress(s["completion_pct"] / 100, text=f"{s['completion_pct']:.0f}% of the plan completed")

    st.subheader("Next actions")
    for a in quiz_manager.next_actions(days):
        st.info(a)
    weak = quiz_manager.identify_weak_topics(days)
    if weak:
        st.warning("Topics flagged for revision: " + ", ".join(f"{w['topic']} ({w['last_score']:.0f}%)" for w in weak))

    st.subheader("Topic status")
    st.dataframe(days_table(days), hide_index=True, use_container_width=True)

    st.subheader("Recent scores")
    if attempts:
        recent = list(reversed(attempts[:10]))
        df = pd.DataFrame({"Attempt": [f"#{a['id']} {a['topic'][:18]}" for a in recent],
                           "Score (%)": [a["percentage"] for a in recent]})
        st.bar_chart(df, x="Attempt", y="Score (%)")
    else:
        st.caption("No quizzes yet. Take one to see your scores here.")

    st.subheader("AI study advice")
    if st.button("Analyse my weak topics with AI"):
        try:
            with st.spinner("Analysing your progress..."):
                st.session_state.advice = ai_service.generate_progress_advice(plan["subject"], plan["level"], days)
        except AIServiceError as exc:
            st.error(str(exc))
    advice = st.session_state.get("advice")
    if advice:
        st.write(advice["weak_topic_analysis"])
        for r in advice["recommendations"]:
            st.markdown(f"- **{r['topic']}** - {r['reason']} *Next step:* {r['action']}")


def page_history():
    st.header("Learning History")
    attempts = database.get_attempts()
    if not attempts:
        st.info("No quiz attempts saved yet.")
        return
    df = pd.DataFrame([{
        "Attempt": a["id"], "Date": a["taken_at"].replace("T", " "), "Plan": a["plan_title"],
        "Day": a["day_number"], "Topic": a["topic"], "Score": f"{a['score']}/{a['total']}",
        "Percentage": a["percentage"]} for a in attempts])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.subheader("Score trend")
    st.line_chart(df.sort_values("Attempt").set_index("Attempt")["Percentage"])

    st.subheader("Review an attempt")
    chosen = st.selectbox("Attempt", [a["id"] for a in attempts],
                          format_func=lambda i: next(f"#{a['id']} - {a['topic']} - {a['score']}/{a['total']}" for a in attempts if a["id"] == i))
    detail = database.get_attempt_detail(chosen)
    if not detail or not detail["quiz"]:
        st.warning("Details for this attempt are not available.")
        return
    for i, (q, picked) in enumerate(zip(detail["quiz"]["questions"], detail["answers"]), start=1):
        ok = picked == q["correct_index"]
        st.markdown(f"{'✅' if ok else '❌'} **Q{i}. {q['question']}**")
        st.markdown(f"Your answer: {q['options'][picked] if picked is not None else '(none)'}  \n"
                    f"Correct answer: {q['options'][q['correct_index']]}")


PAGE_FUNCS = {"Home": page_home, "Learner Setup": page_setup, "Study Plan": page_plan,
              "Practice Quiz": page_quiz, "Results & Feedback": page_results,
              "Progress Dashboard": page_dashboard, "Learning History": page_history}


def main():
    init_app()
    if "nav_request" in st.session_state:               # must run before the radio is created
        st.session_state.page = st.session_state.pop("nav_request")
    st.session_state.setdefault("page", "Home")
    with st.sidebar:
        st.title("🎓 Learning Coach")
        st.radio("Navigate", PAGES, key="page")
        st.divider()
        if os.getenv("GEMINI_API_KEY", "").strip() and not os.getenv("GEMINI_API_KEY", "").startswith("your_"):
            st.caption("🟢 Gemini API key detected")
        else:
            st.caption("🔴 No Gemini API key - see README")
    try:
        PAGE_FUNCS[st.session_state.page]()
    except DatabaseError as exc:
        st.error(f"A database problem occurred: {exc}. Your data was not changed. Please try again.")


main()
