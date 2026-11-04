# SPEC.md — game-loop V0.2

**Status:** IMPLEMENTED / VERIFIED
**Version:** V0.2
**Purpose:** Embeddable B2B Active Learning & Inquiry Engine
**Authority:** This document is the source of truth for V0.1 and V0.2 product behavior, architecture, and contracts.

---

# 1. Product Objective

`game-loop` transforms passive educational video consumption into an active learning loop:

**WATCH → CONTENT-RELEVANT INTERRUPTION → ACT → EVALUATE → FEEDBACK → RESUME**

The purpose of the learning intervention is not merely to test memory. It is to make the learner stop, think, predict, reason, or engage with the material before continuing.

The primary objective is:

> Prove that educational video can be converted into a continuous active-learning loop without breaking the learner's viewing flow.

---

# 2. V0.1 Scope

V0.1 is a proof of concept.

It supports:

* Mathematics
* Grade 9
* One primary demonstration lecture initially
* Local video file playback
* AI-generated learning interventions
* Approximately 4–6 learning interventions per lecture
* Deterministic evaluation
* Local JSON lecture data
* In-memory runtime session state

V0.1 does not require:

* Accounts
* User authentication
* Persistent learner data
* Database infrastructure
* Billing
* Analytics infrastructure
* Dynamic AI generation during playback
* Arbitrary code execution
* Stateful simulations
* Workflow execution
* Open-ended semantic grading

---

# 3. Learning Intervention Model

A learning intervention is a content-relevant interruption in the lecture that requires an explicit learner action.

V0.1 supports exactly two intervention types:

* `single_choice`
* `multiple_selection`

The intervention must be related to the material surrounding its trigger point.

The intervention exists to create active engagement with the material before playback continues.

---

# 4. Response Correctness

Correctness is determined exclusively through finite structured responses.

For `single_choice`:

```text
submitted_option == correct_option
```

For `multiple_selection`:

```text
submitted_set == correct_set
```

Selection order does not matter for `multiple_selection`.

Evaluation is deterministic.

---

# 5. Unsupported Response Types

V0.1 does not support:

* Open-ended natural-language answers
* Keyword matching
* Semantic similarity grading
* Essay grading
* Subjective grading
* Freeform mathematical expressions
* General symbolic mathematics
* Programming answers
* Arbitrary code execution
* Stateful simulations
* Workflow execution
* Subjective interpretation

---

# 6. Learner Experience

During normal playback:

1. Video plays normally.
2. The system detects an intervention trigger.
3. The frontend immediately pauses playback.
4. The intervention appears as an overlay.
5. The learner selects an answer.
6. The learner submits exactly once.
7. The system evaluates the response.
8. Feedback is displayed.
9. After the required feedback display period, playback resumes automatically.

Correct response:

**brief confirmation → minimum feedback display period → resume**

Incorrect response:

**explanation → minimum feedback display period → resume**

The learner may seek during normal playback when no intervention is `ACTIVE`.

---

# 7. Runtime Authority

The frontend owns immediate physical/UI behavior:

* Video playback
* Local playback position
* Immediate optimistic pause
* Intervention UI
* Selection state before submission
* Feedback display
* Immediate resume
* UI reconciliation

The backend owns authoritative logical state:

* Session state
* Logical intervention state
* Activation validity
* Progression
* Submission
* Evaluation
* Terminal states
* State versioning
* Stale-event protection

The frontend may react optimistically.

The backend is authoritative for logical state.

The backend must not be required to approve the physical pause before the frontend pauses the video.

---

# 8. Runtime State Machine

Each intervention has one of these states:

```text
PENDING
ACTIVE
COMPLETED
BYPASSED
```

Allowed transitions:

```text
PENDING → ACTIVE
ACTIVE → COMPLETED
PENDING → BYPASSED
```

No other transitions are valid.

---

# 9. Terminal-State Rule

`COMPLETED` and `BYPASSED` are terminal states.

Once an intervention reaches either terminal state:

* It cannot become `ACTIVE` again during the same session.
* Backward seeking into that intervention's timestamp does not reactivate it.
* The intervention does not require another submission.

`BYPASSED` does not mean completed, correct, mastered, or successfully answered.

It only means the learner moved past the intervention without activating it.

---

# 10. Trigger Detection

Each intervention has a configured `trigger_time`.

`trigger_time` represents the **intended pause point**.

The tolerance value is a detection tolerance only. It does not redefine the intended pause point and does not cause the frontend to intentionally pause early.

For trigger time `T` and tolerance `ε`, the intervention is eligible when playback position enters:

```text
[T - ε, T + ε]
```

The frontend pauses at the first locally detected playback position within the tolerance window.

The frontend does **not** seek the video backward or forward to `trigger_time`.

Therefore:

* `trigger_time` is the center/intended point.
* `tolerance` compensates for playback timing and browser event granularity.
* The actual pause position may differ slightly from `trigger_time`.

Only `PENDING` interventions can activate.

`COMPLETED`, `BYPASSED`, and already `ACTIVE` interventions cannot activate.

---

# 11. Trigger and Pause Behavior

When a valid `PENDING` intervention enters its trigger window:

1. Frontend pauses the video immediately.
2. Frontend displays the intervention overlay.
3. Frontend sends an activation event to the backend.
4. Backend validates the activation.
5. If valid, backend marks the intervention `ACTIVE`.
6. If invalid or stale, the frontend reconciles with the backend-authoritative state.

### Activation Rejection Reconciliation

If the backend rejects activation, the frontend must:

* close the rejected intervention overlay;
* discard its local activation state;
* adopt the backend's returned intervention state/version;
* keep the current valid playback position;
* resume playback immediately unless the backend reports another valid `ACTIVE` intervention that must remain displayed.

The frontend must not independently convert a rejected activation into `COMPLETED` or `BYPASSED`.

### Rejection Suppression

After an activation attempt for an intervention is rejected while that intervention remains `PENDING`, the frontend must suppress another activation attempt for that intervention until one of these occurs:

1. Playback leaves the intervention's tolerance window and subsequently re-enters it; or
2. The backend returns a new authoritative state/version that makes the intervention eligible for activation again.

This prevents repeated activation requests while the playback position remains inside the same rejected trigger window.

---

# 12. Seeking

Seeking is allowed during normal playback when no intervention is `ACTIVE`.

### Forward Seeking

If the learner seeks forward past a `PENDING` intervention's trigger window, that intervention transitions:

