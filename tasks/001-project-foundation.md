# Task 001 - Project Foundation

## Objective

Create the minimal project foundation required to begin V0.1 implementation without inventing architecture.

## Authority

Follow, in order:

1. `SPEC.md`
2. `docs/architecture.md`
3. this task

If this task conflicts with either higher-level document, stop and escalate.

## Scope

Establish:

- monorepo structure
- React + TypeScript frontend
- FastAPI + Python backend
- basic frontend/backend communication
- test directories
- lecture-data directories
- local environment configuration
- secret-handling conventions

## Required structure

```text
game-loop/
|- SPEC.md
|- AGENTS.md
|- ROADMAP.md
|- Codex_to_copilot.md
|- Copilot_to_codex.md
|- docs/
|  `- architecture.md
|- tasks/
|  |- TEMPLATE.md
|  `- 001-project-foundation.md
|- frontend/
|- backend/
|- data/
|  `- lectures/
|- tests/
`- .testsprite/
```

## Constraints

- Do not add a database.
- Do not add runtime Gemini calls.
- Do not create an authoring service yet.
- Do not add microservices.
- Do not invent authentication requirements.
- Do not expose arbitrary filesystem access.
- Do not commit or print API secret values.
- Do not modify `SPEC.md` to make implementation easier.
- Do not implement future adaptive-learning features.

## Acceptance criteria

### Structure
- Required directories/files exist.
- Frontend and backend are independently runnable.

### Backend
- FastAPI application starts.
- A minimal health/status endpoint exists if needed for connectivity verification.
- Backend dependency/environment setup is reproducible.

### Frontend
- React + TypeScript application starts.
- Frontend can make a successful request to backend.
- Basic error handling exists for backend-unavailable state.

### Tests
- Test infrastructure is runnable.
- At least one meaningful backend foundation test exists.
- At least one frontend foundation test exists if frontend test infrastructure is established in this task.

### Secrets
- Environment-based secret loading is established.
- No API key value appears in source, docs, task files, logs, or communication files.

## Verification

Run the project's foundation checks and record:
- commands
- pass/fail
- any deviations

Do not expand this task into runtime behavior.

## Completion report

Codex should report:

1. What was implemented.
2. What was tested.
3. Test results.
4. Any deviations from the task.
5. Any unresolved ambiguity.
