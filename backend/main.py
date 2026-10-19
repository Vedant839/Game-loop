from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import FileResponse, Response, StreamingResponse
import aiofiles
import math

from backend.config import get_settings
from backend.schemas.lecture import Lecture, LectureSummary
from backend.schemas.session import (
    ActivateInterventionRequest,
    ActiveInterventionPayload,
    CreateSessionRequest,
    EvaluationResult,
    InquiryExperimentSubmission,
    LearnerProfile,
    SessionState,
    SubmitAnswerRequest,
    SyncPlaybackRequest,
)
from backend.services.lecture_service import get_lecture_service
from backend.services.lecture_service import _generate_for_lecture
from backend.services.gemini_authoring_service import generate_interventions_with_gemini
from backend.services.session_service import SessionError, get_session_service
from backend.services.learner_service import get_learner_service

settings = get_settings()

app = FastAPI(title="game-loop API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
def get_health() -> dict[str, str]:
    """Return a small stable response for frontend connectivity checks."""
    return {"status": "ok"}


@app.post("/api/lectures", response_model=Lecture, status_code=status.HTTP_201_CREATED)
def create_lecture(lecture: Lecture) -> Lecture:
    """Create a custom lecture definition and persist it on disk."""
    service = get_lecture_service()
    if lecture.id in {"math_sample_lecture", "physics_kinematics"}:
        raise HTTPException(
            status_code=400,
            detail="Legacy lecture IDs are reserved; choose a custom lecture ID.",
        )
    service.save_lecture(lecture)
    return lecture


@app.get("/api/lectures", response_model=list[LectureSummary])
def list_lectures() -> list[LectureSummary]:
    """List available lectures."""
    service = get_lecture_service()
    return service.list_lectures()


@app.get("/api/lectures/{lecture_id}", response_model=Lecture)
def get_lecture(lecture_id: str) -> Lecture:
    """Retrieve full validated lecture definition by ID."""
    service = get_lecture_service()
    lecture = service.get_lecture(lecture_id)
    if not lecture:
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")
    return lecture


@app.post("/api/lectures/{lecture_id}/generate_interventions", response_model=Lecture)
def generate_interventions_for_lecture(lecture_id: str, max_count: int = 4):
    """Generate interventions for a lecture, grounded in its actual transcript content.

    When a Gemini API key is configured, this calls Gemini with the full
    transcript so that the generated questions are specific to the lecture's
    subject, grade, and content (not generic placeholders).

    Falls back to a local deterministic generator when no API key is set.
    The fallback is clearly flagged in the response via the X-Generation-Mode
    response header so callers can distinguish the two paths.
    """
    service = get_lecture_service()
    lecture_path = service.lectures_dir / f"{lecture_id}.json"
    if not lecture_path.exists():
        raise HTTPException(status_code=404, detail=f"Lecture '{lecture_id}' not found.")

    canonical_lecture = service.get_lecture_by_file(lecture_path)
    generation_lecture = canonical_lecture.model_copy(deep=True)
    generation_lecture.interventions = []

    api_key = settings.gemini_api_key
    if api_key is not None:
        key_value = api_key.get_secret_value()
        if key_value:
            try:
                generated = generate_interventions_with_gemini(
                    lecture=generation_lecture,
                    api_key=key_value,
                    target_count=max_count,
                    max_count=max_count,
                )
                service.set_runtime_lecture(generated)
                return generated
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Gemini generation failed: {exc}",
                )

    # No API key configured — fall back to deterministic generator
    generated = _generate_for_lecture(generation_lecture, max_count)
    service.set_runtime_lecture(generated)
    return generated


@app.post("/api/sessions", response_model=SessionState, status_code=status.HTTP_201_CREATED)
def create_session(req: CreateSessionRequest) -> SessionState:
    """Create a new in-memory runtime session for a lecture.

    V0.2: Accepts optional client_id, external_user_id, and tier_override for
    B2B multi-tenant learner identity and adaptive difficulty seeding.
    """
    session_service = get_session_service()
    try:
        return session_service.create_session(
            lecture_id=req.lecture_id,
            client_id=req.client_id or "default_client",
            external_user_id=req.external_user_id or "default_learner",
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


@app.post("/api/sessions/{session_id}/submit", response_model=EvaluationResult)
def submit_answer(session_id: str, req: SubmitAnswerRequest) -> EvaluationResult:
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


@app.get("/api/learners/{client_id}/{user_id}", response_model=LearnerProfile)
def get_learner_profile(client_id: str, user_id: str) -> LearnerProfile:
    """Retrieve the current learner mastery profile for a B2B client's user."""
    learner_service = get_learner_service()
    return learner_service.get_or_create_profile(client_id, user_id)


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