```text
PENDING → BYPASSED
```

The intervention is not considered answered, completed, mastered, or successfully passed.

### Seeking Into a Pending Window

If the learner seeks to a playback position inside a `PENDING` intervention's tolerance window:

* The intervention becomes eligible for activation.
* The normal trigger behavior applies.
* The frontend pauses immediately.
* The backend validates the activation.

A seek into a pending trigger window therefore does not automatically bypass the intervention.

### Backward Seeking

Backward seeking into an intervention that is already `COMPLETED` or `BYPASSED` is a no-op with respect to that intervention.

### Seeking While ACTIVE

Seeking is disabled while an intervention is `ACTIVE`.

The learner must submit the currently active intervention before normal seeking becomes available again.

The active intervention therefore cannot be escaped by seeking away from its trigger point.

---

# 13. Submission

Before submission, the learner may change their selection.

After submission:

* Selection is locked.
* Exactly one logical submission is accepted.
* The response is evaluated once.
* The intervention cannot be retried.
* The intervention transitions from `ACTIVE` to `COMPLETED`.

A submission must contain an idempotency key so that the same logical submission can safely be retried at the transport layer without causing multiple evaluations.

The backend must treat repeated submissions using the same session, intervention, and idempotency key as the same logical submission.

---

# 14. Evaluation

For `single_choice`:

```text
submitted_option == correct_option
```

For `multiple_selection`:

```text
submitted_set == correct_set
```

For `multiple_selection`, option order is irrelevant.

An empty submitted selection is not valid for `multiple_selection`.

The frontend must not allow submission with no selected option.

No LLM is involved in runtime evaluation.

---

# 15. Feedback

Each intervention contains:

* `correct_feedback`
* `incorrect_feedback`

Correct feedback is displayed when the submitted response exactly matches the stored correct answer.

Incorrect feedback is displayed for every other valid submission.

Feedback is stored in the lecture data.

Gemini is not called during runtime evaluation.

### Feedback Display Duration

Feedback must remain visible for at least **3 seconds**.

The configured feedback duration may be longer than 3 seconds, but it must never be shorter than 3 seconds.

Playback resumes automatically after the configured feedback duration has elapsed.

---

# 16. Interaction Schema

Each generated intervention contains:

```text
id
trigger_time
concept
difficulty
type
question
options
correct_answer
correct_feedback
incorrect_feedback
```

`type` must be exactly one of:

```text
single_choice
multiple_selection
```

`difficulty` is generated by Gemini and must be one of:

```text
Easy
Medium
Hard
Tough
```

### Option Schema

Each option contains:

```text
id
text
```

Option IDs must be unique within an intervention.

For `single_choice`:

```text
correct_answer: string
```

The value must exactly match the ID of one option.

For `multiple_selection`:

```text
correct_answer: array[string]
```

Every value must exactly match the ID of an option.

The correct-answer array must contain no duplicate IDs.

An empty correct-answer set is invalid.

---

# 17. Transcript Representation

The authoring pipeline uses sentence-level timestamps.

A transcript consists of ordered transcript segments.

Each segment contains:

```text
start_time
end_time
text
```

A transcript segment represents one sentence or sentence-level unit with a defined temporal interval.

Transcript sources are processed in this order:

1. Use an existing transcript if available.
2. Otherwise generate a speech-to-text transcript.

Each transcript segment must have valid timestamps satisfying:

```text
0 ≤ start_time < end_time ≤ video_duration
```

---

# 18. AI Authoring Pipeline

The authoring pipeline is:

```text
Video
  ↓
Transcript
  ↓
Timestamped transcript + lecture metadata
  ↓
Gemini
  ↓
Generated intervention set
  ↓
Schema validation
  ↓
Timestamp validation
  ↓
Spacing/conflict validation
  ↓
Intervention-count validation
  ↓
Final intervention set
  ↓
Lecture JSON
```

Gemini independently identifies suitable intervention points.

One Gemini generation call produces the complete proposed intervention set.

Gemini proposes:

* Intervention content
* Intervention type
* Difficulty
* Relevant transcript segment
* Trigger timestamp

The deterministic validator verifies the generated structure and timing.

---

# 19. Gemini Input

Gemini receives:

* Full timestamped transcript
* Subject
* Grade
* Lecture duration
* Allowed intervention types
* Target intervention count
* Maximum intervention count
* Relevant authoring constraints

The model must generate structured intervention data.

Gemini is responsible for choosing pedagogically relevant intervention points.

The deterministic validator is responsible for verifying objective technical constraints.

---

# 20. AI Generation Determinism

Gemini generation is non-deterministic.

Therefore:

* Gemini output is not treated as deterministic.
* JSON parsing is deterministic.
* Schema validation is deterministic.
* Timestamp validation is deterministic.
* Spacing validation is deterministic.
* Conflict resolution is deterministic.
* Intervention-count enforcement is deterministic.
* Runtime evaluation is deterministic.

The authoring pipeline must not assume repeated Gemini calls produce identical results.

---

# 21. Gemini Confidence

Gemini may provide confidence information.

Confidence is diagnostic only.

It must never be treated as proof that an intervention is valid.

Deterministic validation rules remain authoritative.

---

# 22. Complete Gemini Failure

If the complete Gemini generation call fails:

1. Retry the identical request once.
2. If the retry fails, lecture generation fails.

No additional automatic retries occur.

---

# 23. Individual Intervention Validation

If Gemini returns valid structured JSON but individual interventions violate constraints:

* Validate each intervention independently.
* Drop invalid interventions.
* Preserve valid interventions.

The entire generation is not discarded solely because one intervention is invalid.

An intervention is invalid if it violates any mandatory schema, timing, interaction-type, answer, transcript-association, or spacing constraint.

---

# 24. Zero Valid Interventions

If zero valid interventions remain after validation:

**Lecture generation fails.**

The system must not repeatedly regenerate solely to reach the target intervention count.

---

# 25. Trigger Timestamp Validation

Each generated intervention must identify a transcript segment to which its trigger belongs.

A trigger is technically valid when:

1. Its timestamp is within the video duration.
2. Its timestamp falls within the specified transcript segment.
3. The referenced transcript segment has valid timestamps.
4. The intervention satisfies the schema requirements.
5. The intervention satisfies spacing and timing constraints.
6. The trigger does not violate any terminal authoring constraint.

Pedagogical suitability is determined by Gemini during generation; the deterministic validator does not attempt to independently judge whether a learning moment is pedagogically interesting.

