# game-loop Architecture

## 1. Status

- Project: `game-loop`
- Version: V0.1
- Architecture status: Architecture baseline
- Product authority: `SPEC.md`
- Scope: Mathematics proof-of-concept
- Runtime model: deterministic, pre-authored interventions
- Gemini role: authoring-time generation only

This document records the architecture decisions made for V0.1. It does not override `SPEC.md`.

---

## 2. Architectural principle

V0.1 is intentionally a **deterministic runtime around an AI-assisted authoring pipeline**.

The core system boundary is:

```text
Video + timestamped transcript
        |
        v
      Gemini
        |
        v
Candidate interventions
        |
        v
Deterministic validation
        |
        v
Final lecture JSON
        |
        v
React frontend <---- REST/JSON ----> FastAPI backend
        |
        v
Local video playback + learner interaction
```

Gemini is allowed to generate pedagogical proposals. The application decides what is executable.

---

## 3. Product/runtime model

The V0.1 learner experience is:

```text
WATCH
  -> INTERRUPTION
  -> ACT
  -> EVALUATE
  -> FEEDBACK
  -> RESUME
  -> next fixed intervention
```

Every learner receives the same authored intervention sequence and trigger timestamps.

A learner's answer affects:
- deterministic correctness evaluation
- selected authored feedback

A learner's answer does **not** affect:
- which intervention comes next
- trigger timestamps
- lesson structure
- runtime generation
- backend execution rules

V0.1 therefore does not implement runtime personalization or adaptive intervention selection.

---

## 4. Repository/application structure

Use a monorepo with separate frontend and backend applications:

```text
game-loop/
├── SPEC.md
├── AGENTS.md
├── ROADMAP.md
├── Codex_to_copilot.md
├── Copilot_to_codex.md
├── docs/
│   └── architecture.md
├── tasks/
│   ├── TEMPLATE.md
│   └── 001-project-foundation.md
├── frontend/
├── backend/
├── data/
│   └── lectures/
├── tests/
└── .testsprite/
```

The architecture intentionally does not introduce a database, message broker, microservices, or separate authoring service for V0.1.

---

## 5. Technology choices

### Frontend

- React
- TypeScript
- Browser video element / local HTTP video
- Frontend owns presentation and physical playback behavior

### Backend

- FastAPI
- Python
- REST/HTTP JSON
- Backend owns authoritative logical state and deterministic evaluation

### Storage

- Static lecture JSON files in `data/lectures/`
- Local lecture media served through the backend
- In-memory runtime sessions
- No database in V0.1

---

## 6. State ownership

The system uses a deliberate hybrid ownership model.

### Backend owns

- intervention lifecycle state
- current intervention
- intervention activation validity
- deterministic evaluation
- progression
- idempotency
- session state
- state versions/sequence numbers
- stale-event rejection
- authoritative logical interpretation of learner actions

### Frontend owns

- video playback
- detecting the local playback trigger window
- pausing/resuming the player
- visible UI state
- answer selections before submission
- loading/error animations and presentation
- rendering feedback

Rule:

> The frontend controls how an action is presented; the backend controls what the action means.

---

## 7. API architecture

The frontend communicates with the backend through REST/HTTP JSON.

The API is intentionally narrow and domain-oriented. V0.1 should expose operations for:

1. loading a lecture
2. creating a session
3. activating an intervention
4. retrieving authoritative session state
5. submitting an answer
6. evaluating/progressing the intervention
7. rejecting stale or invalid events

The backend must not expose arbitrary filesystem access or arbitrary execution.

### Request identity

Runtime mutation requests use:
- session ID
- intervention ID where applicable
- state version/sequence information
- idempotency key for submissions

The backend must treat repeated submission requests with the same idempotency key as the same logical submission.

---

## 8. Runtime state machine

Each intervention has:

```text
PENDING -> ACTIVE -> COMPLETED
PENDING -> BYPASSED
```

`COMPLETED` and `BYPASSED` are terminal.

For normal V0.1 interaction:

```text
PENDING
   |
   | valid activation
   v
ACTIVE
   |
   | valid answer
   v
COMPLETED
```

The frontend may physically detect an intervention, but only the backend can establish its authoritative logical state.

