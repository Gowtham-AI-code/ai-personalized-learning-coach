"""
agent.py - The AI agent: Ollama + LangChain connection and the staged workflow.

Workflow (matches section 7 of the assignment):
  Stage 1  Requirement Analyzer   (LLM)    understand the requirement
  Stage 2  Scenario Selector      (LLM)    choose Positive / Negative / Edge scenarios
  Stage 3  Test Case Generator    (LLM)    write structured test cases as JSON
  Stage 4  Response Validator     (Python) validate every response (test_case_generator.py)
  Stage 5  Result Manager         (app.py + database.py + export_utils.py)

Every LLM stage is validated by Python. If a response is invalid the agent
retries ONCE, telling the model exactly what was wrong, and then raises a
clear error instead of crashing.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from prompts import (
    SYSTEM_PROMPT,
    build_analyzer_prompt,
    build_generation_prompt,
    build_retry_prompt,
    build_scenario_prompt,
)
from test_case_generator import (
    ResponseValidationError,
    extract_json,
    fill_defaults,
    validate_analysis,
    validate_response,
    validate_scenarios,
)

DEFAULT_MODEL = "llama3.2"
DEFAULT_BASE_URL = "http://localhost:11434"
MIN_WORDS = 3
MAX_CHARS = 3000


# --------------------------------------------------------------------------
# Exceptions (each one is shown to the user with a helpful message)
# --------------------------------------------------------------------------
class AgentError(Exception):
    """Base class for all agent errors."""


class RequirementError(AgentError):
    """The user's requirement cannot be processed."""


class EmptyRequirementError(RequirementError):
    """The requirement is empty."""


class UnclearRequirementError(RequirementError):
    """The requirement is too vague. `question` is a clarification question."""

    def __init__(self, message: str, question: str = ""):
        super().__init__(message)
        self.question = question or message


class OllamaConnectionError(AgentError):
    """Ollama is not running or not reachable."""


class ModelNotFoundError(AgentError):
    """The requested model has not been downloaded in Ollama."""


class LLMInvocationError(AgentError):
    """The model call failed for another reason (timeout, server error...)."""


class InvalidLLMResponseError(AgentError):
    """The model kept returning invalid output after a retry."""


@dataclass
class AgentResult:
    """Everything the UI needs after a successful run."""
    result: dict                       # required JSON structure (validated)
    analysis: dict                     # Stage 1 output
    scenarios: list                    # Stage 2 output
    warnings: list = field(default_factory=list)
    model: str = ""


