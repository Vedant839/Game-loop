import asyncio
import logging
from datetime import datetime, timezone
import uuid
from typing import Any
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import aiofiles
import math
import time

from backend.config import get_settings
from backend.auth import require_creator
from backend.database import DatabaseUnavailableError, get_database
from backend.lecture_sanitizer import sanitize_student_lecture
from backend.schemas.lecture import Intervention, Lecture, LectureSummary, ResumptionPolicy, TimingConfig
from backend.schemas.ingest import IngestLectureRequest, PreflightRequest
from backend.services.transcript_quality import PreflightReport, analyze_transcript_quality
from backend.schemas.session import (
    ActivateInterventionRequest,
    ActiveInterventionPayload,
    CreateSessionRequest,
    EvaluationResult,
    HintRequest,
    InquiryExperimentSubmission,
    InterventionStateEnum,
    LearnerProfile,
    OpenEndedSubmissionRequest,
    OpenEndedSubmissionResponse,
    SelfAssessRequest,
    SessionState,
    SkipInterventionRequest,
    SubmissionStatus,
    SubmissionStatusResponse,
    SubmitAnswerRequest,
    SyncPlaybackRequest,
    TabEventRequest,
    TabEventResponse,
)
from backend.services.lecture_service import get_lecture_service
from backend.services.gemini_client import GeminiClient, GeminiQuotaExceeded
from backend.services.ingest_pipeline import PipelineFailure, run_understanding_pipeline
from backend.services.checkpoint_generator import MIN_CHECKPOINT_GAP_SECONDS
from backend.utils.captions import CaptionParseError, TranscriptValidationError, parse_srt, parse_vtt
from backend.services.session_service import SessionError, get_session_service
from backend.services.learner_service import get_learner_service
from backend.services.evaluator_service import get_evaluator_service
from backend.rate_limit import (
    get_creator_rate_limit_key,
    get_real_client_ip,
    limiter,
)

settings = get_settings()
logger = logging.getLogger(__name__)