### Trigger Relocation

If the generated timestamp is technically unsuitable:

1. Search for another valid trigger point within the **same transcript segment**.
2. Candidate points are evaluated using the same deterministic validity criteria.
3. Candidate points are considered in ascending timestamp order.
4. The first valid candidate is selected.
5. If no valid candidate exists within that same segment, drop the intervention.

The system must not relocate an intervention to an unrelated transcript segment.

---

# 26. Interaction Spacing and Conflict Resolution

Intervention timing must satisfy a configurable minimum trigger gap:

```text
MIN_TRIGGER_GAP
```

Two interventions conflict when their trigger times are less than `MIN_TRIGGER_GAP` apart.

For chronologically ordered interventions `A` and `B`:

```text
A.trigger_time < B.trigger_time
```

If:

```text
B.trigger_time - A.trigger_time < MIN_TRIGGER_GAP
```

then the two interventions conflict.

The earlier-triggered intervention wins.

The later-triggered intervention is dropped.

The later intervention is never shifted automatically.

### Equal-Timestamp Conflict

If:

```text
A.trigger_time == B.trigger_time
```

the interventions conflict.

Because neither timestamp is earlier, the tie is resolved using the original Gemini output order.

The intervention appearing earlier in the Gemini-generated intervention list is retained.

The other intervention is dropped.

### Runtime Eligibility-Window Conflict

For an intervention:

```text
window_start = trigger_time - tolerance
window_end   = trigger_time + tolerance
```

Two chronologically ordered interventions must not have overlapping eligibility windows.

The timing configuration must satisfy:

```text
2 × tolerance < MIN_TRIGGER_GAP
```

Strict inequality is required because the trigger windows are inclusive at both boundaries.

If:

```text
2 × tolerance >= MIN_TRIGGER_GAP
```

the timing configuration is invalid.

The system must reject the configuration rather than silently modifying either value.

This invariant guarantees that valid trigger spacing cannot produce overlapping runtime eligibility windows.

### Configuration Validation

Timing configuration must be validated before authoring or runtime operation begins.

Invalid configuration causes configuration loading to fail.

No implementation may silently:

* Clamp tolerance
* Modify `MIN_TRIGGER_GAP`
* Change window boundaries
* Ignore the conflict
* Invent a different spacing rule

---

# 27. Intervention Count

The target intervention count is approximately 4–6.

`MAX_INTERVENTIONS` is fixed at:

```text
6
```

Gemini may return fewer or more than six proposed interventions.

### Fewer Than Four

If fewer than four valid interventions remain:

* Keep all valid interventions.
* Do not regenerate solely to reach four.

### Four to Six

Keep all valid interventions.

### More Than Six

If more than six valid interventions remain:

1. Preserve Gemini's original generated order.
2. Keep the first six valid interventions in that order.
3. Drop all remaining valid interventions.

The count limit is deterministic.

The system does not rank interventions by difficulty, confidence, or presumed pedagogical value when enforcing the maximum.

---

# 28. Lecture Storage

Generated lectures are stored as:

```text
data/lectures/<lecture-id>.json
```

The JSON file contains the complete runtime lecture definition, including:

* Lecture metadata
* Video reference
* Transcript information where required
* Intervention definitions
* Trigger timestamps
* Correct answers
* Feedback
* Difficulty
* Interaction type
* Options
* Timing configuration where lecture-specific

The lecture JSON must pass schema validation before becoming available to runtime.

---

# 29. Local Video Delivery

A browser cannot directly load an arbitrary filesystem path from lecture JSON.

For V0.1, the backend serves the local lecture video over HTTP.

The lecture JSON therefore references a backend-served video path rather than a raw operating-system filesystem path.

The browser loads the video through the application's HTTP server.

The backend must serve only files within the configured lecture media directory.

The runtime must not expose arbitrary filesystem paths to the browser.

---

# 30. Runtime Data Flow

Runtime uses pre-generated lecture JSON.

The runtime flow is:

```text
Lecture JSON
    ↓
Backend session
    ↓
Frontend loads lecture
    ↓
Video playback
    ↓
Trigger detection
    ↓
Optimistic frontend pause
    ↓
Backend activation validation
    ↓
Intervention
    ↓
Submission
    ↓
Backend evaluation
    ↓
Feedback
    ↓
Resume
```

Gemini is not involved in this runtime path.

---

# 31. Backend API Responsibilities

The backend must provide REST endpoints sufficient to support:

* Lecture loading
* Session creation
* Intervention activation
* State retrieval
* Submission
* Evaluation
* Progression
* Stale-event rejection

The exact HTTP routes and JSON contracts are defined in `docs/architecture.md`.

The backend keeps session state in memory.

No database is required for V0.1.

---

# 32. Frontend Responsibilities

The frontend is responsible for:

* Loading the lecture
* Rendering the video
* Tracking local playback position
* Detecting trigger windows
* Immediately pausing at valid trigger points
* Rendering intervention overlays
* Managing pre-submission selections
* Displaying feedback
* Resuming playback
* Disabling seeking while an intervention is `ACTIVE`
* Reconciling rejected or stale backend events
* Preventing duplicate local activation attempts
* Preventing submission without a selected answer

The frontend must not become the authoritative source of logical intervention state.

---

# 33. State Synchronization

Every session and intervention state-changing event must contain sufficient information to prevent stale events from overwriting newer state.

The implementation must use:

* Session IDs
* Intervention IDs
* State versions or sequence numbers
* Submission idempotency keys

A stale event must be rejected.

A stale frontend response must not overwrite newer backend-authoritative state.

The backend is authoritative for logical state.

The exact versioning and stale-response protocol is defined in `docs/architecture.md`.

---

# 34. Submission Reliability

A learner submission must be safe against network retries.

Each logical submission has an idempotency key.

The backend uses the combination of:

```text
session_id
intervention_id
idempotency_key
```

to identify a logical submission attempt.

If the same submission request is received again with the same identifiers:

* It must not create a second evaluation.
* It must return the previously established submission result.

A new idempotency key cannot be used to retry an already completed intervention because terminal-state rules still apply.

---

# 35. Runtime Failure Handling

### Backend Session Not Found

If the frontend attempts an operation for a session that no longer exists:

* The backend returns a session-not-found response.
* The frontend stops attempting state-changing operations for that session.
* The current intervention overlay is closed if one is displayed.
* The frontend displays a session-loss error.
* The frontend does not invent a replacement backend state.

