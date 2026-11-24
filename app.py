"""
app.py - Streamlit dashboard (Stage 5: Result Manager).

Run with:   streamlit run app.py

Pages (sidebar):
  Home      - project name, description, overview, instructions
  Generate  - enter requirement, run the agent, review / edit / delete / save / export
  History   - saved requirements and their test cases (stored in SQLite)

Working copy of the results is kept in st.session_state["current"]:
  {uid, requirement_id, requirement_text, feature_name, requirement_summary,
   assumptions, created_at, test_cases: [{..., "db_id": int | None}]}
Test cases with a db_id are already in SQLite, so edits and deletes on them
are written to the database immediately.
"""

import json

import streamlit as st

import database as db
from agent import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, AgentError, CaseGeneratorAgent, EmptyRequirementError,
    InvalidLLMResponseError, LLMInvocationError, ModelNotFoundError, OllamaConnectionError,
    UnclearRequirementError, check_ollama,
)
from export_utils import export_csv, make_filename, test_cases_to_dataframe
from test_case_generator import (
    VALID_PRIORITIES, VALID_SCENARIOS, ResponseValidationError, validate_test_case,
)

EXAMPLES = {
    "Registration": "A user should be able to register using name, email, and password.",
    "Login": "A registered user can log in with email and password. After 3 failed attempts the account is locked.",
    "Password field": "The password field must accept 8 to 20 characters and must include at least one number.",
    "Search box": "Users can search products by keyword. The search shows matching products or a 'no results' message.",
}

