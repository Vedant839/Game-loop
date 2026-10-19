# Task 002 - Lecture Content, Runtime Session State Machine, and Video Intervention UI

## Objective

Implement the complete V0.1 runtime loop (WATCH -> INTERRUPTION -> ACT -> EVALUATE -> FEEDBACK -> RESUME) including lecture data validation, backend session state machine, and frontend video player intervention overlay.

## Authority

1. `SPEC.md`
2. `docs/architecture.md`
3. `ROADMAP.md`
4. This task

If this task conflicts with higher-level documents, stop and escalate.

## Scope

- **Lecture Data & Validation**:
  - Implement Pydantic / TypeScript schemas for Lecture, Transcript Segment, Intervention, Option, Timing Config.
  - Implement deterministic validation rules for lecture JSON files (timing config `2 * tolerance < min_trigger_gap`, option uniqueness, answer matching, segment timestamp bounds, trigger window bounds, max interventions count <= 6).
  - Add canonical Grade 9 Mathematics lecture artifact (`data/lectures/math_sample_lecture.json`) referencing `math_sample_lecture.mp4`.
  - Add backend endpoints `GET /api/lectures` and `GET /api/lectures/{lecture_id}`.
  - Fix media serving endpoint (`GET /media/{file_name}`).

- **Runtime Session & State Machine**:
  - In-memory session store for active sessions.
  - Implement intervention state machine (`PENDING`, `ACTIVE`, `COMPLETED`, `BYPASSED`).
  - Terminal state rules: `COMPLETED` and `BYPASSED` cannot re-activate.
  - Version sequence numbers and stale event rejection.
  - Idempotent submission handling using idempotency keys.
  - Deterministic answer evaluation (`single_choice` and `multiple_selection`).
  - Add backend endpoints:
    - `POST /api/sessions`: create runtime session for a lecture.
    - `GET /api/sessions/{session_id}`: get session status.
    - `POST /api/sessions/{session_id}/activate`: activate an intervention if trigger window & state are valid.
    - `POST /api/sessions/{session_id}/submit`: submit answer, evaluate, transition state to `COMPLETED`, return feedback.
    - `POST /api/sessions/{session_id}/sync`: synchronize playback position and handle seeking bypasses (`PENDING -> BYPASSED`).

- **Video & Intervention UI**:
  - React video player with trigger window detection `[trigger_time - tolerance, trigger_time + tolerance]`.
  - Immediate pause on trigger window entry.
  - Overlay UI rendering `single_choice` and `multiple_selection` interventions.
  - Answer selection & single submit button (disabled when no option selected).
  - Lock selection on submit & render feedback (correct / incorrect).
  - Minimum 3-second feedback display timer before auto-resuming playback.
  - Prevent seek while intervention is `ACTIVE`.
  - Sync seek forward to trigger backend bypass transitions.
  - Reconcile rejected activations with backend state.

## Constraints

- Runtime MUST NOT call Gemini or any LLM.
- Evaluation MUST be deterministic (no semantic grading).
- No database persistence (sessions are in-memory).
- Follow exact schema and state machine rules in `SPEC.md`.

## Acceptance Criteria

1. Valid lecture JSON loads and invalid structures/configs are rejected.
2. Backend creates session, activates pending interventions, evaluates submissions, handles idempotency, and transitions state per SPEC state machine.
3. Frontend pauses video on trigger window, presents intervention overlay, submits answer, displays feedback for at least 3 seconds, and resumes playback.
4. Seeking forward past pending interventions marks them `BYPASSED` on backend.
5. Seeking backward into `COMPLETED` or `BYPASSED` interventions does not re-trigger them.
6. Automated backend unit/integration tests and frontend Vitest tests pass.

## Verification

- Backend unit tests (`pytest`): test schema validation, state machine transitions, idempotency, stale version rejection, deterministic evaluation.
- Frontend Vitest tests (`npm run test`): test video player trigger detection, overlay presentation, option selection, submit locking, feedback timer, and seek restriction.
- Frontend build (`npm run build`): clean compilation without TypeScript errors.