The user must restart the session.

### Backend Restart

Because V0.1 session state is in memory, a backend restart may invalidate active sessions.

Invalidated sessions are handled using the session-loss behavior above.

---

# 36. Video-End Behavior

### Video Ends With ACTIVE Intervention

If the video reaches its end while an intervention is `ACTIVE`:

* The intervention remains `ACTIVE`.
* The learner must submit the intervention.
* Video playback cannot resume beyond the end of the video.
* The intervention cannot be bypassed through seeking because seeking is disabled while `ACTIVE`.

### Video Ends With PENDING Interventions

Any `PENDING` interventions whose trigger points were not reached become `BYPASSED` when the video ends.

They are not considered completed or answered.

### Video Ends With Terminal Interventions

`COMPLETED` and `BYPASSED` interventions remain unchanged.

---

# 37. Multiple Tabs

A session is logically associated with one session ID.

Multiple browser tabs may interact with the same session.

The backend remains authoritative.

If one tab causes a state transition that makes another tab stale:

* The stale tab receives a stale-state response when it attempts an invalid state change.
* The stale tab reconciles to the backend-authoritative state.
* The stale tab must not overwrite the newer state.

The implementation does not guarantee synchronized visual playback between multiple tabs.

---

# 38. External Tool and Execution Boundary

V0.1 does not execute:

* Arbitrary code
* User programs
* External workflows
* Stateful tool environments
* General-purpose simulations

Therefore V0.1 does not require execution-isolation mechanisms for those environments.

---

# 39. Runtime AI Boundary

Gemini is an authoring-time dependency only.

Gemini must not be called during video playback.

Gemini must not:

* Evaluate learner answers
* Determine runtime state
* Decide whether an answer is correct
* Control playback
* Resolve runtime state conflicts
* Resolve stale events

Runtime behavior must remain deterministic and operational without an AI model.

---

# 40. Project Architecture

The system is divided conceptually into:

```text
AUTHORING
RUNTIME
SHARED
```

### AUTHORING

Responsible for:

* Transcript acquisition
* Gemini generation
* Parsing
* Schema validation
* Trigger validation
* Timestamp relocation
* Spacing/conflict validation
* Intervention-count enforcement
* Lecture JSON generation

### RUNTIME

Responsible for:

* Lecture loading
* Session management
* Playback coordination
* Trigger detection
* Intervention state
* Submission
* Deterministic evaluation
* Feedback
* State synchronization

### SHARED

Responsible for:

* Data schemas
* Validation models
* Shared types
* Constants
* Common protocol definitions

AUTHORING and RUNTIME must remain logically separated.

---

# 41. Project Structure

The conceptual project structure is:

```text
game-loop/
├── SPEC.md
├── AGENTS.md
├── ROADMAP.md
├── docs/
│   └── architecture.md
├── .agent/
│   ├── protocol.md
│   ├── current-task.md
│   ├── discussion.jsonl
│   ├── decisions.md
│   ├── escalations.md
│   └── state.json
├── tasks/
├── src/
├── tests/
├── data/
│   └── lectures/
└── .testsprite/
```

Exact implementation language and framework choices are architecture decisions rather than product requirements unless separately specified.

---

# 42. Unit Testing

Unit tests must verify deterministic components independently.

At minimum:

* State transitions
* Single-choice evaluation
* Multiple-selection evaluation
* Empty-selection rejection
* Trigger-window detection
* Trigger pause semantics
* Timestamp validation
* Same-segment timestamp relocation
* Spacing validation
* Equal-timestamp conflict resolution
* Eligibility-window overlap prevention
* Timing configuration validation
* Intervention-count enforcement
* Submission idempotency
* Stale-event rejection
* Terminal-state behavior
* Seeking rules
* Video-end behavior

---

# 43. Integration Testing

Integration tests must verify interactions between:

* Frontend and backend
* Session state and intervention state
* Activation and state synchronization
* Submission and evaluation
* Submission retries and idempotency
* Seeking and progression
* Lecture loading and runtime state
* Video delivery and browser playback
* Backend session loss and frontend reconciliation

---

# 44. Behavioral Testing

TestSprite must verify observable learner behavior.

At minimum:

1. Video plays normally.
2. Valid intervention trigger pauses the video.
3. The pause occurs at the first detected point inside the tolerance window.
4. The frontend does not intentionally seek to `trigger_time`.
5. Intervention appears.
6. Activation reaches backend.
7. Valid activation becomes `ACTIVE`.
8. Correct submission receives correct feedback.
9. Incorrect submission receives incorrect feedback.
10. Feedback remains visible for at least 3 seconds.
11. Playback resumes after feedback.
12. Submitted intervention cannot be retried.
13. Duplicate transport submission does not create duplicate evaluation.
14. Forward seeking bypasses a pending intervention.
15. Seeking into a pending intervention window activates it.
16. Bypassed intervention does not reactivate on backward seek.
17. Completed intervention does not reactivate on backward seek.
18. Seeking is unavailable while an intervention is `ACTIVE`.
19. Invalid activation is reconciled without creating an invalid logical state.
20. Rejected activation does not repeatedly fire while playback remains inside the same window.
21. Stale events cannot overwrite newer state.
22. Overlapping trigger windows cannot occur under valid configuration.
23. Invalid timing configuration is rejected.
24. Equal-timestamp conflicts resolve deterministically.
25. More than six valid interventions are capped deterministically.
26. Fewer than four valid interventions are accepted.
27. Zero valid interventions cause authoring failure.
28. Backend session loss is handled without inventing state.
29. Video-end behavior is correct for `ACTIVE` interventions.
30. Video-end behavior is correct for remaining `PENDING` interventions.

TestSprite is a verification layer, not a product or architecture authority.

---

# 45. Build Order

Implementation proceeds in this order:

### 1. Foundation

* Project setup
* Shared schemas
* Configuration
* Basic backend/frontend structure

### 2. Static Runtime

* Lecture loading
* Backend video serving
* Video playback
* Basic intervention rendering

### 3. Runtime State

* Session state
* Intervention state machine
* Activation
* Submission
* Idempotency
* Evaluation
* State synchronization
* Stale-event handling

### 4. Intervention UI

* Overlay
* Selection
* Submission
* Feedback
* Minimum feedback duration
* Resume
* Seeking restrictions

### 5. Authoring Pipeline

