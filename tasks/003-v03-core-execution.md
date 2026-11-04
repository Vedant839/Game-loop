# Task 003 — V0.3 Core Execution: Non-Blocking Immersion, Open-Ended Semantic Grading & Persistent Multi-Tenancy

## Objective

Implement the complete V0.3 feature set:
1. SQLite embedded persistence for sessions, learner profiles, and audit telemetry.
2. Explicit checkpoint and skip policy model (`SKIPPABLE`, `REQUIRED`, `REQUIRED_WITH_RETRY`) with missing-evidence skip semantics.
3. Anti-ad immersion UX (non-blocking progress bar cues, audio decrescendo, and decoupled skip controls).
4. Asynchronous open-ended semantic grading via Gemini with configurable resumption, foreground timeouts with labeled self-assessment, and idempotent late-arrival reconciliation.

## Authority

1. `SPEC.md` (§55)
2. `docs/architecture.md`
3. `ROADMAP.md` (V0.3 Phases)
4. This task

## Scope

### Subtask 1: Persistence Foundation (SQLite + Repositories)
- Introduce SQLite database file (`data/game_loop.db`) managed via SQLAlchemy / aiosqlite.
- Implement database models:
  - `Tenant`: client configuration, name, default skip policies, API keys.
  - `Session`: session ID, lecture ID, client ID, user ID, state version.
  - `SessionIntervention`: state (`PENDING`, `ACTIVE`, `EVALUATING`, `COMPLETED`, `SKIPPED`, `BYPASSED`), tier, submission results.
  - `Submission`: submission ID, idempotency key, answer text, status, AI score, feedback, latency.
  - `LearnerProfile`: concept mastery map, streak, friction index, intervention totals.
  - `TelemetryEvent`: structured event logging.
- Refactor `SessionService` and `LearnerService` to persist to SQLite while maintaining high-performance memory caching for active sessions.

### Subtask 2: Policy-Governed Skipping & Anti-Ad Immersion Flow
- Add `InterventionPolicy` enum (`SKIPPABLE`, `REQUIRED`, `REQUIRED_WITH_RETRY`) and `ResumptionPolicy` enum (`IMMEDIATE_OPTIMISTIC`, `WAIT_FOR_RESULT`).
- Add `POST /api/sessions/{session_id}/interventions/{intervention_id}/skip` endpoint.
  - Enforce policy: reject skips on `REQUIRED` / `REQUIRED_WITH_RETRY` with HTTP 403.
  - Transition state to `SKIPPED`.
  - Leave mastery unmodified ($\Delta M = 0$), logging event as `missing_evidence`.
- Update seeking sync endpoint: forward seeks past `REQUIRED` checkpoints are blocked and clamped to the trigger window.
- Frontend Player UX:
  - Render progress-bar checkpoint pips (hollow circle for skippable, solid diamond for required).
  - Add approaching interaction aura/cue at $[T - 6.0\text{s}, T]$ on the approaching timeline pip.
  - Add 300ms audio decrescendo prior to trigger pause.

### Subtask 3: Open-Ended Semantic Grading & Submission Lifecycle
- Define `open_ended` interaction schema with authored rubrics (`key_concepts`, `misconceptions`, `reference_answer`, `passing_score`).
- Implement `EvaluatorService` to asynchronously invoke Gemini (`gemini-2.5-flash` or `gemini-3.8-flash`) with structured prompts.
- Implement hash cache for semantic evaluations (`SHA256(intervention_id + normalized_answer)`).
- Add endpoints:
  - `POST /api/sessions/{session_id}/submissions/open-ended`: accepts answer, persists `SubmissionRecord` with `status = PENDING`, dispatches async evaluation, returns HTTP 202.
  - `GET /api/sessions/{session_id}/submissions/{submission_id}`: returns evaluation status and results.
  - `POST /api/sessions/{session_id}/submissions/{submission_id}/self-assess`: allows learner to self-assess timed-out submissions.
- Implement foreground timeout (5.0s) offering an explicitly labeled self-assessment fallback rubric.
- Implement late-evaluation reconciliation guard: if AI evaluation arrives after self-assessment or session completion, update submission record idempotently without duplicating mastery deltas.
- Non-blocking feedback delivery: anchored card/toast when video has resumed.

## Constraints

- Zero external database services: must run self-contained with SQLite.
- Backward compatibility: V0.1 single/multiple choice and V0.2 code sandboxes must continue working seamlessly.
- Evaluation determinism where possible: evaluation results are cached so identical submissions yield identical results.
- Secrets: `GEMINI_API_KEY` remains environment-based; never committed.

## Acceptance Criteria

1. **Persistence:** Active sessions and learner profiles persist across FastAPI server restarts.
2. **Policy Enforcement:**
   - Interventions marked `SKIPPABLE` can be skipped, transitioning state to `SKIPPED` without altering concept mastery.
   - Interventions marked `REQUIRED` reject skip requests and block forward seeks past the trigger point.
3. **Open-Ended Evaluation:**
   - Freeform student answers trigger asynchronous Gemini evaluation.
   - If evaluation completes within foreground threshold, formative feedback and score are displayed.
   - If evaluation exceeds 5.0s, learner receives labeled self-assessment fallback option.
   - Late-arriving evaluations are recorded without duplicate mastery updates.
4. **Anti-Ad UX:** Timeline pips display without obscuring video; approaching cue glows gently; audio fades down before pause.
5. **Testing & Build:**
   - All backend unit/integration tests (`pytest`) pass.
   - All frontend Vitest tests (`npm test`) pass.
   - Frontend compiles cleanly (`npm run build`).

## Verification Commands & Results

- Backend: `.\.venv\Scripts\python.exe -m pytest -q` -> **34 passed in 10.30s**
- Frontend: `npm test -- --run` (in `frontend/`) -> **18 passed in 6.90s**
- Frontend Build: `npm run build` (in `frontend/`) -> **Vite built in 3.20s without errors**

## Status

**COMPLETE** — All subtasks implemented, verified, and passing across backend and frontend suites.