---

## 9. Video/intervention synchronization

Each intervention has a trigger timestamp.

The frontend continuously compares playback time with the configured trigger window:

```text
[T - epsilon, T + epsilon]
```

When the first local playback position enters the window, the frontend pauses the video and requests activation.

The frontend does **not** seek the video to the exact trigger timestamp.

The backend validates the activation against the authoritative session/intervention state.

This separates:
- physical timing detection: frontend
- logical activation: backend

---

## 10. Seeking

Seeking is allowed, but it cannot silently bypass an outstanding intervention.

The backend remains authoritative when a seek causes a stale, invalid, or out-of-order interaction.

The exact stale-event and bypass semantics follow `SPEC.md`; no additional behavior should be invented by agents.

---

## 11. Intervention behavior

V0.1 supports exactly two intervention types:

- `single_choice`
- `multiple_selection`

A learner submits one structured response.

Evaluation is deterministic:
- exact structured response matching
- no semantic LLM grading
- no runtime Gemini evaluation

Both correct and incorrect responses use authored feedback.

Normal lifecycle:

```text
activate
  -> answer
  -> deterministic evaluation
  -> authored feedback
  -> resume video
```

Incorrect answers do not trigger retries or branching in V0.1.

---

## 12. Lecture representation

One lecture is one self-contained JSON artifact:

```text
data/lectures/<lecture-id>.json
```

It contains, at minimum:

- lecture metadata
- video reference
- timestamped transcript
- interventions

The transcript uses sentence-level segments with:
- start time
- end time
- text

Interventions contain the fields defined by `SPEC.md`, including:
- id
- trigger time
- concept
- difficulty
- type
- question
- options
- correct answer
- correct feedback
- incorrect feedback

The JSON file is the runtime content source.

---

## 13. Authoring architecture

The authoring pipeline is:

```text
video
  -> transcript
  -> timestamped transcript + basic metadata
  -> Gemini
  -> candidate intervention set
  -> schema validation
  -> timestamp validation
  -> spacing/conflict validation
  -> count validation
  -> final intervention set
  -> lecture JSON
```

### Gemini input

V0.1 sends Gemini:

- full timestamped transcript
- subject
- grade
- duration
- allowed intervention types
- target/max count
- authoring constraints

No separate rich pedagogical metadata layer is required for V0.1.

### Gemini responsibility

Gemini proposes:
- intervention content
- concepts
- difficulty
- questions/options
- candidate timestamps
- feedback

### Application responsibility

Deterministic application code decides:
- schema validity
- timestamp validity
- relocation within the same transcript segment when permitted
- spacing/conflict resolution
- intervention count
- final executable set

This is a hard boundary.

---

## 14. Gemini failure policy

Gemini is non-deterministic.

For a complete generation failure:
1. retry the identical request once
2. if the retry fails, fail lecture generation

There are no additional automatic retries.

Invalid individual interventions may be dropped while valid interventions are preserved.

If zero valid interventions remain, lecture generation fails.

The system does not repeatedly regenerate merely to reach the target intervention count.

---

## 15. Intervention timing validation

An intervention timestamp must belong to its referenced transcript segment.

If the timestamp is unsuitable:
- candidate points are considered within the same segment
- candidates are considered in ascending order
- the first valid candidate is selected
- if none is valid, the intervention is dropped

Spacing follows the SPEC's `MIN_TRIGGER_GAP` rules.

The validation configuration is invalid if:

```text
2 × tolerance >= MIN_TRIGGER_GAP
```

The earlier intervention wins conflicts. Equal timestamps preserve original Gemini output order.

---

## 16. Intervention count

The authored result must contain at most six valid interventions.

V0.1 accepts:
- fewer than four valid interventions
- four to six valid interventions

If Gemini produces more than six valid interventions, the first six valid interventions in original Gemini output order are retained.

---

## 17. Persistence and failure boundaries

### Runtime

Sessions are in memory.

A backend restart may lose active session state. V0.1 does not introduce persistent session recovery.

### Content

Lecture JSON and media are persistent repository/local files.

### Security

Secrets such as Gemini/TestSprite API keys must never be copied into:
- architecture documents
- task documents
- agent communication files
- source-controlled examples