* Transcript handling
* Gemini integration
* JSON parsing
* Schema validation
* Trigger validation
* Timestamp relocation
* Spacing/conflict resolution
* Intervention-count enforcement

### 6. Real Lecture

* Demonstration lecture
* Real transcript
* Gemini-generated interventions
* Final lecture JSON
* Local video delivery

### 7. Verification

* Unit tests
* Integration tests
* TestSprite behavioral tests
* Bug fixing
* State synchronization verification

### 8. Additional Lecture Data

* Additional valid lecture JSON data using the same runtime architecture

---

# 46. Definition of Done

V0.1 is complete when:

* A real Grade 9 mathematics lecture can be loaded.
* The lecture video is served successfully through the application.
* The lecture has a usable timestamped transcript.
* Gemini can generate structured interventions.
* Generated interventions pass deterministic validation.
* Invalid individual interventions are removed correctly.
* Trigger timestamps satisfy timing constraints.
* Trigger relocation remains within the same transcript segment.
* Eligibility windows cannot overlap under valid configuration.
* Equal-timestamp conflicts resolve deterministically.
* The intervention count never exceeds six.
* Fewer than four valid interventions are accepted.
* Zero valid interventions cause authoring failure.
* The runtime loads the generated lecture JSON.
* Valid triggers pause playback.
* Activation is synchronized with backend state.
* Learners can submit exactly once.
* Submission retries cannot create duplicate evaluations.
* Responses are evaluated deterministically.
* Correct and incorrect feedback work.
* Feedback remains visible for the required minimum duration.
* Playback resumes correctly.
* Forward seeking bypasses pending interventions.
* Seeking into a pending trigger window activates the intervention.
* Seeking is disabled during active interventions.
* Terminal interventions cannot reactivate.
* Stale state cannot overwrite newer state.
* Rejected activation cannot repeatedly trigger while remaining inside the same window.
* Invalid activation is reconciled deterministically.
* Video-end behavior is deterministic.
* Backend session loss is handled explicitly.
* No Gemini call is required during runtime.
* No persistent database is required.
* No arbitrary code/workflow execution exists.
* No lecture-specific runtime hardcoding is required.
* Unit tests pass.
* Integration tests pass.
* TestSprite behavioral verification passes.

---

# 47. Architectural Invariants

The following are mandatory V0.1 invariants:

1. Exactly two intervention types exist:

   * `single_choice`
   * `multiple_selection`

2. Runtime correctness is deterministic.

3. Runtime evaluation does not use an LLM.

4. Gemini is authoring-time only.

5. Gemini is not required during playback.

6. Frontend pause behavior is optimistic.

7. Backend owns authoritative logical state.

8. `COMPLETED` and `BYPASSED` are terminal.

9. Terminal interventions cannot reactivate during the same session.

10. `BYPASSED` does not equal completion or mastery.

11. Seeking is disabled while an intervention is `ACTIVE`.

12. An active intervention cannot be escaped through seeking.

13. `trigger_time` represents the intended pause point.

14. Tolerance is detection tolerance, not an instruction to seek to an alternate pause point.

15. The frontend pauses at the first detected point inside the tolerance window.

16. The frontend does not intentionally seek to `trigger_time` when activating an intervention.

17. A rejected activation cannot repeatedly retry while playback remains inside the same trigger window.

18. The target is approximately 4–6 valid interventions.

19. `MAX_INTERVENTIONS = 6`.

20. Fewer than four valid interventions are acceptable if valid interventions remain.

21. More than six valid interventions are reduced deterministically using original Gemini output order.

22. Zero valid interventions causes lecture-generation failure.

23. Individual invalid interventions are dropped without discarding valid ones.

24. Gemini supplies the pedagogical intervention point and transcript association.

25. Deterministic validation verifies objective technical constraints.

26. Timestamp relocation is allowed only within the same transcript segment.

27. Candidate relocation points are evaluated deterministically.

28. Later conflicting interventions are dropped rather than shifted.

29. Equal trigger timestamps are resolved using original Gemini output order.

30. Runtime eligibility-window overlap is treated as a timing conflict.

31. Valid timing configuration must satisfy:

```text
2 × tolerance < MIN_TRIGGER_GAP
```

32. Timing windows are inclusive at both boundaries.

33. Invalid timing configuration must fail configuration loading.

34. Trigger tolerance is configurable.

35. Feedback must remain visible for at least 3 seconds.

36. `multiple_selection` cannot be submitted with an empty selection.

37. Correct-answer IDs must exist in the intervention's option set.

38. Option IDs must be unique within an intervention.

39. Submission uses an idempotency key.

40. Duplicate logical submissions cannot produce duplicate evaluations.

41. Stale events cannot overwrite newer state.

42. Lecture data is stored as JSON.

43. Runtime does not require persistent state.

44. Local video is served through the application's backend rather than exposing arbitrary filesystem paths.

45. Runtime does not execute arbitrary code or external workflows.

46. Runtime does not perform open-ended semantic grading.

47. AI generation may be non-deterministic.

48. Post-generation validation and runtime evaluation are deterministic.

49. The frontend must not independently create authoritative logical state.

50. A rejected activation must not create a local terminal state.

51. Video-end behavior is explicitly defined for `ACTIVE` and `PENDING` interventions.

52. No requirement may be silently changed during implementation.

53. Ambiguous or contradictory requirements must be escalated rather than silently resolved.

---

# 48. Change Control

`SPEC.md` is authoritative for V0.1 product behavior.

Agents may:

* Implement specified behavior.
* Refactor implementation details without changing observable behavior.
* Improve internal structure while preserving architectural invariants.
* Add tests.
* Fix defects that clearly violate this specification.

Agents must escalate:

* Contradictory requirements.
* Missing architectural decisions that materially affect behavior.
* Requirements that cannot be implemented consistently.
* Changes that affect state semantics.
* Changes that affect authority boundaries.
* Changes that affect interaction semantics.
* Changes that expand V0.1 scope.

Agents must not silently:

* Add new interaction types.
* Add runtime AI evaluation.
* Change deterministic evaluation.
* Change terminal-state semantics.
* Allow active interventions to be bypassed through seeking.
* Change bypass semantics.
* Shift conflicting intervention timestamps.
* Change timing invariants.
* Introduce persistent learner state.
* Introduce arbitrary code execution.
* Introduce workflow execution.
* Add open-ended semantic grading.
* Change the frontend/backend authority boundary.
* Expand the product scope.
* Change API/state semantics without updating the authoritative architecture documentation.
* Invent behavior for unspecified failure cases.

