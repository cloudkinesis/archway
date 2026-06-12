"""Tests for the synthesis/interview completion-loop fix.

Once every interview question is answered, an additional user message must be
treated as a clarification — never as a re-answer to question[0]. It must not
append junk/duplicate assumptions, must not grow the refined problem statement
with stale question context, and must leave the brief ready to proceed.
"""

from app.services.synthesis import SynthesisEngine, _COMPLETION_CLARIFICATION_MESSAGE

USE_CASE = (
    "We want an internal analytics web application with a REST API for our operations "
    "team to track orders and view dashboards across the business."
)


def _interview_answer_assumptions(brief) -> list[str]:
    return [a.text for a in brief.assumptions if a.text.startswith("Interview answer for")]


def _answered_ids(brief) -> list[str]:
    return list(((brief.use_case_profile or {}).get("interview") or {}).get("answered") or [])


def _drive_to_completion(engine: SynthesisEngine, brief):
    """Answer every interview question until none remain pending."""
    guard = 0
    while engine.next_question(brief) is not None and guard < 30:
        question = engine.next_question(brief)
        brief = engine.respond(brief, f"Answer for {question.id}").brief
        guard += 1
    assert engine.next_question(brief) is None, "interview did not reach completion"
    return brief


def test_extra_message_after_all_questions_does_not_reanswer_first_question():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief(USE_CASE)
    first_question = engine.next_question(brief)
    assert first_question is not None
    first_prompt = first_question.prompt

    brief = _drive_to_completion(engine, brief)

    answered_before = _answered_ids(brief)
    ia_before = _interview_answer_assumptions(brief)

    response = engine.respond(brief, "One more thing about the project.")
    after = response.brief

    # Question state is untouched: the answered set did not change.
    assert _answered_ids(after) == answered_before
    # The first question was not re-answered (no new "Interview answer for" entries).
    assert _interview_answer_assumptions(after) == ia_before
    # And the first question's prompt is recorded at most once across answers.
    assert sum(1 for t in _interview_answer_assumptions(after) if first_prompt in t) <= 1


def test_extra_message_after_completion_does_not_append_junk_assumption():
    engine = SynthesisEngine()
    brief = _drive_to_completion(engine, engine.create_initial_brief(USE_CASE))

    ia_before = len(_interview_answer_assumptions(brief))
    texts_before = [a.text for a in brief.assumptions]

    after = engine.respond(brief, "Also make sure this is for internal AWS review only.").brief

    # No new malformed "Interview answer for '<question>'" junk entry.
    assert len(_interview_answer_assumptions(after)) == ia_before
    # No duplicate assumptions were introduced.
    texts_after = [a.text for a in after.assumptions]
    assert len(texts_after) == len(set(texts_after))
    # If a note was added, it is the clean, meaningful clarification form.
    added = [t for t in texts_after if t not in texts_before]
    assert added == ["Additional clarification: Also make sure this is for internal AWS review only."]


def test_refined_problem_statement_does_not_grow_with_stale_question_context():
    engine = SynthesisEngine()
    brief = _drive_to_completion(engine, engine.create_initial_brief(USE_CASE))

    rps_before = brief.refined_problem_statement
    notes_before = rps_before.count("Synthesis interview note:")

    after = engine.respond(brief, "Please keep latency low for dashboards.").brief

    # No new stale "interview note" question context appended.
    assert after.refined_problem_statement.count("Synthesis interview note:") == notes_before
    # The refined problem statement is not grown by the clarification.
    assert after.refined_problem_statement == rps_before


def test_completion_state_remains_ready_to_proceed():
    engine = SynthesisEngine()
    brief = _drive_to_completion(engine, engine.create_initial_brief(USE_CASE))

    readiness_before = engine.readiness(brief)
    response = engine.respond(brief, "Add a note that this is exploratory.")

    # Does not regress to "waiting for question 0".
    assert engine.next_question(response.brief) is None
    assert response.message == _COMPLETION_CLARIFICATION_MESSAGE
    # Readiness remains ready or improves (never worse).
    assert response.readiness.confidence_score >= readiness_before.confidence_score
    assert response.readiness.can_proceed == readiness_before.can_proceed or response.readiness.can_proceed


def test_normal_question_answer_flow_still_works():
    engine = SynthesisEngine()
    brief = engine.create_initial_brief(USE_CASE)

    pending = engine.next_question(brief)
    assert pending is not None
    answered_before = _answered_ids(brief)
    ia_before = len(_interview_answer_assumptions(brief))

    response = engine.respond(brief, "We expect about 5000 requests per day.")
    after = response.brief

    # The pending question is now recorded as answered (normal flow unchanged).
    assert pending.id in _answered_ids(after)
    assert len(_answered_ids(after)) == len(answered_before) + 1
    # A normal interview answer assumption was added.
    assert len(_interview_answer_assumptions(after)) == ia_before + 1
    # And the response is not the completion clarification message yet.
    assert response.message != _COMPLETION_CLARIFICATION_MESSAGE