The repository may use the configured local secret mechanism, but secret values must never be reproduced.

---

## 18. Multiple tabs and concurrency

Multiple tabs are supported logically through session/intervention/state identifiers.

The backend is authoritative when requests race or become stale.

V0.1 does not promise visual synchronization between multiple browser tabs.

The architecture uses state versions/sequence numbers and idempotency to prevent stale or duplicate mutations from silently changing authoritative state.

---

## 19. Testing architecture

Testing is layered.

### Unit tests

Test deterministic domain rules:
- schema validation
- timestamp validation
- spacing
- count limits
- evaluation
- state transitions
- idempotency
- stale-event rejection

### Integration tests

Test:
- API endpoints
- lecture loading
- session creation
- activation
- submission
- progression
- restart/session-loss behavior

### Behavioral tests

Test the observable learner flow:
- video pauses at intervention
- interaction appears
- correct answer gives correct feedback
- incorrect answer gives incorrect feedback
- video resumes
- interventions occur in fixed order
- seeking cannot silently bypass required state

### TestSprite

TestSprite is the behavioral verification layer, not the architectural authority.

---

## 20. Agent boundaries

### Codex

Codex is the primary builder.

Codex may:
- implement the current task
- add tests
- make implementation-level decisions that do not alter architecture

Codex must not:
- redefine product requirements
- silently change architectural decisions
- add infrastructure because it seems useful
- change the runtime AI boundary
- invent unspecified behavior

### Copilot

Copilot is an independent reviewer.

Copilot checks:
- implementation against SPEC
- implementation against architecture
- tests and edge cases
- unintended complexity
- security/secret handling
- architectural drift

Copilot does not become a second product authority.

### TestSprite

TestSprite verifies observable behavior and reports failures.

### Human

The human remains the authority for:
- product scope
- requirement changes
- architecture changes
- unresolved ambiguities

---

## 21. Change control

Priority order:

```text
SPEC.md
  >
docs/architecture.md
  >
ROADMAP.md
  >
task files
  >
implementation
```

If a lower-level artifact conflicts with a higher-level artifact, the lower-level artifact must be corrected.

An ambiguous requirement must be escalated rather than invented.

Architecture changes must be explicit and documented.

---

## 22. Explicit V0.1 non-goals

Do not introduce:

- runtime Gemini generation
- runtime LLM evaluation
- adaptive intervention ordering
- learner-specific intervention generation
- branching lessons
- retry loops
- semantic/open-ended grading
- database persistence
- arbitrary code execution
- stateful simulations
- workflow engines
- microservices
- unnecessary cloud infrastructure
- rich pedagogical metadata authoring
- production-scale multi-tenant infrastructure

These can be reconsidered after V0.1 evidence exists.

---

## 23. Decision log

| # | Decision | Choice |
|---|---|---|
| 1 | Repository structure | Monorepo, separate frontend/backend |
| 2 | Stack | React + TypeScript / FastAPI + Python |
| 3 | State ownership | Hybrid |
| 4 | API | REST/HTTP JSON |
| 5 | Persistence | Static JSON + in-memory sessions |
| 6 | Product authority conflict | Current SPEC remains authoritative |
| 7 | Learner sequence | Fixed intervention sequence |
| 8 | Gemini authority | Gemini proposes; backend validates/decides |
| 9 | Gemini authoring context | Timestamped transcript + basic metadata |
| 10 | Lecture storage | One complete JSON per lecture |
| 11 | Incorrect answer | Predefined feedback, then resume |
| 12 | Correct answer | Predefined feedback, then resume |
| 13 | Playback detection | Frontend trigger-window checking |
| 14 | Seeking | Must not silently bypass outstanding intervention |

The remaining implementation-level choices should follow `SPEC.md` and these principles rather than trigger another architecture redesign.

---

## 24. Deferred decisions

The following are intentionally deferred:

- runtime adaptive learning
- runtime Gemini
- learner modeling
- branching/retry pedagogy
- richer pedagogical metadata
- database/session persistence
- multiple lesson management at production scale
- authentication/authorization beyond what V0.1 requires

These should be introduced only when a concrete requirement justifies them.