When a requirement is ambiguous, the agent must escalate the ambiguity to the product/architecture authority rather than inventing a rule.

---

# 49. V0.2 Scope & Architecture Overview

V0.2 expands `game-loop` from a standalone educational player into an **embeddable B2B learning & inquiry engine**.

In V0.2:
1. **Host-Owned Playback**: The B2B client owns the video player and learning platform. `game-loop` embeds as an overlay / sidecar engine, interacting with the player through a decoupled `VideoPlayerAdapter`.
2. **Scientific Inquiry Sandbox**: Beyond static multiple-choice questions, learners engage in inquiry-driven interventions:
   $$\text{Observe} \longrightarrow \text{Hypothesize} \longrightarrow \text{Experiment / Code} \longrightarrow \text{Analyze} \longrightarrow \text{Conclude}$$
3. **Adaptive Difficulty Engine**: Deterministically resolves tiered variants (Tier 1: Guided/Scaffolded, Tier 2: Standard Application, Tier 3: Edge Case / Debugging) tailored to the learner's concept mastery and streak.
4. **B2B Multi-Tenant Identity & Telemetry**: Every runtime session binds `client_id` and `external_user_id`, logging structured telemetry events for LMS integration.
5. **Client-Side Sandbox Execution**: Arbitrary code execution occurs strictly client-side (sandboxed in browser / Web Worker) to maintain backend zero-trust security invariants.

---

# 50. VideoPlayerAdapter Contract

To decouple `game-loop` from any specific player technology (HTML5 video, Video.js, JWPlayer, YouTube IFrame, Vimeo, or custom Canvas players), the client or embedding layer implements `VideoPlayerAdapter`:

```typescript
export interface VideoPlayerAdapter {
  play(): Promise<void>;
  pause(): void;
  getCurrentTime(): number;
  seekTo(seconds: number): void;
  getDuration(): number;
  onTimeUpdate(callback: (currentTime: number) => void): () => void;
  onSeeking(callback: (targetTime: number) => void): () => void;
  onSeeked?(callback: () => void): () => void;
  onEnded?(callback: () => void): () => void;
  destroy(): void;
}
```

### Invariants:
1. `game-loop` must not proxy, stream, or re-encode video media directly.
2. The adapter must report playback position monotonically (modulo seeks).
3. The host player must honor `pause()` immediately when an intervention triggers.
4. During an `ACTIVE` intervention, seeking must be disabled or rebound to the lock position.

---

# 51. Scientific Inquiry Sandbox Specification

V0.2 introduces two inquiry interaction types:
* `predict_and_verify`: The learner predicts what a given code snippet / system state will produce (hypothesis), runs or modifies code in a sandboxed runner, observes output, and confirms understanding.
* `inquiry_sandbox`: An open-ended structured investigation where the learner writes or debugs code to meet automated test cases.

### The 5-Phase Inquiry Loop:
1. **Observation**: Learner inspects the problem context and initial code snippet.
2. **Hypothesis Formulation**: Learner selects a hypothesis from finite options before executing code.
3. **Experimentation**: Learner runs the sandboxed runner (`MiniPythonInterpreter` or `javascript_eval`), observing live console output.
4. **Analysis & Verification**: Code runner executes automated test assertions (`TestCase[]`) deterministically client-side.
5. **Conclusion & Submission**: Learner submits the combined hypothesis and verification result to the backend.

### Execution Security:
* All code execution is sandboxed entirely on the client.
* The backend does not run user-submitted code in production containers or eval strings.

---

# 52. Dynamic Adaptive Difficulty & Learner Model

### Tiers:
* **Tier 1 (Guided / Scaffolded)**: Explicit hints, reduced distractor count, simplified starter code.
* **Tier 2 (Standard Application)**: Core curriculum difficulty, baseline test cases.
* **Tier 3 (Advanced / Edge Case)**: Debugging broken code, edge cases, fewer hints.

### Learner Profile State:
```python
class LearnerProfile(BaseModel):
    user_id: str
    client_id: str = "default_client"
    concept_mastery: dict[str, float] = Field(default_factory=dict) # 0.0 to 1.0
    streak: int = 0                                                 # Positive = correct, negative = incorrect
    friction_index: float = 1.0
    total_interventions: int = 0
    total_correct: int = 0
```

### Deterministic Tier Selection Algorithm:
1. If explicit `tier_override` is supplied in the session request, use it.
2. Otherwise, look up concept mastery $M \in [0.0, 1.0]$ (defaults to 0.5 for fresh concepts).
3. If $M \ge 0.75$ and $\text{streak} \ge 2$: Select **Tier 3**.
4. If $M \le 0.35$ or $\text{streak} \le -2$: Select **Tier 1**.
5. Otherwise: Select **Tier 2**.

### Mastery Update Formula:
On submission for concept $C$ at tier $T \in \{1, 2, 3\}$:
$$\Delta = \begin{cases} +0.10 \times \frac{T}{2.0} & \text{if correct} \\ -0.10 \times \frac{T}{2.0} & \text{if incorrect} \end{cases}$$
$$M_{\text{new}} = \max(0.0, \min(1.0, M_{\text{prev}} + \Delta))$$

---

# 53. B2B Multi-Tenant Identity & Telemetry

### Identity Context:
* Sessions are created with `client_id` (e.g. `"acme_lms"`) and `external_user_id` (e.g. `"learner_42"`).
* Multiple tenants maintain isolated learner profiles in `LearnerService`.

### Telemetry Events:
The engine produces structured telemetry events:
* `intervention_triggered`: Window entered and optimistic pause triggered.
* `hypothesis_formulated`: Learner selected hypothesis option.
* `code_executed`: Client code runner executed tests.
* `intervention_evaluated`: Final evaluation result computed with `mastery_delta` and `tier`.
* `playback_resumed`: Video playback resumed after feedback display.

---

# 54. V0.2 API Contract Extensions

### 1. Create Session
`POST /api/sessions`
```json
{
  "lecture_id": "python_basics_lists",
  "client_id": "acme_lms",
  "external_user_id": "learner_42",
  "tier_override": 2
}
```

