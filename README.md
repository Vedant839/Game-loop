# game-loop (V0.3)

`game-loop` is an **embeddable B2B active learning & dynamic inquiry engine**. Designed to integrate directly into host video players and LMS platforms, it observes learner playback in real time and triggers mathematically and pedagogically structured interventions:

$$\textbf{Video Observation} \longrightarrow \textbf{Approaching Cue} \longrightarrow \textbf{Intervention Trigger} \longrightarrow \textbf{Learner Action} \longrightarrow \textbf{Evaluation} \longrightarrow \textbf{Mastery Update} \longrightarrow \textbf{Resume}$$

---

## What's New in V0.3

1. **Embedded SQLite Persistence & Multi-Tenant Crash Recovery**:
   - Zero-external-dependency SQLite database with Write-Ahead Logging (`WAL` mode).
   - Write-through persistence for runtime sessions, learner profiles, submission records, and audit telemetry.
   - Sessions and learner mastery profiles recover seamlessly across server restarts.
2. **Asynchronous Open-Ended Grading via Gemini**:
   - Evaluates short/long freeform student reasoning against authored rubrics (`key_concepts`, `misconceptions`, `reference_answer`, `passing_score`).
   - Idempotent evaluation cache based on `SHA256(intervention_id + normalized_answer)`.
   - Offline / timeout-safe fallback rubric evaluator.
   - **Reconciliation Guard**: Prevents double-counting mastery if AI results arrive after a student has already self-assessed.
3. **5-Second Fallback & Reference Rubric Self-Assessment**:
   - For open-ended questions under `wait_for_result`, a 5-second timeout offers an explicitly labeled self-assessment card comparing the student's answer with the reference rubric.
4. **Policy-Governed Skipping & Missing-Evidence Semantics**:
   - Explicit `InterventionPolicy`: `SKIPPABLE`, `REQUIRED`, and `REQUIRED_WITH_RETRY`.
   - `POST /api/sessions/{session_id}/interventions/{intervention_id}/skip` strictly checks policy (rejecting `REQUIRED` skips with HTTP 403).
   - Skipping an intervention records telemetry as `missing_evidence: true` with zero mastery change ($\Delta M = 0$), rather than penalizing the student.
   - Forward seek past uncompleted `REQUIRED` checkpoints is automatically guarded and clamped.
5. **Anti-Ad Immersion & Interactive Player UX**:
   - **Interactive Timeline Progress Bar**: Visual checkpoint pips displayed directly on the timeline (hollow for skippable, solid for required) with color-coded states (Pending, Active, Completed, Skipped, Evaluating).
   - **Approaching Interaction Cue**: Non-blocking ambient glow aura at $[T - 6.0\text{s}, T]$ preparing the student for an upcoming interaction.
   - **Audio Decrescendo**: 300ms audio fade before pause to eliminate jarring hard stops.
   - **Fullscreen Overlay Support**: Fullscreens the video wrapper container so interactive overlays, code editors, and open-ended textareas remain interactive in fullscreen mode.

---

## Core Architecture

```text
Host Web App / Video Player
       │
       ▼ (implements VideoPlayerAdapter)
[ game-loop Runtime SDK ]
   ├── Time/Trigger Detection (window [T - ε, T + ε])
   ├── Interactive Timeline Pips & Approaching Cue [T - 6s, T]
   ├── 300ms Audio Decrescendo & Seek Guard
   ├── Fullscreen Overlay Support
   ├── Client-Side CodeRunner (Python WASM / JS)
   └── Open-Ended Response & Self-Assessment UI
       │
       ▼ REST API (Deterministic & Persistent Authority)
[ FastAPI Backend Engine ]
   ├── Database (Embedded SQLite with WAL, Multi-Tenant Repositories)
   ├── LectureService (Canonical curriculum & authored rubrics)
   ├── LearnerService (Persistent mastery profiles, streaks, dynamic tiers)
   ├── SessionService (Session lifecycle, seek validation, policy enforcement)
   └── EvaluatorService (Async Gemini grading, hash cache, fallback rubric)
```

---

## Dynamic Adaptive Difficulty (Tiers 1–3)

Difficulty tiers adapt automatically to individual learner performance per concept:

- **Tier 1 (Scaffolded)**: Selected when concept mastery $< 0.40$ or streak $\le -2$. Provides guided hints, starter templates, and reduced distractors.
- **Tier 2 (Standard Baseline)**: Selected when mastery is between $0.40$ and $0.79$. Standard conceptual challenge.
- **Tier 3 (Advanced / Edge Case)**: Selected when mastery $\ge 0.80$ or streak $\ge 2$. Debugging broken implementations, edge-case analysis, and complex proofs.

---

## Local Development & Quickstart

### 1. Backend Setup
From the repository root:
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
API runs on `http://127.0.0.1:8000` (Interactive docs available at `http://127.0.0.1:8000/docs`).

### 2. Frontend Setup
From the `frontend/` directory:
```powershell
Set-Location frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Development web player runs on `http://127.0.0.1:5173`.

---

## Test Verification

### Backend Tests (34 tests passing)
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

### Frontend Tests (18 tests passing)
```powershell
npm --prefix frontend test -- --run
```

### Production Build Validation
```powershell
npm --prefix frontend run build
```

---

## API Endpoints Reference

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check endpoint |
| `GET` | `/api/lectures` | List available lectures and summary metadata |
| `GET` | `/api/lectures/{lecture_id}` | Retrieve full lecture with authored interventions & rubrics |
| `POST` | `/api/lectures` | Register a new lecture definition |
| `POST` | `/api/sessions` | Create a runtime session (`client_id`, `external_user_id`, `tier_override`) |
| `GET` | `/api/sessions/{session_id}` | Get current session state and intervention statuses |
| `POST` | `/api/sessions/{session_id}/activate` | Validate and activate intervention at playback timestamp |
| `POST` | `/api/sessions/{session_id}/sync` | Sync playback position and guard against seeking past required checkpoints |
| `POST` | `/api/sessions/{session_id}/submit` | Submit single/multiple choice answer (deterministic) |
| `POST` | `/api/sessions/{session_id}/experiment` | Submit inquiry sandbox experiment & test case verification |
| `POST` | `/api/sessions/{session_id}/submissions/open-ended` | Submit open-ended conceptual reasoning for async AI grading |
| `GET` | `/api/sessions/{session_id}/submissions/{submission_id}` | Poll async grading status, AI score, feedback, and misconceptions |
| `POST` | `/api/sessions/{session_id}/submissions/{submission_id}/self-assess` | Self-assess timed-out submission against authored reference rubric |
| `POST` | `/api/sessions/{session_id}/interventions/{intervention_id}/skip` | Skip skippable intervention (logged as missing evidence, $\Delta M = 0$) |
| `GET` | `/api/learners/{client_id}/{user_id}` | Retrieve persistent tenant-specific learner mastery profile |
| `GET` | `/api/telemetry` | Export structured B2B LMS telemetry events |
