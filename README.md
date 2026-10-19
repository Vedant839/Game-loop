# game-loop (V0.2)

`game-loop` is an **embeddable B2B active learning & inquiry engine**. It embeds directly into a host video player or LMS platform, observing learner playback and triggering content-relevant, scientifically-structured interventions:

$$\textbf{Video Observation} \longrightarrow \textbf{Intervention Trigger} \longrightarrow \textbf{Hypothesize} \longrightarrow \textbf{Experiment / Code} \longrightarrow \textbf{Deterministic Evaluation} \longrightarrow \textbf{Mastery Update} \longrightarrow \textbf{Resume}$$

---

## What's New in V0.2

1. **Host-Owned Playback & `VideoPlayerAdapter`**:
   - `game-loop` does not proxy or re-encode video streams.
   - The decoupled `VideoPlayerAdapter` interface allows `game-loop` to overlay seamlessly onto standard HTML5 video, Video.js, JWPlayer, YouTube IFrame, Vimeo, or custom Canvas players.
2. **Scientific Inquiry Sandbox**:
   - Supports `predict_and_verify` and `inquiry_sandbox` interaction types.
   - 5-Phase Inquiry Workflow:
     1. **Observation**: View the context and initial code snippet.
     2. **Hypothesis Formulation**: Commit to a prediction before running code.
     3. **Experimentation**: Run code in an interactive client-side sandbox with live console output.
     4. **Verification**: Automated test assertions (`TestCase[]`) evaluated deterministically.
     5. **Conclusion**: Submit results to update the learner's mastery profile.
3. **Client-Side Code Runner**:
   - Zero-trust architecture: user-submitted code is executed exclusively in client-side sandboxes (Python simulator & JavaScript eval).
   - The backend never evaluates arbitrary code strings on the server.
4. **Dynamic Adaptive Difficulty (Tiers 1–3)**:
   - **Tier 1 (Scaffolded)**: Reduced distractors, guided hints, simplified starter code.
   - **Tier 2 (Standard Application)**: Core curriculum expectations and standard test cases.
   - **Tier 3 (Advanced / Edge Case)**: Debugging broken implementations, edge-case analysis.
   - Deterministic tier selection resolved via `LearnerProfile` concept mastery and streaks.
5. **B2B Multi-Tenant Identity & Telemetry**:
   - Supports `client_id` and `external_user_id` mapping for each session.
   - Structured telemetry events logged for host LMS reporting.

---

## Architecture Overview

```text
Host Web App / Video Player
       │
       ▼ (implements VideoPlayerAdapter)
[ game-loop Runtime SDK ]
  ├── Time/Trigger Detection (window [T - ε, T + ε])
  ├── Optimistic Pause & Seek Guard
  ├── Client-Side Sandboxed CodeRunner (Python / JS)
  └── Inquiry & Intervention Overlay UI
       │
       ▼ REST API (Deterministic logical authority)
[ FastAPI Backend Engine ]
  ├── LectureService (Canonical lecture data + JSON store)
  ├── LearnerService (Multi-tenant mastery, streaks, adaptive tiers)
  └── SessionService (In-memory state machine, idempotency, versioning)
```

---

## Local Development

### 1. Backend Setup
From the repository root:
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```
API runs on `http://localhost:8000`.

### 2. Frontend Setup
From `frontend/`:
```powershell
Set-Location frontend
npm install
npm run dev
```
Development app runs on `http://localhost:5173`.

---

## Verification & Checks

### Backend Unit & Integration Tests (26 tests)
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Frontend Tests (14 tests)
```powershell
Set-Location frontend
npm test -- --run
```

### Production Build Validation
```powershell
Set-Location frontend
npm run build
```

---

## API Endpoints Reference

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/lectures` | List available lectures |
| `GET` | `/api/lectures/{lecture_id}` | Retrieve full lecture with interventions |
| `POST` | `/api/sessions` | Create a runtime session (`client_id`, `external_user_id`, `tier_override`) |
| `POST` | `/api/sessions/{session_id}/activate` | Validate and activate intervention at playback timestamp |
| `POST` | `/api/sessions/{session_id}/submit` | Submit single/multiple choice answer (deterministic) |
| `POST` | `/api/sessions/{session_id}/experiment` | Submit inquiry sandbox experiment & test case results |
| `GET` | `/api/learners/{client_id}/{user_id}` | Get tenant-specific learner mastery profile |
| `POST` | `/api/sessions/{session_id}/sync` | Sync playback position (e.g. bypass on forward seek) |