### 2. Submit Inquiry Experiment
`POST /api/sessions/{session_id}/experiment`
```json
{
  "intervention_id": "py_1",
  "idempotency_key": "exp_key_123",
  "hypothesis_answer": "h_b",
  "code_submitted": "a = [1,2,3]\nb = a\nb.append(4)\nprint(a)",
  "test_results": [
    { "name": "Output includes 4", "passed": true, "actual_output": "[1, 2, 3, 4]", "expected_output": "[1, 2, 3, 4]" }
  ],
  "passed_tests": true
}
```

Response:
```json
{
  "is_correct": true,
  "feedback": "Correct! b = a makes b an alias to the same list.",
  "submitted_answer": "h_b",
  "tier": 2,
  "mastery_delta": 0.1,
  "suggested_next_tier": 3,
  "session_state": { ... }
}
```

### 3. Get Learner Profile
`GET /api/learners/{client_id}/{user_id}`
Returns `LearnerProfile` with current concept mastery map, streak, and intervention totals.

---

# 55. V0.3 Specification: Non-Blocking Immersion, Open-Ended Semantic Grading & Persistent Multi-Tenancy

**Status:** APPROVED FOR PLANNING & IMPLEMENTATION  
**Target Version:** `game-loop` V0.3  
**Authority:** Extends and refines V0.1/V0.2 invariants for open-ended assessment, asynchronous evaluation, policy-governed skipping, and embedded persistence.

---

## 55.1 Architectural Invariants & Guarantees

1. **Decoupled Skip Policy vs. Playback Cue:**
   - Whether an intervention is skippable is governed strictly by the intervention/tenant policy model.
   - How an upcoming intervention is communicated is governed strictly by non-blocking player UX. The two mechanisms must not be conflated.
2. **Asynchronous Semantic Evaluation with Controlled Resumption:**
   - Open-ended answers are evaluated asynchronously by Gemini against an authored rubric.
   - Resumption policy is explicitly configurable per intervention: `IMMEDIATE_OPTIMISTIC` for formative learning vs. `WAIT_FOR_RESULT` for mandatory assessment.
   - Submissions are uniquely identified and tracked via an explicit status lifecycle (`PENDING`, `COMPLETED`, `TIMED_OUT`, `FAILED`).
   - Timed-out foreground evaluations fall back to explicitly labeled self-assessment without blocking, while late AI results are reconciled idempotently without corrupting newer session state.
3. **Missing Evidence Skip Semantics:**
   - A skipped question transitions the intervention to `SKIPPED`.
   - Mastery is left unmodified ($\Delta M = 0$). Skips are recorded as explicit telemetry events and treated by the adaptation engine as **missing evidence**, not as incorrect answers or negative mastery penalty.
4. **Embedded Persistent Multi-Tenancy:**
   - In-memory dictionaries are replaced with an embedded, zero-infrastructure SQLite database (via SQLAlchemy / aiosqlite).
   - Sessions, submissions, learner profiles, and audit telemetry persist across server restarts, scoped by `client_id`.

---

## 55.2 Extended Runtime State Machine

In V0.3, interventions support two additional states: `EVALUATING` and `SKIPPED`.

```text
               ┌─────────────┐
               │   PENDING   │
               └──────┬──────┘
                      │
           ┌──────────┴──────────┐
           │ (valid activation)   │ (forward seek past trigger under SKIPPABLE)
           ▼                     ▼
     ┌───────────┐         ┌───────────┐
     │  ACTIVE   │         │ BYPASSED  │  (Terminal)
     └─────┬─────┘         └───────────┘
           │
     ┌─────┼──────────────────────────────┐
     │     │                              │
     │     │ (submit open-ended)          │ (skip under SKIPPABLE policy)
     │     ▼                              ▼
     │   ┌─────────────┐            ┌───────────┐
     │   │ EVALUATING  │            │  SKIPPED  │  (Terminal)
     │   └──────┬──────┘            └───────────┘
     │          │
     │          │ (grading completed / self-assessed)
     │          ▼
     │   ┌─────────────┐
     └──►│  COMPLETED  │  (Terminal)
(submit  └─────────────┘
 structured)
```

### Allowed Transitions:
* `PENDING → ACTIVE`: Playback position enters trigger window $[T - \epsilon, T + \epsilon]$.
* `PENDING → BYPASSED`: Forward seek past window (only permitted if policy is `SKIPPABLE`).
* `ACTIVE → COMPLETED`: Instant deterministic submission (MCQ, multiple selection, or inquiry code runner verification).
* `ACTIVE → EVALUATING`: Submission of an open-ended freeform response awaiting asynchronous AI grading.
* `ACTIVE → SKIPPED`: Learner explicitly triggers skip (only permitted if policy is `SKIPPABLE`).
* `EVALUATING → COMPLETED`: Asynchronous AI evaluation arrives or learner completes a timed-out self-assessment rubric.

`COMPLETED`, `SKIPPED`, and `BYPASSED` are terminal states. Once an intervention reaches a terminal state, backward seeking cannot re-activate it.

---

## 55.3 Checkpoint & Skip Policy Model

Interventions and B2B tenants configure an explicit `InterventionPolicy`:

```python
class InterventionPolicy(str, Enum):
    SKIPPABLE = "skippable"
    REQUIRED = "required"
    REQUIRED_WITH_RETRY = "required_with_retry"
```

| Policy | Learner Action | Playback Resumption | Seeking Guard | Mastery Effect |
|---|---|---|---|---|
| `SKIPPABLE` | Learner may answer or click **Skip**. | Immediate on submit or skip. | Forward seek past window transitions to `BYPASSED`. | Submit: $\pm \Delta M$.<br>Skip: $\Delta M = 0$ (missing evidence). |
| `REQUIRED` | Learner must submit an answer. Skip button is absent. | Governed by `resumption_policy`. | Forward seek past trigger point is blocked/clamped. | Submit: $\pm \Delta M$. |
| `REQUIRED_WITH_RETRY` | Learner must achieve a passing score ($S \ge \text{passing\_score}$). | Paused until passing score achieved. | Seeking disabled until passed. | Submit: updates streak and mastery. Dropped tier on successive failures. |

Backend authority enforces policy rules on every mutation request:
* If a learner attempts to `skip` an intervention marked `REQUIRED` or `REQUIRED_WITH_RETRY`, the backend rejects the request with HTTP 403 `PolicyViolationError`.
* If a forward seek bypasses a `REQUIRED` intervention, the backend sync endpoint rejects the bypass and clamps playback to the required trigger window.

---

## 55.4 Open-Ended Answers & Submission Lifecycle

