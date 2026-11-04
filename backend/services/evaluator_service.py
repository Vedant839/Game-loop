"""Semantic evaluation service for open-ended learner responses (V0.3).

Evaluates freeform natural-language answers against authored rubrics via Gemini
with a resilient fallback, caching, foreground timeouts, and idempotent mastery updates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.database import Database, get_database
from backend.schemas.session import InterventionStateEnum, SubmissionStatus
from backend.services.learner_service import get_learner_service

logger = logging.getLogger(__name__)


class EvaluationOutput(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0)
    is_correct: bool
    formative_feedback: str
    misconceptions_detected: list[str] = Field(default_factory=list)


class EvaluatorService:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or get_database()
        self.settings = get_settings()
        self._cache: dict[str, EvaluationOutput] = {}

    def _compute_cache_key(self, intervention_id: str, answer: str) -> str:
        normalized = answer.strip().lower()
        return hashlib.sha256(f"{intervention_id}:{normalized}".encode()).hexdigest()

    def evaluate_offline_fallback(
        self,
        question: str,
        user_answer: str,
        rubric: dict[str, Any] | None,
    ) -> EvaluationOutput:
        """Deterministic heuristic evaluation fallback when LLM is unavailable or times out."""
        if not rubric:
            return EvaluationOutput(
                score=1.0,
                is_correct=True,
                formative_feedback="Good response. Your reasoning has been recorded.",
                misconceptions_detected=[],
            )

        key_concepts = rubric.get("key_concepts", [])
        misconceptions = rubric.get("misconceptions", [])
        passing_score = rubric.get("passing_score", 0.7)
        user_lower = user_answer.lower()

        matched_concepts = [c for c in key_concepts if c.lower() in user_lower]
        flagged_misconceptions: list[str] = []
        for m in misconceptions:
            desc = m.get("description", "")
            tag = m.get("tag", "")
            if tag.lower() in user_lower or (desc and desc.lower() in user_lower):
                flagged_misconceptions.append(tag or desc)

        if key_concepts:
            score = len(matched_concepts) / len(key_concepts)
        else:
            score = 1.0 if len(user_answer.strip().split()) >= 3 else 0.5

        if flagged_misconceptions:
            score = max(0.0, score - 0.3 * len(flagged_misconceptions))

        score = round(min(1.0, max(0.0, score)), 2)
        is_correct = score >= passing_score

        if is_correct:
            feedback = f"Strong reasoning! You clearly addressed key elements: {', '.join(matched_concepts) if matched_concepts else 'core concept'}."
        else:
            missing = [c for c in key_concepts if c not in matched_concepts]
            feedback = f"Partially understood. Consider explaining: {', '.join(missing) if missing else 'the theoretical basis'} in more detail."

        return EvaluationOutput(
            score=score,
            is_correct=is_correct,
            formative_feedback=feedback,
            misconceptions_detected=flagged_misconceptions,
        )

    async def evaluate_submission_async(
        self,
        submission_id: str,
        session_id: str,
        intervention_id: str,
        question: str,
        user_answer: str,
        rubric: dict[str, Any] | None,
        client_id: str,
        user_id: str,
        concept: str,
        tier: int,
    ) -> EvaluationOutput:
        """Asynchronously grade student answer via Gemini (with caching and timeout fallback)."""
        cache_key = self._compute_cache_key(intervention_id, user_answer)
        start_time = time.time()

        if cache_key in self._cache:
            eval_result = self._cache[cache_key]
        else:
            eval_result = await self._call_gemini_or_fallback(question, user_answer, rubric)
            self._cache[cache_key] = eval_result

        latency_ms = int((time.time() - start_time) * 1000)

        # Update submission in SQLite
        submission = self.db.get_submission(submission_id)
        if not submission:
            logger.warning("Submission %s not found in DB during async evaluation finish", submission_id)
            return eval_result

        now_str = datetime.now(timezone.utc).isoformat()
        mastery_already_applied = submission["mastery_applied"]

        # If learner hasn't self-assessed yet, apply mastery update now
        if not mastery_already_applied:
            learner_svc = get_learner_service(self.db)
            learner_svc.record_attempt(
                client_id=client_id,
                user_id=user_id,
                concept=concept,
                is_correct=eval_result.is_correct,
                tier=tier,
            )
            mastery_already_applied = True

        self.db.save_submission(
            submission_id=submission_id,
            session_id=session_id,
            intervention_id=intervention_id,
            idempotency_key=submission["idempotency_key"],
            user_answer=user_answer,
            status=SubmissionStatus.COMPLETED.value,
            resumption_policy=submission["resumption_policy"],
            ai_score=eval_result.score,
            is_correct=eval_result.is_correct,
            formative_feedback=eval_result.formative_feedback,
            misconceptions=eval_result.misconceptions_detected,
            self_assessed=submission["self_assessed"],
            mastery_applied=mastery_already_applied,
            created_at=submission["created_at"],
            evaluated_at=now_str,
            latency_ms=latency_ms,
        )

        # Update session intervention state from EVALUATING to COMPLETED if not already terminal
        from backend.services.session_service import get_session_service

        session_service = get_session_service(db=self.db)
        session_service.record_evaluation_completed(session_id, intervention_id)


        return eval_result

    async def _call_gemini_or_fallback(
        self,
        question: str,
        user_answer: str,
        rubric: dict[str, Any] | None,
    ) -> EvaluationOutput:
        api_key = self.settings.gemini_api_key
        if not api_key:
            return self.evaluate_offline_fallback(question, user_answer, rubric)

        key_value = api_key.get_secret_value()
        if not key_value:
            return self.evaluate_offline_fallback(question, user_answer, rubric)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._invoke_gemini, key_value, question, user_answer, rubric),
                timeout=5.0,
            )
        except Exception as exc:
            logger.warning("Gemini evaluation failed or timed out (%s). Using deterministic rubric fallback.", exc)
            return self.evaluate_offline_fallback(question, user_answer, rubric)

    def _invoke_gemini(
        self,
        api_key: str,
        question: str,
        user_answer: str,
        rubric: dict[str, Any] | None,
    ) -> EvaluationOutput:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key, http_options={"timeout": 6000})

        rubric_json = json.dumps(rubric or {}, indent=2)
        prompt = (
            "You are an expert pedagogical grader evaluating a student's answer to an educational video checkpoint.\n"
            f"Question:\n{question}\n\n"
            f"Authored Rubric:\n{rubric_json}\n\n"
            f"Student's Submitted Answer:\n{user_answer}\n\n"
            "Evaluate whether the student's answer demonstrates conceptual mastery.\n"
            "Return valid JSON matching the schema with score (0.0 to 1.0), is_correct (bool), formative_feedback (string, encouraging and constructive), and misconceptions_detected (list of string tags from rubric)."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=EvaluationOutput.model_json_schema(),
            ),
        )
        text = getattr(response, "text", "")
        data = json.loads(text)
        return EvaluationOutput.model_validate(data)

    def self_assess_submission(
        self,
        submission_id: str,
        session_id: str,
        self_assessed_correct: bool,
    ) -> dict[str, Any]:
        """Allows learner to self-assess a timed-out evaluation using the reference rubric."""
        sub = self.db.get_submission(submission_id)
        if not sub:
            raise ValueError(f"Submission '{submission_id}' not found.")

        now_str = datetime.now(timezone.utc).isoformat()
        session_data = self.db.load_session(session_id)
        if not session_data:
            raise ValueError(f"Session '{session_id}' not found.")

        # Update mastery if not yet applied
        if not sub["mastery_applied"]:
            learner_svc = get_learner_service(self.db)
            # Find concept from lecture if available
            learner_svc.record_attempt(
                client_id=session_data["client_id"],
                user_id=session_data["external_user_id"],
                concept="self_assessed_checkpoint",
                is_correct=self_assessed_correct,
                tier=session_data["active_intervention_tier"],
            )

        self.db.save_submission(
            submission_id=submission_id,
            session_id=session_id,
            intervention_id=sub["intervention_id"],
            idempotency_key=sub["idempotency_key"],
            user_answer=sub["user_answer"],
            status=SubmissionStatus.COMPLETED.value,
            resumption_policy=sub["resumption_policy"],
            ai_score=1.0 if self_assessed_correct else 0.5,
            is_correct=self_assessed_correct,
            formative_feedback="Self-assessment recorded against reference rubric.",
            misconceptions=sub["misconceptions"],
            self_assessed=True,
            mastery_applied=True,
            created_at=sub["created_at"],
            evaluated_at=now_str,
            latency_ms=sub["latency_ms"],
        )

        # Transition intervention to COMPLETED via session_service
        from backend.services.session_service import get_session_service

        session_service = get_session_service(db=self.db)
        updated_state = session_service.record_self_assessment(session_id, sub["intervention_id"])
        return updated_state.model_dump()



_evaluator_service_instance: EvaluatorService | None = None


def get_evaluator_service(db: Database | None = None) -> EvaluatorService:
    global _evaluator_service_instance
    if _evaluator_service_instance is None:
        _evaluator_service_instance = EvaluatorService(db)
    return _evaluator_service_instance

