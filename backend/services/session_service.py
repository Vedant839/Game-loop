"""Session manager enforcing deterministic state transitions and SQLite persistence per SPEC.md."""

from __future__ import annotations

import uuid
from typing import Any

from backend.database import Database, get_database
from backend.schemas.lecture import InterventionPolicy, InterventionType, Lecture, ResumptionPolicy
from backend.schemas.session import (
    ActiveInterventionPayload,
    EvaluationResult,
    InquiryExperimentSubmission,
    InterventionSessionState,
    InterventionStateEnum,
    SessionState,
)
from backend.services.learner_service import get_learner_service
from backend.services.lecture_service import LectureService, get_lecture_service


class SessionError(Exception):
    """Domain exception for session errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class RuntimeSession:
    def __init__(
        self,
        session_id: str,
        lecture: Lecture,
        client_id: str = "default_client",
        external_user_id: str = "default_learner",
        tier_override: int | None = None,
    ) -> None:
        self.session_id = session_id
        self.lecture = lecture
        self.client_id = client_id
        self.external_user_id = external_user_id
        self.tier_override = tier_override
        self.version: int = 1
        self.active_intervention_id: str | None = None
        self.active_intervention_tier: int = 1
        self.interventions_state: dict[str, InterventionStateEnum] = {
            intv.id: InterventionStateEnum.PENDING for intv in lecture.interventions
        }
        self.completed_submissions: dict[str, EvaluationResult] = {}

    def get_state(self) -> SessionState:
        return SessionState(
            session_id=self.session_id,
            lecture_id=self.lecture.id,
            version=self.version,
            client_id=self.client_id,
            external_user_id=self.external_user_id,
            active_intervention_id=self.active_intervention_id,
            interventions=[
                InterventionSessionState(
                    id=intv.id,
                    trigger_time=intv.trigger_time,
                    state=self.interventions_state[intv.id],
                    policy=getattr(intv, "policy", InterventionPolicy.SKIPPABLE),
                )
                for intv in self.lecture.interventions
            ],
        )


class SessionService:
    def __init__(
        self,
        lecture_service: LectureService | None = None,
        db: Database | None = None,
    ) -> None:
        self.lecture_service = lecture_service or get_lecture_service()
        self.db = db or get_database()
        self._sessions: dict[str, RuntimeSession] = {}

    def _persist_session(self, session: RuntimeSession) -> None:
        completed_json = {
            k: v.model_dump_json() for k, v in session.completed_submissions.items()
        }
        interventions_state = {k: v.value for k, v in session.interventions_state.items()}
        self.db.save_session(
            session_id=session.session_id,
            lecture_id=session.lecture.id,
            client_id=session.client_id,
            external_user_id=session.external_user_id,
            tier_override=session.tier_override,
            version=session.version,
            active_intervention_id=session.active_intervention_id,
            active_intervention_tier=session.active_intervention_tier,
            interventions_state=interventions_state,
            completed_submissions=completed_json,
        )

    def _get_or_load_session(self, session_id: str) -> RuntimeSession:
        if session_id in self._sessions:
            return self._sessions[session_id]

        data = self.db.load_session(session_id)
        if not data:
            raise SessionError(f"Session '{session_id}' not found.", status_code=404)

        lecture = self.lecture_service.get_lecture(data["lecture_id"])
        if not lecture:
            raise SessionError(f"Lecture '{data['lecture_id']}' not found.", status_code=404)

        session = RuntimeSession(
            session_id=data["session_id"],
            lecture=lecture,
            client_id=data["client_id"],
            external_user_id=data["external_user_id"],
            tier_override=data["tier_override"],
        )
        session.version = data["version"]
        session.active_intervention_id = data["active_intervention_id"]
        session.active_intervention_tier = data["active_intervention_tier"]
        session.interventions_state = {
            k: InterventionStateEnum(v) for k, v in data["interventions_state"].items()
        }
        for k, v in data["completed_submissions"].items():
            session.completed_submissions[k] = EvaluationResult.model_validate_json(v)

        self._sessions[session_id] = session
        return session

    def create_session(
        self,
        lecture_id: str,
        client_id: str = "default_client",
        external_user_id: str = "default_learner",
        tier_override: int | None = None,
    ) -> SessionState:
        lecture = self.lecture_service.get_lecture(lecture_id)
        if not lecture:
            raise SessionError(f"Lecture '{lecture_id}' not found.", status_code=404)

        session_id = str(uuid.uuid4())
        session = RuntimeSession(
            session_id=session_id,
            lecture=lecture,
            client_id=client_id,
            external_user_id=external_user_id,
            tier_override=tier_override,
        )
        self._sessions[session_id] = session
        self._persist_session(session)
        return session.get_state()

    def get_session(self, session_id: str) -> SessionState:
        session = self._get_or_load_session(session_id)
        return session.get_state()

    def sync_playback(self, session_id: str, playback_position: float) -> SessionState:
        session = self._get_or_load_session(session_id)

        changed = False
        tolerance = session.lecture.timing_config.tolerance

        # If no intervention is ACTIVE, check for bypassed pending interventions
        if session.active_intervention_id is None:
            for intv in session.lecture.interventions:
                state = session.interventions_state[intv.id]
                policy = getattr(intv, "policy", InterventionPolicy.SKIPPABLE)
                if state == InterventionStateEnum.PENDING:
                    window_end = intv.trigger_time + tolerance
                    if playback_position > window_end:
                        if policy == InterventionPolicy.SKIPPABLE:
                            session.interventions_state[intv.id] = InterventionStateEnum.BYPASSED
                            changed = True
                        else:
                            # REQUIRED checkpoint cannot be bypassed via forward seek
                            raise SessionError(
                                f"Cannot seek past required intervention '{intv.id}'. Completion is mandatory.",
                                status_code=403,
                            )

        if changed:
            session.version += 1
            self._persist_session(session)

        return session.get_state()

    def skip_intervention(
        self, session_id: str, intervention_id: str, reason: str = "learner_choice"
    ) -> SessionState:
        """Explicitly skip an intervention per SPEC.md §55.3.
        
        Requires policy to be SKIPPABLE. Mastery is unchanged (ΔM = 0) and logged as missing evidence.
        """
        session = self._get_or_load_session(session_id)

        target_intv = next(
            (i for i in session.lecture.interventions if i.id == intervention_id), None
        )
        if not target_intv:
            raise SessionError(f"Intervention '{intervention_id}' not found.", status_code=404)

        policy = getattr(target_intv, "policy", InterventionPolicy.SKIPPABLE)
        if policy in (InterventionPolicy.REQUIRED, InterventionPolicy.REQUIRED_WITH_RETRY):
            raise SessionError(
                f"Intervention '{intervention_id}' has policy '{policy.value}' and cannot be skipped.",
                status_code=403,
            )

        current_state = session.interventions_state[target_intv.id]
        if current_state in (
            InterventionStateEnum.COMPLETED,
            InterventionStateEnum.BYPASSED,
            InterventionStateEnum.SKIPPED,
        ):
            raise SessionError(
                f"Intervention '{intervention_id}' is already in terminal state '{current_state.value}'.",
                status_code=409,
            )

        # Transition state to SKIPPED
        session.interventions_state[target_intv.id] = InterventionStateEnum.SKIPPED
        if session.active_intervention_id == target_intv.id:
            session.active_intervention_id = None
        session.version += 1

        # Record skip as missing evidence in learner service
        learner_svc = get_learner_service(self.db)
        learner_svc.record_skip(
            client_id=session.client_id,
            user_id=session.external_user_id,
            session_id=session.session_id,
            intervention_id=target_intv.id,
            concept=target_intv.concept,
        )

        self._persist_session(session)
        return session.get_state()

    def activate_intervention(
        self, session_id: str, intervention_id: str, playback_position: float
    ) -> ActiveInterventionPayload:
        session = self._get_or_load_session(session_id)

        target_intv = next(
            (i for i in session.lecture.interventions if i.id == intervention_id), None
        )
        if not target_intv:
            raise SessionError(f"Intervention '{intervention_id}' not found.", status_code=404)

        current_state = session.interventions_state[target_intv.id]

        # Re-activation / idempotent retry if already active
        if session.active_intervention_id == target_intv.id and current_state == InterventionStateEnum.ACTIVE:
            return self._build_active_payload(session, target_intv)

        # Reject if another intervention is active
        if session.active_intervention_id is not None:
            raise SessionError(
                f"Cannot activate intervention '{intervention_id}': intervention '{session.active_intervention_id}' is currently ACTIVE.",
                status_code=409,
            )

        # Reject if state is terminal (COMPLETED, BYPASSED, or SKIPPED)
        if current_state in (
            InterventionStateEnum.COMPLETED,
            InterventionStateEnum.BYPASSED,
            InterventionStateEnum.SKIPPED,
        ):
            raise SessionError(
                f"Intervention '{intervention_id}' is already in terminal state '{current_state.value}'.",
                status_code=409,
            )

        tolerance = session.lecture.timing_config.tolerance
        window_start = target_intv.trigger_time - tolerance
        window_end = target_intv.trigger_time + tolerance

        if not (window_start <= playback_position <= window_end):
            raise SessionError(
                f"Playback position {playback_position:.2f} is outside trigger window [{window_start:.2f}, {window_end:.2f}] for intervention '{intervention_id}'.",
                status_code=400,
            )

        # Transition any prior pending interventions past window_end to BYPASSED (if skippable)
        for intv in session.lecture.interventions:
            if intv.id == target_intv.id:
                break
            if session.interventions_state[intv.id] == InterventionStateEnum.PENDING:
                if playback_position > (intv.trigger_time + tolerance):
                    if getattr(intv, "policy", InterventionPolicy.SKIPPABLE) == InterventionPolicy.SKIPPABLE:
                        session.interventions_state[intv.id] = InterventionStateEnum.BYPASSED

        # Resolve tier dynamically
        learner_svc = get_learner_service(self.db)
        profile = learner_svc.get_or_create_profile(session.client_id, session.external_user_id)
        resolved_tier = learner_svc.resolve_intervention_tier(
            profile, target_intv.concept, session.tier_override
        )
        session.active_intervention_tier = resolved_tier

        # Transition target to ACTIVE
        session.interventions_state[target_intv.id] = InterventionStateEnum.ACTIVE
        session.active_intervention_id = target_intv.id
        session.version += 1

        self._persist_session(session)
        return self._build_active_payload(session, target_intv)

    def submit_answer(
        self,
        session_id: str,
        intervention_id: str,
        idempotency_key: str,
        answer: str | list[str],
    ) -> EvaluationResult:
        session = self._get_or_load_session(session_id)

        # Idempotency check: return previous result if key already processed
        if idempotency_key in session.completed_submissions:
            return session.completed_submissions[idempotency_key]

        target_intv = next(
            (i for i in session.lecture.interventions if i.id == intervention_id), None
        )
        if not target_intv:
            raise SessionError(f"Intervention '{intervention_id}' not found.", status_code=404)

        if (
            session.active_intervention_id != intervention_id
            or session.interventions_state[intervention_id] != InterventionStateEnum.ACTIVE
        ):
            raise SessionError(
                f"Intervention '{intervention_id}' is not currently ACTIVE.",
                status_code=409,
            )

        tier = session.active_intervention_tier
        variant = target_intv.variants.get(tier) if getattr(target_intv, "variants", None) else None

        # Deterministic evaluation
        is_correct = False
        if target_intv.type == InterventionType.SINGLE_CHOICE:
            if not isinstance(answer, str):
                raise SessionError("Single choice submission must be a string answer ID.")
            correct = variant.correct_answer if (variant and variant.correct_answer) else target_intv.correct_answer
            is_correct = answer == correct
        elif target_intv.type == InterventionType.MULTIPLE_SELECTION:
            if not isinstance(answer, list) or len(answer) == 0:
                raise SessionError("Multiple selection submission must be a non-empty list of answer IDs.")
            correct = variant.correct_answer if (variant and variant.correct_answer) else target_intv.correct_answer
            expected_set = set(correct) if isinstance(correct, list) else {correct}  # type: ignore
            submitted_set = set(answer)
            is_correct = submitted_set == expected_set
        elif target_intv.type in (InterventionType.PREDICT_AND_VERIFY, InterventionType.INQUIRY_SANDBOX):
            correct = variant.correct_answer if (variant and variant.correct_answer) else target_intv.correct_answer
            if correct:
                if isinstance(correct, list):
                    is_correct = set(answer if isinstance(answer, list) else [answer]) == set(correct)
                else:
                    is_correct = str(answer).strip() == str(correct).strip()
            else:
                is_correct = True

        correct_fb = variant.correct_feedback if (variant and variant.correct_feedback) else target_intv.correct_feedback
        incorrect_fb = variant.incorrect_feedback if (variant and variant.incorrect_feedback) else target_intv.incorrect_feedback
        feedback = correct_fb if is_correct else incorrect_fb

        # Record in learner service
        learner_svc = get_learner_service(self.db)
        mastery_delta, next_tier = learner_svc.record_attempt(
            session.client_id,
            session.external_user_id,
            target_intv.concept,
            is_correct,
            tier,
        )

        # Transition state ACTIVE -> COMPLETED
        session.interventions_state[intervention_id] = InterventionStateEnum.COMPLETED
        session.active_intervention_id = None
        session.version += 1

        result = EvaluationResult(
            is_correct=is_correct,
            feedback=feedback,
            submitted_answer=answer,
            session_state=session.get_state(),
            tier=tier,
            mastery_delta=mastery_delta,
            suggested_next_tier=next_tier,
        )

        # Store for idempotency
        session.completed_submissions[idempotency_key] = result
        self._persist_session(session)
        return result

    def submit_experiment(
        self,
        session_id: str,
        submission: InquiryExperimentSubmission,
    ) -> EvaluationResult:
        session = self._get_or_load_session(session_id)

        if submission.idempotency_key in session.completed_submissions:
            return session.completed_submissions[submission.idempotency_key]

        intervention_id = submission.intervention_id
        target_intv = next(
            (i for i in session.lecture.interventions if i.id == intervention_id), None
        )
        if not target_intv:
            raise SessionError(f"Intervention '{intervention_id}' not found.", status_code=404)

        if (
            session.active_intervention_id != intervention_id
            or session.interventions_state[intervention_id] != InterventionStateEnum.ACTIVE
        ):
            raise SessionError(
                f"Intervention '{intervention_id}' is not currently ACTIVE.",
                status_code=409,
            )

        tier = session.active_intervention_tier
        variant = target_intv.variants.get(tier) if getattr(target_intv, "variants", None) else None

        is_correct = submission.passed_tests

        correct_fb = variant.correct_feedback if (variant and variant.correct_feedback) else target_intv.correct_feedback
        incorrect_fb = variant.incorrect_feedback if (variant and variant.incorrect_feedback) else target_intv.incorrect_feedback
        feedback = correct_fb if is_correct else incorrect_fb

        learner_svc = get_learner_service(self.db)
        mastery_delta, next_tier = learner_svc.record_attempt(
            session.client_id,
            session.external_user_id,
            target_intv.concept,
            is_correct,
            tier,
        )

        session.interventions_state[intervention_id] = InterventionStateEnum.COMPLETED
        session.active_intervention_id = None
        session.version += 1

        result = EvaluationResult(
            is_correct=is_correct,
            feedback=feedback,
            submitted_answer=submission.code_submitted or str(submission.hypothesis_answer or ""),
            session_state=session.get_state(),
            tier=tier,
            mastery_delta=mastery_delta,
            suggested_next_tier=next_tier,
        )
        session.completed_submissions[submission.idempotency_key] = result
        self._persist_session(session)
        return result

    def _build_active_payload(
        self, session: RuntimeSession, intervention: Any
    ) -> ActiveInterventionPayload:
        tier = session.active_intervention_tier
        variant = intervention.variants.get(tier) if getattr(intervention, "variants", None) else None

        question = variant.prompt if variant else intervention.question
        hypothesis_prompt = (
            variant.hypothesis_prompt
            if variant and variant.hypothesis_prompt
            else getattr(intervention, "hypothesis_prompt", None)
        )
        hypothesis_options = []
        raw_hyp_opts = (
            variant.hypothesis_options
            if variant and variant.hypothesis_options
            else getattr(intervention, "hypothesis_options", [])
        )
        if raw_hyp_opts:
            hypothesis_options = [opt.model_dump() for opt in raw_hyp_opts]

        options = []
        if getattr(intervention, "options", None):
            options = [opt.model_dump() for opt in intervention.options]

        sandbox_config_obj = (
            variant.sandbox_config
            if variant and variant.sandbox_config
            else getattr(intervention, "sandbox_config", None)
        )
        sandbox_config = sandbox_config_obj.model_dump() if sandbox_config_obj else None

        rubric_dict = None
        if getattr(intervention, "rubric", None):
            rubric_dict = intervention.rubric.model_dump()

        return ActiveInterventionPayload(
            id=intervention.id,
            trigger_time=intervention.trigger_time,
            concept=intervention.concept,
            difficulty=intervention.difficulty.value,
            type=intervention.type.value,
            question=question,
            options=options,
            session_state=session.get_state(),
            tier=tier,
            hypothesis_prompt=hypothesis_prompt,
            hypothesis_options=hypothesis_options,
            sandbox_config=sandbox_config,
            policy=getattr(intervention, "policy", InterventionPolicy.SKIPPABLE),
            resumption_policy=getattr(intervention, "resumption_policy", ResumptionPolicy.IMMEDIATE_OPTIMISTIC),
            rubric=rubric_dict,
        )

    def record_evaluation_completed(self, session_id: str, intervention_id: str) -> None:
        """Mark intervention COMPLETED when async AI evaluation completes."""
        session = self._get_or_load_session(session_id)
        if session.interventions_state.get(intervention_id) == InterventionStateEnum.EVALUATING:
            session.interventions_state[intervention_id] = InterventionStateEnum.COMPLETED
            if session.active_intervention_id == intervention_id:
                session.active_intervention_id = None
            session.version += 1
            self._persist_session(session)

    def record_self_assessment(self, session_id: str, intervention_id: str) -> SessionState:
        """Transition intervention to COMPLETED after learner self-assesses timed-out rubric."""
        session = self._get_or_load_session(session_id)
        session.interventions_state[intervention_id] = InterventionStateEnum.COMPLETED
        if session.active_intervention_id == intervention_id:
            session.active_intervention_id = None
        session.version += 1
        self._persist_session(session)
        return session.get_state()



_session_service_instance: SessionService | None = None


def get_session_service(
    lecture_service: LectureService | None = None,
    db: Database | None = None,
) -> SessionService:
    global _session_service_instance
    if _session_service_instance is None:
        _session_service_instance = SessionService(lecture_service=lecture_service, db=db)
    return _session_service_instance

