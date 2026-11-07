"""Quiz validation, Python-based scoring, weak-topic detection and recommendations.

IMPORTANT: scores are calculated here from the answer key - never by the LLM.
"""
import random

from learning_plan import ResponseValidationError

LETTERS = "ABCD"
WEAK_THRESHOLD = 60      # below this percentage -> weak topic
STRONG_THRESHOLD = 80    # at or above this percentage -> strong result


def validate_quiz(data, expected_count=5, shuffle=True):
    """Validate the LLM quiz JSON and return normalised questions.

    Each returned question: {question, options[4], correct_index, explanation}.
    """
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ResponseValidationError("Quiz JSON must contain a 'questions' list.")
    raw = data["questions"]
    if len(raw) < expected_count:
        raise ResponseValidationError(f"Expected {expected_count} questions but got {len(raw)}.")

    questions = []
    for n, q in enumerate(raw[:expected_count], start=1):
        if not isinstance(q, dict):
            raise ResponseValidationError(f"Question {n} must be an object.")
        text = q.get("question")
        if not isinstance(text, str) or not text.strip():
            raise ResponseValidationError(f"Question {n} has no text.")
        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4:
            raise ResponseValidationError(f"Question {n} must have exactly 4 options.")
        options = [str(o).strip() for o in options]
        if any(not o for o in options) or len(set(o.lower() for o in options)) != 4:
            raise ResponseValidationError(f"Question {n} options must be non-empty and distinct.")

        correct = q.get("correct_option", q.get("correct_index"))
        if isinstance(correct, bool):
            raise ResponseValidationError(f"Question {n} has an invalid correct answer.")
        if isinstance(correct, int):
            idx = correct
        elif isinstance(correct, str) and correct.strip()[:1].upper() in LETTERS:
            idx = LETTERS.index(correct.strip()[:1].upper())
        else:
            raise ResponseValidationError(f"Question {n} has an invalid correct answer.")
        if not 0 <= idx < 4:
            raise ResponseValidationError(f"Question {n} correct answer is out of range.")

        explanation = q.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ResponseValidationError(f"Question {n} has no explanation.")

        if shuffle:  # LLMs like putting the answer in the same slot, so shuffle in Python
            order = list(range(4))
            random.shuffle(order)
            options = [options[i] for i in order]
            idx = order.index(idx)
        questions.append({"question": text.strip(), "options": options,
                          "correct_index": idx, "explanation": explanation.strip()})
    return questions


def score_quiz(questions, answers):
    """Score a quiz using the answer key.

    answers: list of chosen option indexes (None = unanswered), same order as questions.
    """
    results, score = [], 0
    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else None
        is_correct = chosen is not None and chosen == q["correct_index"]
        score += int(is_correct)
        results.append({
            "question": q["question"], "options": q["options"], "selected": chosen,
            "correct_index": q["correct_index"], "is_correct": is_correct,
            "explanation": q["explanation"],
        })
    total = len(questions)
    pct = round(100.0 * score / total, 1) if total else 0.0
    return {"score": score, "total": total, "percentage": pct, "results": results}


def performance_level(pct):
    if pct < WEAK_THRESHOLD:
        return "weak"
    if pct >= STRONG_THRESHOLD:
        return "strong"
    return "moderate"


def status_for_score(pct):
    """Map a quiz percentage to a topic status stored in the database."""
    level = performance_level(pct)
    return {"weak": "needs_revision", "moderate": "in_progress", "strong": "completed"}[level]


def identify_weak_topics(days):
    """Topics whose most recent quiz was below the weak threshold."""
    return [d for d in days if d["last_score"] is not None and d["last_score"] < WEAK_THRESHOLD]


def next_pending_day(days, exclude_id=None):
    """First topic that has not been completed yet."""
    for d in days:
        if d["id"] != exclude_id and d["status"] in ("pending", "in_progress"):
            return d
    return None


def recommend_next_steps(day, pct, days):
    """Rule-based recommendation after a quiz (FR-09). Returns {level, action, message}."""
    level = performance_level(pct)
    topic = day["topic"]
    if level == "weak":
        return {"level": level, "action": "revise",
                "message": f"Revise '{topic}': re-read the objectives, redo the practice activity, "
                           f"then take another quiz on it."}
    if level == "moderate":
        return {"level": level, "action": "practice",
                "message": f"You are getting there on '{topic}'. Take one more practice quiz to "
                           f"confirm your understanding before moving on."}
    nxt = next_pending_day(days, exclude_id=day["id"])
    weak = [w for w in identify_weak_topics(days) if w["id"] != day["id"]]
    if weak:
        return {"level": level, "action": "revise_other",
                "message": f"Strong result on '{topic}'. Before moving on, revisit "
                           f"'{weak[0]['topic']}', which still needs work."}
    if nxt:
        return {"level": level, "action": "next",
                "message": f"Strong result on '{topic}'. Move on to Day {nxt['day_number']}: "
                           f"'{nxt['topic']}'. One quiz is a good sign, not proof of mastery, "
                           f"so review '{topic}' again later."}
    return {"level": level, "action": "harder",
            "message": f"Strong result on '{topic}' and no topics are left. Try harder, "
                       f"mixed-topic practice and review older topics. One quiz does not prove mastery."}


def next_actions(days):
    """Short to-do list for the dashboard."""
    actions = []
    for w in identify_weak_topics(days):
        actions.append(f"Revise Day {w['day_number']}: {w['topic']} (last score {w['last_score']:.0f}%).")
    for d in days:
        if d["status"] == "in_progress":
            actions.append(f"Practice Day {d['day_number']}: {d['topic']} once more to confirm understanding.")
    nxt = next(( d for d in days if d["status"] == "pending"), None)
    if nxt:
        actions.append(f"Start Day {nxt['day_number']}: {nxt['topic']}.")
    if not actions:
        actions.append("All topics look good. Take a harder mixed quiz or set a new goal.")
    return actions


def progress_summary(days, attempts):
    total = len(days)
    completed = sum(1 for d in days if d["status"] == "completed")
    avg = round(sum(a["percentage"] for a in attempts) / len(attempts), 1) if attempts else None
    return {
        "total_topics": total, "completed": completed,
        "pending": sum(1 for d in days if d["status"] == "pending"),
        "completion_pct": round(100.0 * completed / total, 1) if total else 0.0,
        "average_score": avg, "attempts": len(attempts),
        "weak_topics": len(identify_weak_topics(days)),
    }


def build_fallback_feedback(topic, pct, results):
    """Plain-Python feedback used when the LLM feedback call fails."""
    wrong = [r for r in results if not r["is_correct"]]
    if not wrong:
        summary = f"All answers on '{topic}' were correct. Nice work, but one short quiz is not proof of mastery."
    else:
        summary = f"You got {len(results) - len(wrong)} of {len(results)} right on '{topic}'."
    tips = [f"Review: {r['question']}" for r in wrong[:3]] or ["Try a harder quiz on this topic later."]
    return {"summary": summary, "study_tips": tips, "practice_focus": [topic]}