app = FastAPI(title="game-loop API", version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


def get_gemini_client() -> GeminiClient:
    """Dependency boundary so authoring tests can install a fake provider."""
    return GeminiClient(db=get_database(), settings=settings)


@app.exception_handler(DatabaseUnavailableError)
async def database_unavailable_handler(
    _request: Request, _exc: DatabaseUnavailableError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database temporarily unavailable"},
    )


@app.get("/api/health")
def get_health() -> dict[str, str]:
    """Return a small stable response for frontend connectivity checks."""
    return {"status": "ok"}


@app.post("/api/lectures", response_model=Lecture, status_code=status.HTTP_201_CREATED)
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def create_lecture(
    request: Request,
    lecture: Lecture,
    _creator: dict[str, str] = Depends(require_creator),
) -> Lecture:
    """Create a custom lecture definition and persist it to the repository."""
    if lecture.id == "math_sample_lecture":
        raise HTTPException(
            status_code=400,
            detail="The sample lecture ID is reserved; choose a custom lecture ID.",
        )
    video_url = lecture.video_url.lower()
    source_type = (
        "youtube" if "youtube.com/" in video_url or "youtu.be/" in video_url
        else "vimeo" if "vimeo.com/" in video_url
        else "direct"
    )
    _creator_id = _creator["creator_id"]
    get_database().lectures.save_lecture(
        lecture_id=lecture.id,
        creator_id=_creator_id,
        title=lecture.id,
        video_url=lecture.video_url,
        source_type=source_type,
        content_json=lecture.model_dump_json(),
    )
    return lecture


@app.post("/api/creator/ingest/preflight", response_model=PreflightReport)
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def preflight_transcript_quality(
    request: Request,
    payload: PreflightRequest,
    creator: dict[str, str] = Depends(require_creator),
) -> PreflightReport:
    """Analyze caption timing and word density deterministically without external calls."""
    segments: list[dict[str, Any]] = []
    plain_text: str | None = None

    if payload.transcript:
        segments = payload.transcript
    elif payload.captions and payload.captions.strip():
        if payload.captions_format == "srt":
            try:
                segments = [seg.model_dump() for seg in parse_srt(payload.captions)]
            except Exception:
                plain_text = payload.captions
        elif payload.captions_format == "vtt":
            try:
                segments = [seg.model_dump() for seg in parse_vtt(payload.captions)]
            except Exception:
                plain_text = payload.captions
        else:
            plain_text = payload.captions

    return analyze_transcript_quality(
        segments=segments if segments else None,
        duration_seconds=payload.duration_seconds,
        plain_text=plain_text,
    )


@app.post("/api/creator/ingest", response_model=Lecture, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute", key_func=get_creator_rate_limit_key)
def ingest_lecture(
    request: Request,
    payload: IngestLectureRequest,
    response: Response,
    creator: dict[str, str] = Depends(require_creator),
    gemini_client: GeminiClient = Depends(get_gemini_client),
) -> Lecture:
    """Parse uploaded captions, author checkpoints, and save a creator lecture."""
    started_at = time.perf_counter()
    try:
        if payload.captions_format == "srt":
            transcript = parse_srt(payload.captions)
        elif payload.captions_format == "vtt":
            transcript = parse_vtt(payload.captions)
        elif payload.captions.strip():
            from backend.schemas.lecture import TranscriptSegment

            lines = [line.strip() for line in payload.captions.splitlines() if line.strip()]
            width = payload.duration_seconds / max(len(lines), 1)
            transcript = [
                TranscriptSegment(start_time=i * width, end_time=(i + 1) * width, text=line)
                for i, line in enumerate(lines)
            ]
        else:
            transcript = []
    except (CaptionParseError, TranscriptValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    lecture_id = "ingest_" + uuid.uuid4().hex[:12]
    lecture = Lecture(
        id=lecture_id,
        duration_seconds=payload.duration_seconds,
        video_url=payload.video_url,
        transcript=transcript,
        timing_config=TimingConfig(min_trigger_gap=MIN_CHECKPOINT_GAP_SECONDS, tolerance=2.0),
        interventions=[],
    )
    api_key = (request.headers.get("X-Gemini-Key") or "").strip()
    creator_supplied_key = bool(api_key)
    if not api_key and settings.gemini_api_key is not None:
        api_key = settings.gemini_api_key.get_secret_value()
    try:
        lecture = run_understanding_pipeline(
            lecture,
            intensity=payload.intensity,
            api_key=api_key,
            creator_id=creator["creator_id"],
            gemini_client=gemini_client,
            enforce_monthly_cap=not creator_supplied_key,
            creator_context=payload.creator_context.model_dump(mode="json") if payload.creator_context else None,
            visual_evidence=payload.visual_evidence,
        )
        response.headers["X-Generation-Mode"] = "concept_v2"
    except GeminiQuotaExceeded:
        raise HTTPException(status_code=429, detail="Monthly Gemini token cap reached") from None
    except PipelineFailure as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "understanding_unavailable", "analysis_report": exc.analysis_report},
        ) from None
    except Exception as exc:
        # Do not include provider exception details; they may contain prompt or key data.
        logger.warning("Understanding pipeline failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "understanding_unavailable", "analysis_report": lecture.analysis_report},
        ) from None

    video_url_lower = lecture.video_url.lower()
    source_type = (
        "youtube" if "youtube.com/" in video_url_lower or "youtu.be/" in video_url_lower
        else "vimeo" if "vimeo.com/" in video_url_lower
        else "direct"
    )
    get_database().lectures.save_lecture(
        lecture_id=lecture.id,
        creator_id=creator["creator_id"],
        title=lecture.id,
        video_url=lecture.video_url,
        source_type=source_type,
        content_json=lecture.model_dump_json(),
    )
    try:
        get_database().record_telemetry(
            client_id=creator["creator_id"],
            session_id=f"ingest_{lecture.id}",
            user_id=creator["creator_id"],
            event_type="lecture_ingestion_completed",
            payload={"duration_ms": round((time.perf_counter() - started_at) * 1000), "intensity": payload.intensity},
        )
    except Exception:
        # Telemetry must not make an otherwise successful ingestion fail.
        pass
    return lecture


@app.get("/api/lectures", response_model=list[LectureSummary])
def list_lectures() -> list[LectureSummary]:
    """List available lectures."""
    service = get_lecture_service()
    return service.list_lectures()


@app.get("/api/lectures/{lecture_id}")
def get_lecture(lecture_id: str) -> dict[str, Any]:
    """Return the student-safe lecture view by ID."""
    try:
        stored = get_database().lectures.get_lecture(lecture_id)
        if stored and stored.get("content"):
            content_data = json.loads(stored["content"])
            return sanitize_student_lecture(content_data)
    except Exception:
        pass
    service = get_lecture_service()
    lecture = service.get_lecture(lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")
    return sanitize_student_lecture(lecture.model_dump(mode="json"))


@app.get("/api/sessions/{session_id}/lecture")
def get_session_lecture(session_id: str) -> dict[str, Any]:
    """Return the sanitized lecture attached to a valid session capability."""
    session_service = get_session_service()
    try:
        session = session_service._get_or_load_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return sanitize_student_lecture(session.lecture.model_dump(mode="json"))


@app.post("/api/sessions/{session_id}/hint")
def request_session_hint(session_id: str, req: HintRequest) -> dict[str, str]:
    """Return a hint only when the server has recorded an attempt."""
    try:
        hint = get_session_service().request_hint(session_id, req.intervention_id)
    except SessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"hint": hint}


@app.get("/api/studio/lectures/{lecture_id}", response_model=Lecture)
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def get_studio_lecture(
    request: Request,
    lecture_id: str,
    creator: dict[str, str] = Depends(require_creator),
) -> Lecture:
    """Return the full lecture to an authenticated creator."""
    stored = get_database().lectures.get_lecture(lecture_id)
    if stored is not None:
        if stored["creator_id"] != creator["creator_id"]:
            raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")
        try:
            return Lecture.model_validate_json(stored["content"])
        except ValueError:
            raise HTTPException(status_code=500, detail="Stored lecture is invalid") from None

    # Bundled seed lectures belong to the canonical creator until backfilled.
    if creator["creator_id"] != "default_client":
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")
    lecture = get_lecture_service().get_lecture(lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")
    return lecture


@app.post("/api/studio/lectures/{lecture_id}/checkpoints/{intervention_id}/approve")
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def approve_checkpoint(
    request: Request,
    lecture_id: str,
    intervention_id: str,
    creator: dict[str, str] = Depends(require_creator),
) -> dict[str, Any]:
    """Approve a flagged checkpoint without changing its revision (§7.3.7)."""
    db = get_database()
    stored = db.lectures.get_lecture(lecture_id)
    if not stored or stored["creator_id"] != creator["creator_id"]:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")

    lecture = Lecture.model_validate_json(stored["content"])
    found = False
    target_intv = None
    for intv in lecture.interventions:
        if intv.id == intervention_id:
            intv.review_state = "approved"
            target_intv = intv
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{intervention_id}' not found.")

    db.lectures.save_lecture(
        lecture_id=lecture.id,
        creator_id=creator["creator_id"],
        title=stored.get("title", lecture.id),
        video_url=lecture.video_url,
        source_type=stored.get("source_type", "direct"),
        content_json=lecture.model_dump_json(),
    )
    return {"status": "approved", "intervention": target_intv.model_dump(mode="json")}


@app.post("/api/studio/lectures/{lecture_id}/approve_flagged")
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def approve_all_flagged_checkpoints(
    request: Request,
    lecture_id: str,
    creator: dict[str, str] = Depends(require_creator),
) -> dict[str, Any]:
    """Approve all checkpoints with review_state == 'needs_review' (§7.3.7)."""
    db = get_database()
    stored = db.lectures.get_lecture(lecture_id)
    if not stored or stored["creator_id"] != creator["creator_id"]:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")

    lecture = Lecture.model_validate_json(stored["content"])
    approved_count = 0
    for intv in lecture.interventions:
        if getattr(intv, "review_state", "auto") == "needs_review":
            intv.review_state = "approved"
            approved_count += 1

    if approved_count > 0:
        db.lectures.save_lecture(
            lecture_id=lecture.id,
            creator_id=creator["creator_id"],
            title=stored.get("title", lecture.id),
            video_url=lecture.video_url,
            source_type=stored.get("source_type", "direct"),
            content_json=lecture.model_dump_json(),
        )

    return {"approved_count": approved_count}


@app.put("/api/studio/lectures/{lecture_id}/checkpoints/{intervention_id}")
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def edit_checkpoint(
    request: Request,
    lecture_id: str,
    intervention_id: str,
    payload: dict[str, Any],
    creator: dict[str, str] = Depends(require_creator),
) -> dict[str, Any]:
    """Edit a checkpoint: sets review_state to 'approved' and increments revision (§7.2, §7.3.7)."""
    db = get_database()
    stored = db.lectures.get_lecture(lecture_id)
    if not stored or stored["creator_id"] != creator["creator_id"]:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")

    lecture = Lecture.model_validate_json(stored["content"])
    found = False
    target_intv = None
    for idx, intv in enumerate(lecture.interventions):
        if intv.id == intervention_id:
            data = intv.model_dump(mode="json")
            for key in ("question", "trigger_time", "options", "hints", "correct_answer", "policy", "concept"):
                if key in payload:
                    data[key] = payload[key]
            data["revision"] = data.get("revision", 1) + 1
            data["review_state"] = "approved"
            updated = Intervention.model_validate(data)
            lecture.interventions[idx] = updated
            target_intv = updated
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Checkpoint '{intervention_id}' not found.")

    db.lectures.save_lecture(
        lecture_id=lecture.id,
        creator_id=creator["creator_id"],
        title=stored.get("title", lecture.id),
        video_url=lecture.video_url,
        source_type=stored.get("source_type", "direct"),
        content_json=lecture.model_dump_json(),
    )
    return {"status": "updated", "intervention": target_intv.model_dump(mode="json")}


@app.post("/api/sessions", response_model=SessionState, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute", key_func=get_real_client_ip)
def create_session(request: Request, req: CreateSessionRequest) -> SessionState:
    """Create a new in-memory runtime session for a lecture.

    V0.2: Accepts optional client_id, external_user_id, and tier_override for
    B2B multi-tenant learner identity and adaptive difficulty seeding.
    """
    session_service = get_session_service()
    try:
        return session_service.create_session(
            lecture_id=req.lecture_id,
            client_id=req.client_id or "default_client",
            external_user_id=req.learner_id or req.external_user_id or "default_learner",
            tier_override=req.tier_override,
        )
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.get("/api/sessions/{session_id}", response_model=SessionState)
def get_session(session_id: str) -> SessionState:
    """Get current authoritative session state."""
    session_service = get_session_service()
    try:
        return session_service.get_session(session_id)
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post("/api/sessions/{session_id}/activate", response_model=ActiveInterventionPayload)
def activate_intervention(session_id: str, req: ActivateInterventionRequest) -> ActiveInterventionPayload:
    """Attempt to activate a pending intervention at the current playback position."""
    session_service = get_session_service()
    try:
        return session_service.activate_intervention(
            session_id=session_id,
            intervention_id=req.intervention_id,
            playback_position=req.playback_position,
        )
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post("/api/sessions/{session_id}/sync", response_model=SessionState)
def sync_playback(session_id: str, req: SyncPlaybackRequest) -> SessionState:
    """Sync playback position and transition bypassed interventions if seeking past trigger windows."""
    session_service = get_session_service()
    try:
        return session_service.sync_playback(
            session_id=session_id, playback_position=req.playback_position
        )
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post("/api/sessions/{session_id}/tab_event", response_model=TabEventResponse)
@limiter.limit("30/minute", key_func=get_real_client_ip)
def session_tab_event(
    request: Request, session_id: str, req: TabEventRequest
) -> TabEventResponse:
    """Offer a sanitized recall card after more than 60 seconds away."""
    try:
        return TabEventResponse(**get_session_service().tab_event(session_id, req.away_seconds))
    except SessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None


@app.post("/api/sessions/{session_id}/submit", response_model=EvaluationResult)
@limiter.limit("60/minute", key_func=get_real_client_ip)
def submit_answer(
    request: Request, session_id: str, req: SubmitAnswerRequest
) -> EvaluationResult:
    """Submit answer for active intervention and receive deterministic evaluation result."""
    session_service = get_session_service()
    try:
        return session_service.submit_answer(
            session_id=session_id,
            intervention_id=req.intervention_id,
            idempotency_key=req.idempotency_key,
            answer=req.answer,
        )
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post("/api/sessions/{session_id}/experiment", response_model=EvaluationResult)
def submit_experiment(session_id: str, req: InquiryExperimentSubmission) -> EvaluationResult:
    """Submit results of a predict-and-verify or inquiry sandbox intervention.

    V0.2: Accepts sandbox test results and hypothesis answer from the client-side
    code runner. Updates the learner mastery profile deterministically.
    """
    session_service = get_session_service()
    try:
        return session_service.submit_experiment(session_id=session_id, submission=req)
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.get("/api/studio/sessions")
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def list_creator_sessions(
    request: Request,
    lecture_id: str | None = None,
    limit: int = 100,
    creator: dict[str, str] = Depends(require_creator),
) -> list[dict[str, Any]]:
    """List session identifiers belonging to the authenticated creator."""
    return get_database().sessions.list_sessions_by_creator(
        creator["creator_id"], lecture_id=lecture_id, limit=limit
    )


@app.get("/api/learners/{client_id}/{user_id}", response_model=LearnerProfile)
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def get_learner_profile(
    request: Request,
    client_id: str,
    user_id: str,
    creator: dict[str, str] = Depends(require_creator),
) -> LearnerProfile:
    """Retrieve the current learner mastery profile for a B2B client's user."""
    if client_id != creator["creator_id"]:
        raise HTTPException(status_code=403, detail="Creator cannot access another tenant")
    learner_service = get_learner_service()
    return learner_service.get_or_create_profile(client_id, user_id)


# ---------------------------------------------------------------------------
# V0.3 Endpoints: Skip, Open-Ended Semantic Grading, and B2B Telemetry
# ---------------------------------------------------------------------------


@app.post(
    "/api/sessions/{session_id}/interventions/{intervention_id}/skip",
    response_model=SessionState,
)
def skip_intervention(
    session_id: str, intervention_id: str, background_tasks: BackgroundTasks,
    req: SkipInterventionRequest | None = None
) -> SessionState:
    """Explicitly skip an intervention if permitted by policy."""
    session_service = get_session_service()
    reason = req.reason if req and req.reason else "learner_choice"
    try:
        state = session_service.skip_intervention(
            session_id, intervention_id, reason=reason, write_telemetry=False
        )
        session = session_service._get_or_load_session(session_id)
        intervention = next(i for i in session.lecture.interventions if i.id == intervention_id)
        def record_skip_telemetry() -> None:
            db = get_database()
            profile = get_learner_service(db).get_or_create_profile(
                session.client_id, session.external_user_id
            )
            db.record_telemetry(
                client_id=session.client_id, session_id=session_id,
                user_id=session.external_user_id, event_type="intervention_skipped",
                payload={"intervention_id": intervention_id, "concept": intervention.concept,
                         "missing_evidence": True,
                         "current_mastery": profile.concept_mastery.get(intervention.concept, 0.5)},
            )
        background_tasks.add_task(record_skip_telemetry)
        return state
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.post(
    "/api/sessions/{session_id}/submissions/open-ended",
    response_model=OpenEndedSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("60/minute", key_func=get_real_client_ip)
def submit_open_ended(
    request: Request,
    session_id: str,
    req: OpenEndedSubmissionRequest,
    background_tasks: BackgroundTasks,
) -> OpenEndedSubmissionResponse:
    """Submit open-ended freeform answer for asynchronous AI evaluation."""
    session_service = get_session_service()
    evaluator_service = get_evaluator_service()
    db = get_database()

    try:
        session = session_service._get_or_load_session(session_id)
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    intervention_id = req.intervention_id
    target_intv = next((i for i in session.lecture.interventions if i.id == intervention_id), None)
    if not target_intv:
        raise HTTPException(status_code=404, detail=f"Intervention '{intervention_id}' not found.")

    if (
        session.active_intervention_id != intervention_id
        or session.interventions_state[intervention_id] != InterventionStateEnum.ACTIVE
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Intervention '{intervention_id}' is not currently ACTIVE.",
        )

    # Idempotency check: see if submission with idempotency_key already exists
    existing_row = db.submissions.get_by_idempotency_key(session_id, req.idempotency_key)
    if existing_row:
        submission_id = existing_row["submission_id"]
        return OpenEndedSubmissionResponse(
            submission_id=submission_id,
            status=SubmissionStatus.PENDING,
            resumption_policy=getattr(target_intv, "resumption_policy", ResumptionPolicy.IMMEDIATE_OPTIMISTIC),
            message="Submission already in progress.",
            session_state=session.get_state(),
        )

    submission_id = str(uuid.uuid4())
    tier = session.active_intervention_tier
    resumption_policy = getattr(target_intv, "resumption_policy", ResumptionPolicy.IMMEDIATE_OPTIMISTIC)

    # Transition state to EVALUATING
    session.interventions_state[intervention_id] = InterventionStateEnum.EVALUATING
    session.attempt_counts[intervention_id] = session.attempt_counts.get(intervention_id, 0) + 1
    if resumption_policy == ResumptionPolicy.IMMEDIATE_OPTIMISTIC:
        # Optimistic resume: unlock video playhead
        session.active_intervention_id = None
    session.version += 1
    rubric_dict = target_intv.rubric.model_dump() if getattr(target_intv, "rubric", None) else None

    # Persist the session transition and pending submission in one atomic batch.
    session_service._persist_session(
        session,
        intervention_ids={intervention_id},
        pending_submission={
            "submission_id": submission_id,
            "session_id": session_id,
            "intervention_id": intervention_id,
            "idempotency_key": req.idempotency_key,
            "user_answer": req.user_answer,
            "status": SubmissionStatus.PENDING.value,
            "resumption_policy": resumption_policy.value,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # Dispatch async background task
    def evaluate_in_worker() -> None:
        asyncio.run(evaluator_service.evaluate_submission_async(
            submission_id=submission_id,
            session_id=session_id,
            intervention_id=intervention_id,
            question=target_intv.question,
            user_answer=req.user_answer,
            rubric=rubric_dict,
            client_id=session.client_id,
            user_id=session.external_user_id,
            concept=target_intv.concept,
            tier=tier,
            lecture_id=session.lecture.id,
        ))

    background_tasks.add_task(evaluate_in_worker)

    return OpenEndedSubmissionResponse(
        submission_id=submission_id,
        status=SubmissionStatus.PENDING,
        resumption_policy=resumption_policy,
        message="Answer received. Evaluating asynchronously.",
        session_state=session.get_state(),
    )


@app.get(
    "/api/sessions/{session_id}/submissions/{submission_id}",
    response_model=SubmissionStatusResponse,
)
def get_submission_status(session_id: str, submission_id: str) -> SubmissionStatusResponse:
    """Check asynchronous evaluation status."""
    db = get_database()
    sub = db.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail=f"Submission '{submission_id}' not found.")

    if sub["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Submission not found for this session.")

    session_service = get_session_service()
    try:
        session_service._get_or_load_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc

    status_val = SubmissionStatus(sub["status"])

    # Check for foreground timeout (5.0s threshold)
    created_dt = datetime.fromisoformat(sub["created_at"])
    now_dt = datetime.now(timezone.utc)
    elapsed = (now_dt - created_dt).total_seconds()

    if status_val == SubmissionStatus.PENDING and elapsed > 5.0:
        status_val = SubmissionStatus.TIMED_OUT

    return SubmissionStatusResponse(
        submission_id=sub["submission_id"],
        status=status_val,
        ai_score=sub["ai_score"],
        is_correct=sub["is_correct"],
        formative_feedback=sub["formative_feedback"],
        misconceptions_detected=sub["misconceptions"],
        self_assessed=sub["self_assessed"],
        evaluation_latency_ms=sub["latency_ms"],
    )


@app.post(
    "/api/sessions/{session_id}/submissions/{submission_id}/self-assess",
    response_model=SessionState,
)
def self_assess_submission(
    session_id: str, submission_id: str, req: SelfAssessRequest
) -> SessionState:
    """Self-assess timed-out submission using reference rubric."""
    evaluator_service = get_evaluator_service()
    session_service = get_session_service()
    try:
        updated_dict = evaluator_service.self_assess_submission(
            submission_id=submission_id,
            session_id=session_id,
            self_assessed_correct=req.self_assessed_correct,
        )
        return SessionState.model_validate(updated_dict)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/telemetry")
@limiter.limit("120/minute", key_func=get_creator_rate_limit_key)
def export_telemetry(
    request: Request,
    client_id: str | None = None,
    limit: int = 100,
    creator: dict[str, str] = Depends(require_creator),
) -> list[dict[str, Any]]:
    """Export structured telemetry events for B2B LMS integration."""
    if client_id is not None and client_id != creator["creator_id"]:
        raise HTTPException(status_code=403, detail="Creator cannot access another tenant")
    db = get_database()
    return db.export_telemetry(client_id=creator["creator_id"], limit=limit)



if settings.env != "production":
    @app.get("/media/{file_name}")
    async def serve_media(request: Request, file_name: str):
        """Serve media files with basic HTTP Range support for browser playback.

        - If the client sends a `Range` header, respond with `206 Partial Content` and
          the requested byte range.
        - Otherwise return a normal `200` full-file response.
        This is a minimal implementation suitable for local development and testing.
        """
        media_path = settings.media_dir / file_name
        if not media_path.exists() or not media_path.is_file():
            raise HTTPException(status_code=404, detail="media not found")

        file_size = media_path.stat().st_size

        range_header = request.headers.get("range")
        if not range_header:
            return FileResponse(media_path, media_type="video/mp4")

        # Parse a single range like: bytes=START-END
        try:
            units, _, range_spec = range_header.partition("=")
            if units.strip().lower() != "bytes":
                raise ValueError("Only 'bytes' unit is supported")
            start_str, _, end_str = range_spec.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
        except Exception:
            raise HTTPException(status_code=416, detail="Invalid Range header")

        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")

        chunk_size = 1024 * 1024
        content_length = end - start + 1

        async def stream_range(path, start_pos, length):
            remaining = length
            async with aiofiles.open(path, mode="rb") as f:
                await f.seek(start_pos)
                while remaining > 0:
                    read_size = min(remaining, chunk_size)
                    data = await f.read(read_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        content_range = f"bytes {start}-{end}/{file_size}"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": content_range,
            "Content-Length": str(content_length),
        }

        return StreamingResponse(
            stream_range(str(media_path), start, content_length),
            status_code=206,
            media_type="video/mp4",
            headers=headers,
        )


    @app.head("/media/{file_name}")
    def head_media(file_name: str) -> Response:
        """Respond to HEAD requests for media files to support pre-flight metadata inspection."""
        media_path = settings.media_dir / file_name
        if not media_path.exists() or not media_path.is_file():
            raise HTTPException(status_code=404, detail="media not found")

        file_size = media_path.stat().st_size
        return Response(
            status_code=200,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