st.set_page_config(page_title="AI Test Case Generator Agent", page_icon="🧪", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; max-width: 1250px;}
    .hero {padding: 1.4rem 1.6rem; border-radius: 10px; border-left: 6px solid #0f766e;
           background: rgba(15,118,110,0.10); margin-bottom: 1.2rem;}
    .hero h1 {margin: 0 0 .3rem 0; font-size: 2rem;}
    .hero p {margin: 0; font-size: 1.05rem; opacity: .9;}
    .note {padding: .7rem 1rem; border-radius: 8px; background: rgba(217,119,6,0.12);
           border-left: 4px solid #d97706; margin: .5rem 0 1rem 0; font-size: .95rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Session state and small helpers
# --------------------------------------------------------------------------
def init_state() -> None:
    defaults = {
        "page": "Home", "requirement_input": "", "current": None, "analysis": None,
        "scenarios": None, "warnings": [], "unclear_question": None, "uid": 0, "flash": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def go_to(page: str) -> None:
    """Callback: switch page (callbacks may change a widget's state safely)."""
    st.session_state.page = page


def set_example(text: str) -> None:
    st.session_state.requirement_input = text
    st.session_state.unclear_question = None


def set_current(result: dict, requirement_text: str, requirement_id=None, db_ids=None, created_at=None) -> None:
    """Make `result` the working copy shown on the Generate page."""
    st.session_state.uid += 1
    test_cases = []
    for i, tc in enumerate(result["test_cases"]):
        item = {k: v for k, v in tc.items() if k != "db_id"}
        item["db_id"] = tc.get("db_id") or (db_ids[i] if db_ids else None)
        test_cases.append(item)
    st.session_state.current = {
        "uid": st.session_state.uid,
        "requirement_id": requirement_id,
        "requirement_text": requirement_text,
        "feature_name": result["feature_name"],
        "requirement_summary": result.get("requirement_summary", ""),
        "assumptions": result.get("assumptions", []),
        "created_at": created_at,
        "test_cases": test_cases,
    }


def flash(kind: str, message: str) -> None:
    st.session_state.flash = (kind, message)


def show_flash() -> None:
    if st.session_state.flash:
        kind, message = st.session_state.flash
        getattr(st, kind)(message)
        st.session_state.flash = None


def plain_test_cases(test_cases: list) -> list:
    """Test cases without the internal db_id key (for export)."""
    return [{k: v for k, v in tc.items() if k != "db_id"} for tc in test_cases]


def show_db_error(exc: Exception) -> None:
    st.error(f"Database problem: {exc}  The app will keep working, but results cannot be saved or loaded right now.")


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
def sidebar() -> None:
    st.sidebar.title("🧪 Test Case Agent")
    st.sidebar.radio("Go to", ["Home", "Generate", "History"], key="page")
    st.sidebar.divider()
    st.sidebar.subheader("Local model settings")
    st.sidebar.text_input("Ollama model", value=DEFAULT_MODEL, key="model_name",
                          help="Any model you have pulled, e.g. llama3.2, qwen2.5:3b, llama3.1:8b")
    st.sidebar.text_input("Ollama URL", value=DEFAULT_BASE_URL, key="ollama_url")
    if st.sidebar.button("Check Ollama connection"):
        try:
            names = check_ollama(st.session_state.ollama_url, st.session_state.model_name)
            st.sidebar.success(f"Connected. Model ready. Installed: {', '.join(names)}")
        except AgentError as exc:
            st.sidebar.error(str(exc))
        except Exception as exc:  # never crash the sidebar
            st.sidebar.error(f"Unexpected problem while checking Ollama: {exc}")


# --------------------------------------------------------------------------
# Home page
# --------------------------------------------------------------------------
def page_home() -> None:
    st.markdown(
        '<div class="hero"><h1>AI Test Case Generator Agent</h1>'
        "<p>Write a software requirement in plain English and get structured positive, negative "
        "and edge-case test cases. Everything runs locally on your computer.</p></div>",
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.subheader("How the agent works")
        st.markdown(
            "1. **Requirement Analyzer** finds the feature and its conditions.\n"
            "2. **Scenario Selector** picks positive, negative and edge scenarios.\n"
            "3. **Test Case Generator** writes IDs, steps, test data, expected results and priorities.\n"
            "4. **Response Validator** checks every answer with Python before you see it.\n"
            "5. **Result Manager** lets you edit, delete, save to SQLite and export to CSV."
        )
    with right:
        st.subheader("How to use it")
        st.markdown(
            "1. Make sure Ollama is running and a model is installed (see the README).\n"
            "2. Open **Generate**, type a requirement or pick an example.\n"
            "3. Click **Generate test cases** and review the table.\n"
            "4. Edit or delete test cases, then **Save to history** and **Download CSV**.\n"
            "5. Open **History** any time to reload saved results."
        )
    st.markdown(
        '<div class="note">AI-generated test cases must be reviewed by a human before they are used '
        "for real software testing.</div>",
        unsafe_allow_html=True,
    )
    st.button("Start generating", type="primary", on_click=go_to, args=("Generate",))


# --------------------------------------------------------------------------
# Generate page
# --------------------------------------------------------------------------
def run_generation(requirement: str, allow_unclear: bool) -> None:
    """Run the agent and show progress / friendly errors. Never raises."""
    status = st.status("Starting the AI agent...", expanded=True)

    def on_status(stage: str, message: str) -> None:
        status.write(f"**{stage}**: {message}")

    try:
        agent = CaseGeneratorAgent(model=st.session_state.model_name, base_url=st.session_state.ollama_url)
        outcome = agent.run(requirement, allow_unclear=allow_unclear, on_status=on_status)
    except EmptyRequirementError as exc:
        status.update(label="No requirement entered", state="error", expanded=False)
        st.warning(str(exc))
        return
    except UnclearRequirementError as exc:
        status.update(label="The requirement needs more detail", state="error", expanded=False)
        st.session_state.unclear_question = exc.question
        return
    except OllamaConnectionError as exc:
        status.update(label="Ollama is not reachable", state="error", expanded=False)
        st.error(f"{exc}\n\nTip: install Ollama from https://ollama.com and keep it running.")
        return
    except ModelNotFoundError as exc:
        status.update(label="Model not installed", state="error", expanded=False)
        st.error(str(exc))
        return
    except InvalidLLMResponseError as exc:
        status.update(label="The model's answer was not usable", state="error", expanded=False)
        st.error(f"{exc}\n\nNothing was saved. Click Generate again, or try a larger model.")
        return
    except LLMInvocationError as exc:
        status.update(label="The model call failed", state="error", expanded=False)
        st.error(str(exc))
        return
    except AgentError as exc:
        status.update(label="Agent error", state="error", expanded=False)
        st.error(str(exc))
        return
    except Exception as exc:  # last safety net so the app never shows a raw traceback
        status.update(label="Unexpected error", state="error", expanded=False)
        st.error(f"Something unexpected happened: {exc}")
        return

    status.update(label="Test cases generated and validated", state="complete", expanded=False)
    st.session_state.unclear_question = None
    st.session_state.analysis = outcome.analysis
    st.session_state.scenarios = outcome.scenarios
    st.session_state.warnings = outcome.warnings
    set_current(outcome.result, requirement)


def page_generate() -> None:
    st.header("Generate test cases")
    show_flash()

    # ---- FR-01 requirement input -----------------------------------------
    st.caption("Examples (click to fill the box):")
    cols = st.columns(len(EXAMPLES))
    for col, (name, text) in zip(cols, EXAMPLES.items()):
        col.button(name, on_click=set_example, args=(text,), key=f"example_{name}")

    st.text_area(
        "Software requirement",
        key="requirement_input",
        height=150,
        placeholder="Example: A user should be able to register using name, email, and password.",
    )

    generate = st.button("Generate test cases", type="primary")
    if generate:
        run_generation(st.session_state.requirement_input, allow_unclear=False)

    # Unclear requirement: ask for clarification or continue with assumptions.
    if st.session_state.unclear_question:
        st.warning(f"This requirement is not clear enough.  \n**Suggestion:** {st.session_state.unclear_question}")
        if st.button("Generate anyway and list my assumptions"):
            run_generation(st.session_state.requirement_input, allow_unclear=True)

    if st.session_state.current:
        st.divider()
        render_results()


def render_analysis() -> None:
    cur = st.session_state.current
    analysis = st.session_state.analysis
    with st.expander("Requirement analysis and scenario categories", expanded=True):
        st.markdown(f"**Feature:** {cur['feature_name']}")
        st.markdown(f"**Summary:** {cur['requirement_summary']}")
        if analysis:
            if analysis.get("testing_purpose"):
                st.markdown(f"**Testing purpose:** {analysis['testing_purpose']}")
            if analysis.get("conditions"):
                st.markdown("**Important conditions:**\n" + "\n".join(f"- {c}" for c in analysis["conditions"]))
        if cur["assumptions"]:
            st.markdown("**Assumptions (not stated in the requirement):**\n" + "\n".join(f"- {a}" for a in cur["assumptions"]))
        scenarios = st.session_state.scenarios
        if scenarios:
            st.markdown("**Selected scenarios:**\n" + "\n".join(f"- *{s['type']}*: {s['description']}" for s in scenarios))


def render_results() -> None:
    cur = st.session_state.current
    cases = cur["test_cases"]

    saved_note = f"Saved as history #{cur['requirement_id']}" if cur["requirement_id"] else "Not saved yet"
    st.subheader(f"Test cases for: {cur['feature_name']}")
    st.caption(saved_note)

    st.markdown(
        '<div class="note">AI-generated test cases must be reviewed by a human before they are used '
        "for real software testing.</div>",
        unsafe_allow_html=True,
    )
    for message in st.session_state.warnings:
        st.info(message)
    render_analysis()

    if not cases:
        st.info("All test cases were deleted. Generate new ones or load a saved requirement from History.")
        return

    # ---- FR-06 results table ---------------------------------------------
    m = st.columns(5)
    m[0].metric("Total", len(cases))
    for i, kind in enumerate(VALID_SCENARIOS, start=1):
        m[i].metric(kind, sum(1 for tc in cases if tc["scenario_type"] == kind))
    m[4].metric("High priority", sum(1 for tc in cases if tc["priority"] == "High"))

    df = test_cases_to_dataframe(plain_test_cases(cases))
    st.dataframe(df, hide_index=True)

    # ---- FR-07 edit and delete ------------------------------------------
    st.subheader("Edit or delete a test case")
    labels = [f"{tc['test_case_id']} - {tc['title']}" for tc in cases]
    chosen = st.selectbox("Select a test case", range(len(cases)), format_func=lambda i: labels[i],
                          key=f"select_{cur['uid']}")
    render_edit_form(chosen)

    # ---- FR-08 save, FR-09 export ----------------------------------------
    st.subheader("Save and export")
    c1, c2 = st.columns(2)
    with c1:
        if cur["requirement_id"]:
            st.success("This result is saved. Edits and deletes are written to the database automatically.")
        elif st.button("Save to history", type="primary"):
            save_current()
    with c2:
        st.download_button(
            "Download CSV",
            data=export_csv(plain_test_cases(cases)),
            file_name=make_filename(cur["feature_name"]),
            mime="text/csv",
        )


def save_current() -> None:
    cur = st.session_state.current
    result = {
        "feature_name": cur["feature_name"],
        "requirement_summary": cur["requirement_summary"],
        "assumptions": cur["assumptions"],
        "test_cases": plain_test_cases(cur["test_cases"]),
    }
    try:
        db.init_db()
        req_id, db_ids = db.save_result(cur["requirement_text"], result)
    except db.DatabaseError as exc:
        show_db_error(exc)
        return
    cur["requirement_id"] = req_id
    for tc, db_id in zip(cur["test_cases"], db_ids):
        tc["db_id"] = db_id
    flash("success", f"Saved to history as requirement #{req_id}.")
    st.rerun()


def render_edit_form(index: int) -> None:
    cur = st.session_state.current
    tc = cur["test_cases"][index]
    key = f"{cur['uid']}_{tc['test_case_id']}"

    with st.form(f"edit_form_{key}"):
        st.text_input("Test case ID (read-only)", value=tc["test_case_id"], disabled=True)
        title = st.text_input("Title", value=tc["title"])
        a, b = st.columns(2)
        scenario = a.selectbox("Scenario type", VALID_SCENARIOS, index=VALID_SCENARIOS.index(tc["scenario_type"]))
        priority = b.selectbox("Priority", VALID_PRIORITIES, index=VALID_PRIORITIES.index(tc["priority"]))
        preconditions = st.text_area("Preconditions (one per line)", value="\n".join(tc["preconditions"]))
        steps = st.text_area("Steps (one per line)", value="\n".join(tc["steps"]), height=140)
        test_data = st.text_area("Test data (JSON object)", value=json.dumps(tc["test_data"], indent=2, ensure_ascii=False))
        expected = st.text_area("Expected result", value=tc["expected_result"])
        submitted = st.form_submit_button("Save changes")

    if submitted:
        apply_edit(index, {
            "test_case_id": tc["test_case_id"], "title": title, "scenario_type": scenario,
            "priority": priority, "preconditions": preconditions, "steps": steps,
            "test_data": test_data, "expected_result": expected,
        })

    confirm = st.checkbox("I want to delete this test case", key=f"confirm_{key}")
    if st.button("Delete test case", disabled=not confirm, key=f"delete_{key}"):
        delete_test_case(index)


def apply_edit(index: int, values: dict) -> None:
    """Validate the edited values, then update the working copy (and SQLite if already saved)."""
    cur = st.session_state.current
    tc = cur["test_cases"][index]

    raw_data = values["test_data"].strip()
    try:
        values["test_data"] = json.loads(raw_data) if raw_data else {}
    except json.JSONDecodeError:
        st.error('Test data must be valid JSON, for example {"email": "john@example.com"}.')
        return

    try:
        clean = validate_test_case(values, label=tc["test_case_id"])
    except ResponseValidationError as exc:
        st.error(f"Could not save the changes: {exc}")
        return

    if tc.get("db_id"):
        try:
            db.update_test_case(tc["db_id"], clean)
        except db.DatabaseError as exc:
            show_db_error(exc)
            return

    clean["db_id"] = tc.get("db_id")
    cur["test_cases"][index] = clean
    flash("success", f"{clean['test_case_id']} was updated.")
    st.rerun()


def delete_test_case(index: int) -> None:
    cur = st.session_state.current
    tc = cur["test_cases"][index]
    if tc.get("db_id"):
        try:
            db.delete_test_case(tc["db_id"])
        except db.DatabaseError as exc:
            show_db_error(exc)
            return
    cur["test_cases"].pop(index)
    flash("success", f"{tc['test_case_id']} was deleted.")
    st.rerun()


# --------------------------------------------------------------------------
# History page
# --------------------------------------------------------------------------
def load_from_history(requirement_id: int) -> None:
    """Callback for the 'Load into editor' button."""
    try:
        saved = db.load_result(requirement_id)
    except db.DatabaseError as exc:
        st.session_state.flash = ("error", f"Database problem: {exc}")
        return
    if saved is None:
        st.session_state.flash = ("error", "That saved requirement no longer exists.")
        return
    st.session_state.analysis = None
    st.session_state.scenarios = None
    st.session_state.warnings = []
    st.session_state.unclear_question = None
    set_current(saved, saved["requirement_text"], saved["requirement_id"], created_at=saved["created_at"])
    st.session_state.requirement_input = saved["requirement_text"]
    st.session_state.page = "Generate"
    st.session_state.flash = ("success", f"Loaded requirement #{requirement_id} from history.")


def page_history() -> None:
    st.header("History")
    show_flash()
    try:
        db.init_db()
        history = db.get_history()
    except db.DatabaseError as exc:
        show_db_error(exc)
        return

    if not history:
        st.info("Nothing saved yet. Generate test cases and click **Save to history**.")
        return

    summary = [
        {"ID": h["id"], "Feature": h["feature_name"], "Requirement": h["requirement_text"][:90],
         "Test cases": h["test_case_count"], "Saved at": h["created_at"]}
        for h in history
    ]
    st.dataframe(summary, hide_index=True)

    labels = {h["id"]: f"#{h['id']} - {h['feature_name']} ({h['created_at']})" for h in history}
    chosen = st.selectbox("Choose a saved requirement", list(labels), format_func=lambda i: labels[i])

    try:
        saved = db.load_result(chosen)
    except db.DatabaseError as exc:
        show_db_error(exc)
        return
    if saved is None:
        st.warning("That record no longer exists.")
        return

    st.markdown(f"**Requirement:** {saved['requirement_text']}")
    if saved["requirement_summary"]:
        st.markdown(f"**Summary:** {saved['requirement_summary']}")
    if saved["assumptions"]:
        st.markdown("**Assumptions:**\n" + "\n".join(f"- {a}" for a in saved["assumptions"]))

    if saved["test_cases"]:
        plain = plain_test_cases(saved["test_cases"])
        st.dataframe(test_cases_to_dataframe(plain), hide_index=True)
    else:
        st.info("This requirement has no test cases left.")

    c1, c2, c3 = st.columns(3)
    c1.button("Load into editor", type="primary", on_click=load_from_history, args=(chosen,))
    if saved["test_cases"]:
        c2.download_button("Download CSV", data=export_csv(plain), file_name=make_filename(saved["feature_name"]),
                           mime="text/csv", key=f"history_csv_{chosen}")
    with c3:
        confirm = st.checkbox("Confirm delete of this requirement", key=f"hist_confirm_{chosen}")
        if st.button("Delete requirement", disabled=not confirm, key=f"hist_delete_{chosen}"):
            try:
                db.delete_requirement(chosen)
            except db.DatabaseError as exc:
                show_db_error(exc)
                return
            cur = st.session_state.current
            if cur and cur["requirement_id"] == chosen:
                st.session_state.current = None
            flash("success", f"Requirement #{chosen} was deleted.")
            st.rerun()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    init_state()
    sidebar()
    page = st.session_state.page
    if page == "Home":
        page_home()
    elif page == "Generate":
        page_generate()
    else:
        page_history()


main()