### Submission Record Schema:
```python
class SubmissionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"

class SubmissionRecord(BaseModel):
    submission_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    intervention_id: str
    idempotency_key: str
    user_answer: str
    status: SubmissionStatus = SubmissionStatus.PENDING
    resumption_policy: str = "immediate_optimistic" # or "wait_for_result"
    ai_score: Optional[float] = None                # 0.0 to 1.0
    is_correct: Optional[bool] = None
    formative_feedback: Optional[str] = None
    misconceptions_detected: list[str] = Field(default_factory=list)
    self_assessed: bool = False
    mastery_applied: bool = False
    created_at: datetime
    evaluated_at: Optional[datetime] = None
    evaluation_latency_ms: Optional[int] = None
```

### The 4-Stage Asynchronous Lifecycle:
1. **Immediate Acknowledgment (0–100ms):**
   - Backend persists `SubmissionRecord` with `status = PENDING`.
   - Returns HTTP 202 Accepted with `submission_id`.
   - Frontend behavior:
     - If `resumption_policy == "immediate_optimistic"`: Video resumes immediately. A subtle status chip *"Evaluating your reasoning..."* displays in the player status area.
     - If `resumption_policy == "wait_for_result"`: Video remains paused displaying an animated shimmer ticker.
2. **Asynchronous Evaluation Dispatch:**
   - Background worker invokes Gemini with structured rubric prompt:
     - `question`, `rubric.key_concepts`, `rubric.misconceptions`, `rubric.reference_answer`, `user_answer`.
   - Evaluation hash cache: `SHA256(intervention_id + normalized_answer)` checked in SQLite; cached entries return in $< 10$ms.
3. **Foreground Timeout & Labeled Self-Assessment (Default: 5000ms):**
   - If AI evaluation does not arrive within the configurable UX threshold (default 5.0s):
     - The foreground stops waiting.
     - The intervention status updates to `TIMED_OUT`.
     - An explicitly labeled alternative appears:
       > *"AI evaluation is taking longer than expected. You can review the reference rubric below to self-assess, or continue watching."*
     - If the learner self-assesses (e.g. clicks "I got this right"), `self_assessed = True`, mastery delta is recorded with source tag `self_assessment`, and intervention transitions to `COMPLETED`.
4. **Late Result Arrival & Stale State Protection:**
   - If Gemini evaluation completes after the foreground timeout:
     - Backend updates `SubmissionRecord.status = COMPLETED`, records `ai_score` and `formative_feedback`.
     - **Mastery Idempotency Guard**: If `mastery_applied == True` (because learner already self-assessed or completed), the backend does **not** re-apply mastery updates.
     - **Non-Intrusive Delivery**: If the learner is still playing video, the feedback card does **not** interrupt playback with a blocking modal. Instead, a non-blocking toast/card anchored to the completed intervention is delivered, allowing the student to inspect feedback at their convenience.

---

## 55.5 Non-Blocking Playback UX (Anti-Ad Immersion)

1. **Timeline Checkpoint Pips:**
   - Every scheduled intervention is marked on the player progress bar with a subtle visual marker (dot/pip).
   - Distinct visual treatments:
     - Hollow circle: `SKIPPABLE` practice checkpoint.
     - Solid diamond: `REQUIRED` compliance checkpoint.
2. **Approaching Interaction Cue:**
   - When the playback position enters $[T - 6.0\text{s}, T]$, a subtle non-blocking glowing aura appears on the approaching timeline pip.
   - Does not obscure video content, show countdown timers, or force learners to wait.
   - Informs the learner that a reflection point is approaching naturally with the lecture flow.
3. **Audio Decrescendo:**
   - 300ms prior to the physical pause at `trigger_time`, player audio gracefully fades down to 0, eliminating harsh jarring stops.

---

## 55.6 Embedded Persistence Architecture (SQLite)

V0.3 transitions from volatile Python dictionaries to SQLite:
- Single local database file: `data/game_loop.db`.
- Managed via SQLAlchemy ORM with async connection pooling (`aiosqlite`).
- Write-through memory cache for active sessions guarantees sub-millisecond API response times while ensuring crash-resilient persistence across server restarts.

### Database Tables:
* `tenants`: Multi-tenant configuration, client name, default skip policies, API keys.
* `sessions`: Session ID, lecture ID, client ID, external user ID, current state version, created/updated timestamps.
* `session_interventions`: Active/completed/skipped states, selected tier, submission idempotency keys, results.
* `submissions`: Detailed submission records, open-ended answers, evaluation statuses, latency telemetry.
* `learner_profiles`: Concept mastery vectors, streaks, friction indices, total intervention counts.
* `telemetry_events`: Structured event log (`intervention_triggered`, `intervention_skipped`, `evaluation_completed`, `rubric_self_assessed`).

---

## 55.7 V0.3 API Contract Additions

### 1. Submit Open-Ended Freeform Answer
`POST /api/sessions/{session_id}/submissions/open-ended`
```json
{
  "intervention_id": "math_proof_step_3",
  "idempotency_key": "sub_uuid_456",
  "user_answer": "Because angles on a straight line add up to 180 degrees, angle ABC must be 65."
}
```
Response (HTTP 202 Accepted):
```json
{
  "submission_id": "sub_rec_789",
  "status": "pending",
  "resumption_policy": "immediate_optimistic",
  "message": "Answer received. Evaluating asynchronously.",
  "session_state": { ... }
}
```

### 2. Poll / Stream Submission Status
`GET /api/sessions/{session_id}/submissions/{submission_id}`
Response (HTTP 200 OK):
```json
{
  "submission_id": "sub_rec_789",
  "status": "completed",
  "ai_score": 0.95,
  "is_correct": true,
  "formative_feedback": "Excellent reasoning! You correctly identified the straight-angle theorem.",
  "misconceptions_detected": [],
  "evaluation_latency_ms": 1420
}
```

### 3. Skip Intervention
`POST /api/sessions/{session_id}/interventions/{intervention_id}/skip`
```json
{
  "reason": "learner_choice"
}
```
Response:
* HTTP 200 OK if policy is `SKIPPABLE` (transitions to `SKIPPED`, video resumes, $\Delta M = 0$).
* HTTP 403 Forbidden if policy is `REQUIRED` (`"Cannot skip required intervention"`).

### 4. Self-Assess Timed-Out Submission
`POST /api/sessions/{session_id}/submissions/{submission_id}/self-assess`
```json
{
  "self_assessed_correct": true
}
```


