# game-loop Roadmap

## V0.1 - Deterministic Active-Learning Proof of Concept

### Goal

Build a working Grade 9 Mathematics video-learning proof of concept in which:

```text
video
-> fixed interruption
-> learner action
-> deterministic evaluation
-> authored feedback
-> resume
```

Gemini participates only during authoring.

---

## Phase 1 - Project Foundation

### Objectives
- Establish monorepo structure.
- Set up React + TypeScript frontend.
- Set up FastAPI + Python backend.
- Establish local development commands.
- Establish environment/secret handling.
- Establish test layout.

### Exit criteria
- Frontend starts.
- Backend starts.
- Frontend can reach backend.
- No secret values are committed or documented.

---

## Phase 2 - Lecture Content Foundation

### Objectives
- Implement lecture JSON schema.
- Add one lecture artifact.
- Add timestamped transcript representation.
- Add local video configuration.
- Implement deterministic schema validation.

### Exit criteria
- Lecture loads successfully.
- Invalid lecture structures are rejected.
- Video and transcript metadata are available to runtime.

---

## Phase 3 - Runtime Session and State

### Objectives
- Implement in-memory sessions.
- Implement intervention state machine.
- Implement session/intervention IDs.
- Implement state versions/sequence numbers.
- Implement stale-event rejection.
- Implement submission idempotency.

### Exit criteria
- Backend can create a session.
- Backend can activate a valid intervention.
- Invalid/stale activation is rejected.
- Submission happens exactly once logically.
- State transitions match SPEC.

---

## Phase 4 - Video and Intervention UI

### Objectives
- Build video player.
- Implement trigger-window detection.
- Pause at the first locally detected trigger-window position.
- Display single-choice and multiple-selection interventions.
- Submit structured answers.
- Display authored correct/incorrect feedback.
- Resume playback after feedback.

### Exit criteria
- Full learner loop works end-to-end.
- Intervention order is fixed.
- Seeking cannot silently bypass outstanding required state.
- UI behavior is consistent with backend authority.

---

## Phase 5 - Gemini Authoring Pipeline

### Objectives
- Produce timestamped transcript input.
- Call Gemini with the V0.1 authoring contract.
- Parse candidate interventions.
- Validate schema.
- Validate timestamps.
- Apply same-segment relocation rules.
- Apply spacing/conflict rules.
- Apply count rules.
- Produce final lecture JSON.

### Exit criteria
- A real lecture can be authored automatically.
- One failed Gemini generation receives exactly one identical retry.
- Invalid individual interventions are dropped according to SPEC.
- Zero valid interventions causes generation failure.
- Final output passes deterministic validation.

---

## Phase 6 - Real Lecture Integration

### Objectives
- Use an actual Grade 9 Mathematics lecture.
- Generate the lecture JSON.
- Run the complete frontend/backend flow.
- Verify trigger timing and intervention quality.
- Correct implementation defects without changing product scope.

### Exit criteria
- Complete lecture can be watched.
- All authored interventions work.
- Runtime does not call Gemini.
- Runtime behavior is deterministic.

---

## Phase 7 - Verification

### Objectives
- Complete unit tests.
- Complete integration tests.
- Run TestSprite behavioral verification.
- Have Copilot independently review implementation.
- Repair verified defects.

### Exit criteria
- Critical behavioral flows pass.
- No known SPEC violations.
- No architectural drift.
- TestSprite and reviewer findings are resolved or explicitly documented.

---

## Phase 8 - Additional Lecture Data

Only after the first lecture is stable:

- Add additional Grade 9 Mathematics lecture data.
- Verify that the architecture works across different lecture content.
- Look for content-specific assumptions that accidentally entered the implementation.

---

## V0.2 — Scientific Inquiry Sandbox & Adaptive Tiers (Completed)
- Client-side zero-trust Python & JavaScript sandboxed code runners.
- 5-phase scientific inquiry workflow (`predict_and_verify` & `inquiry_sandbox`).
- Dynamic adaptive difficulty (Tiers 1–3) with deterministic tier resolution and streak tracking.
- B2B multi-tenant identity mapping (`client_id`, `external_user_id`) & telemetry events.

---

## V0.3 — Non-Blocking Immersion, Open-Ended Semantic Grading & Persistent Multi-Tenancy (In Progress)

### Goal
Evolve `game-loop` into an enterprise-ready, non-intrusive B2B active learning engine with:
1. Asynchronous open-ended semantic grading via Gemini with graceful timeouts and safe late-response handling.
2. Anti-ad immersion UX (non-blocking progress bar cues, audio decrescendo, and decoupled policy-governed skipping).
3. Embedded crash-resilient persistence (SQLite + SQLAlchemy / aiosqlite).
4. Multi-tenant governance with comprehensive audit telemetry.

---

### Phase 1: Persistence Foundation (SQLite & Repositories)
**Objectives:**
- Replace in-memory dictionaries with embedded SQLite (`data/game_loop.db`) via SQLAlchemy / aiosqlite.
- Implement schema models for tenants, sessions, session interventions, submissions, learner profiles, and telemetry events.
- Maintain write-through memory caching for sub-millisecond hot reads and session sync.
- Migrate `SessionService` and `LearnerService` to use repository patterns.

**Exit Criteria:**
- Server restart preserves active sessions and learner mastery.
- All existing 26 backend unit tests pass without regression.

---

### Phase 2: Policy-Governed Skipping & Anti-Ad Immersion Flow
**Objectives:**
- Formalize `InterventionPolicy`: `SKIPPABLE`, `REQUIRED`, and `REQUIRED_WITH_RETRY`.
- Enforce skip rules in backend state machine; add `SKIPPED` state with missing-evidence mastery semantics ($\Delta M = 0$).
- Implement non-blocking progress-bar cue (timeline pips, subtle glow on approach) decoupled from skip policy.
- Implement 300ms audio decrescendo prior to trigger pause.
- Prevent forward seeking past `REQUIRED` checkpoints.

**Exit Criteria:**
- Skippable checkpoints can be bypassed cleanly; required checkpoints block forward progress.
- Skips are logged as explicit telemetry events without penalizing mastery.

---

### Phase 3: Open-Ended Semantic Grading & Submission Lifecycle
**Objectives:**
- Add `open_ended` interaction schema with authored rubrics (key concepts, misconceptions, reference answer).
- Implement `EvaluatorService` invoking Gemini asynchronously.
- Add submission status lifecycle (`PENDING`, `COMPLETED`, `TIMED_OUT`, `FAILED`) with unique `submission_id`.
- Implement configurable playback resumption (`IMMEDIATE_OPTIMISTIC` vs. `WAIT_FOR_RESULT`).
- Add 5.0s foreground timeout falling back to an explicitly labeled self-assessment rubric.
- Implement late-evaluation reconciliation guard preventing duplicate mastery updates or state corruption.
- Deliver completed evaluation feedback via non-intrusive anchored cards rather than blocking modals if playback resumed.

**Exit Criteria:**
- Freeform answers receive formative AI feedback and score.
- Network timeouts gracefully degrade to self-assessment without stalling the student.
- Late-arriving evaluations are safely absorbed idempotently.

---

### Phase 4: End-to-End Verification & B2B Telemetry Audit
**Objectives:**
- Add integration tests covering the full asynchronous evaluation and skip lifecycle.
- Update frontend React player with timeline pips, approaching glow, and freeform input component.
- Add telemetry export endpoint for B2B LMS reporting.
- Run complete test suite and verify clean builds.

**Exit Criteria:**
- All unit, integration, and Vitest behavioral tests pass.
- Zero TypeScript build errors.

