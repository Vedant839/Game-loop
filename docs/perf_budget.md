# Database round-trip budget

This budget counts DB-API statement executions on the SQLite test path. Each
statement represents one Turso request when the same repository call runs
against `turso-serverless==0.1.0`; transaction and stream lifecycle requests
are listed separately below. Counts are measured with the counting connection
in `tests/backend/test_round_trip_budget.py`.

| Hot path | Measured statements | Turso request estimate | Notes |
|---|---:|---:|---|
| Create session | 5 | 8 | Session row and four checkpoint-state rows, in one transaction. |
| Activate, cold learner | 7 | 14 | Profile read, profile insert, then five session/state writes. Warm profile cache: 5 statements / 8 requests. |
| Sync, state changes | 5 | 8 | Session row and four checkpoint-state rows. A sync that changes no state uses 0 statements. |
| Submit answer | 4 | 7 | Session row, changed checkpoint state, new idempotency result, and learner profile in one transaction. |
| Hint | N/A | N/A | The hint endpoint is not implemented yet; budget it when the endpoint is added. |

The submit path previously rewrote every checkpoint state and every saved
idempotency result. It now writes only the changed checkpoint and new result,
which reduces the measured transaction from 7 statements to 4 while preserving
the atomic session, mastery, and idempotency update.

For Turso, `Database.execute_batch` executes each statement separately. A
transactional DML batch of *N* statements costs *N + 3* HTTP requests: `BEGIN`,
the *N* statements, `COMMIT`, and stream close. A cold activation also reads
the learner profile (one read plus close) and creates it when absent (begin,
insert, commit, close). These request estimates follow the installed
`turso-serverless==0.1.0` DB-API implementation; they are not measurements
against a remote Turso database.

Skip telemetry is scheduled with FastAPI `BackgroundTasks`, so the telemetry
insert does not add a database statement to the learner's skip response path.