# --------------------------------------------------------------------------
# Input pre-check (pure Python, no LLM needed)
# --------------------------------------------------------------------------
def precheck_requirement(text: str) -> str:
    """Return the cleaned requirement or raise a helpful RequirementError."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise EmptyRequirementError("Please enter a software requirement before generating test cases.")
    if len(cleaned) > MAX_CHARS:
        raise UnclearRequirementError(
            f"The requirement is longer than {MAX_CHARS} characters. Please shorten it or split it into features.",
            "Can you split this into smaller features and submit one at a time?",
        )
    words = [w for w in cleaned.split() if any(ch.isalpha() for ch in w)]
    if len(words) < MIN_WORDS:
        raise UnclearRequirementError(
            "The requirement is too short to understand.",
            "Please describe the feature in a full sentence, for example: "
            "'A user should be able to log in using email and password.'",
        )
    return cleaned


# --------------------------------------------------------------------------
# Ollama helpers
# --------------------------------------------------------------------------
def _extract_model_names(response) -> list:
    """Read model names from ollama.Client().list() (works for old dict and new object formats)."""
    models = getattr(response, "models", None)
    if models is None and isinstance(response, dict):
        models = response.get("models")
    names = []
    for m in models or []:
        name = getattr(m, "model", None) or getattr(m, "name", None)
        if name is None and isinstance(m, dict):
            name = m.get("model") or m.get("name")
        if name:
            names.append(str(name))
    return names


def _model_installed(model: str, installed: list) -> bool:
    wanted = model.strip()
    for name in installed:
        if name == wanted or name == f"{wanted}:latest" or name.startswith(f"{wanted}:"):
            return True
    return False


def check_ollama(base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL) -> list:
    """
    Verify that Ollama is running and `model` is downloaded.
    Returns the list of installed model names.
    """
    try:
        import ollama
    except ImportError as exc:
        raise AgentError("The 'ollama' Python package is missing. Run: pip install -r requirements.txt") from exc

    try:
        response = ollama.Client(host=base_url, timeout=5).list()
    except Exception as exc:  # httpx.ConnectError, ConnectionError, ...
        raise OllamaConnectionError(
            f"Cannot reach Ollama at {base_url}. Start the Ollama app (or run 'ollama serve') and try again."
        ) from exc

    installed = _extract_model_names(response)
    if not _model_installed(model, installed):
        raise ModelNotFoundError(
            f"The model '{model}' is not installed in Ollama. Download it with:  ollama pull {model}"
        )
    return installed


def _translate_llm_error(exc: Exception, model: str, base_url: str) -> AgentError:
    """Turn a low-level exception from LangChain / Ollama / httpx into one of our errors."""
    text = f"{type(exc).__name__} {exc}".lower()
    if getattr(exc, "status_code", None) == 404 or ("model" in text and "not found" in text):
        return ModelNotFoundError(f"The model '{model}' is not installed in Ollama. Download it with:  ollama pull {model}")
    if isinstance(exc, ConnectionError) or any(k in text for k in ("connect", "refused", "unreachable")):
        return OllamaConnectionError(
            f"Cannot reach Ollama at {base_url}. Start the Ollama app (or run 'ollama serve') and try again."
        )
    if "timeout" in text or "timed out" in text:
        return LLMInvocationError("The model took too long to answer. Try a smaller model or a shorter requirement.")
    return LLMInvocationError(f"The model call failed: {exc}")


class OllamaLLM:
    """
    Thin wrapper around LangChain's ChatOllama.
    Calling it with (system_prompt, user_prompt) returns the model's text.
    """

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 temperature: float = 0.2, timeout: int = 300):
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise AgentError(
                "LangChain packages are missing. Run: pip install -r requirements.txt"
            ) from exc

        self.model = model
        self.base_url = base_url
        self._system_message = SystemMessage
        self._human_message = HumanMessage
        # format="json" asks Ollama to constrain the output to valid JSON.
        self._chat = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=temperature,
            format="json",
            client_kwargs={"timeout": timeout},
        )

    def __call__(self, system: str, user: str) -> str:
        try:
            reply = self._chat.invoke([self._system_message(content=system), self._human_message(content=user)])
        except Exception as exc:
            raise _translate_llm_error(exc, self.model, self.base_url) from exc
        content = reply.content
        if isinstance(content, list):  # some versions return content blocks
            content = "".join(part if isinstance(part, str) else part.get("text", "") for part in content)
        return str(content)


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------
StatusCallback = Callable[[str, str], None]


class CaseGeneratorAgent:
    """
    Orchestrates Stages 1-4.

    llm_call: optional callable (system, user) -> str. When omitted, a real
    Ollama model is used through LangChain. Passing a fake callable is how the
    automated tests run without Ollama.
    """

    def __init__(self, llm_call: Optional[Callable[[str, str], str]] = None,
                 model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL, max_retries: int = 1):
        self._llm_call = llm_call
        self.model = model
        self.base_url = base_url
        self.max_retries = max_retries

    # ---- internal helpers -------------------------------------------------
    @staticmethod
    def _notify(callback: Optional[StatusCallback], stage: str, message: str) -> None:
        if callback:
            callback(stage, message)

    def _ask(self, prompt: str, validator: Callable):
        """Call the LLM, parse + validate; retry once with feedback on failure."""
        current_prompt, last_error = prompt, None
        for _ in range(self.max_retries + 1):
            raw = self._llm_call(SYSTEM_PROMPT, current_prompt)
            try:
                return validator(extract_json(raw))
            except ResponseValidationError as exc:
                last_error = exc
                current_prompt = build_retry_prompt(prompt, str(exc), raw)
        raise InvalidLLMResponseError(
            f"The model returned an invalid response twice. Last problem: {last_error} "
            "Try again, or use a larger model."
        )

    # ---- public API -------------------------------------------------------
    def run(self, requirement: str, allow_unclear: bool = False,
            on_status: Optional[StatusCallback] = None) -> AgentResult:
        """
        Run the full workflow for one requirement.

        allow_unclear=True lets the user continue after an "unclear" warning;
        the agent then lists its interpretation as an assumption.
        """
        text = precheck_requirement(requirement)

        if self._llm_call is None:
            self._notify(on_status, "Setup", f"Checking Ollama and model '{self.model}'...")
            check_ollama(self.base_url, self.model)
            self._llm_call = OllamaLLM(self.model, self.base_url)

        # Stage 1 - Requirement Analyzer
        self._notify(on_status, "Stage 1: Requirement Analyzer", "Understanding the feature and its conditions...")
        analysis = self._ask(build_analyzer_prompt(text), validate_analysis)
        if not analysis["is_clear"]:
            if not allow_unclear:
                raise UnclearRequirementError(
                    "The requirement is unclear.", analysis["clarification_question"]
                )
            analysis["assumptions"].append(
                "The requirement was unclear; the feature was interpreted from the limited text provided."
            )
        self._notify(on_status, "Stage 1: Requirement Analyzer",
                     f"Feature identified: {analysis['feature_name']} ({len(analysis['conditions'])} condition(s)).")

        # Stage 2 - Scenario Selector
        self._notify(on_status, "Stage 2: Scenario Selector", "Choosing positive, negative and edge scenarios...")
        scenarios = self._ask(build_scenario_prompt(text, analysis), validate_scenarios)
        counts = {t: sum(1 for s in scenarios if s["type"] == t) for t in ("Positive", "Negative", "Edge")}
        self._notify(on_status, "Stage 2: Scenario Selector",
                     f"Selected {counts['Positive']} positive, {counts['Negative']} negative, {counts['Edge']} edge scenario(s).")

        # Stage 3 + 4 - Generate, then validate with Python
        self._notify(on_status, "Stage 3: Test Case Generator", "Writing structured test cases...")
        result, warnings = self._ask(
            build_generation_prompt(text, analysis, scenarios),
            lambda data: validate_response(fill_defaults(data, analysis)),
        )
        self._notify(on_status, "Stage 4: Response Validator", f"{len(result['test_cases'])} test case(s) passed validation.")

        # Merge assumptions from Stage 1 and Stage 3 without duplicates.
        merged, seen = [], set()
        for item in analysis["assumptions"] + result["assumptions"]:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item.strip())
        result["assumptions"] = merged

        return AgentResult(result=result, analysis=analysis, scenarios=scenarios,
                           warnings=warnings, model=self.model)
