-- Schema-only fixture extracted from a read-only V0.3 database copy. No rows included.

CREATE TABLE completed_submissions (
                        session_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        PRIMARY KEY (session_id, idempotency_key),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

CREATE TABLE learner_profiles (
                        client_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        concept_mastery_json TEXT NOT NULL,
                        streak INTEGER NOT NULL DEFAULT 0,
                        friction_index REAL NOT NULL DEFAULT 1.0,
                        total_interventions INTEGER NOT NULL DEFAULT 0,
                        total_correct INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (client_id, user_id)
                    );

CREATE TABLE session_interventions (
                        session_id TEXT NOT NULL,
                        intervention_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        PRIMARY KEY (session_id, intervention_id),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

CREATE TABLE sessions (
                        session_id TEXT PRIMARY KEY,
                        lecture_id TEXT NOT NULL,
                        client_id TEXT NOT NULL DEFAULT 'default_client',
                        external_user_id TEXT NOT NULL DEFAULT 'default_learner',
                        tier_override INTEGER,
                        version INTEGER NOT NULL DEFAULT 1,
                        active_intervention_id TEXT,
                        active_intervention_tier INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

CREATE TABLE submissions (
                        submission_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        intervention_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        user_answer TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        resumption_policy TEXT NOT NULL DEFAULT 'immediate_optimistic',
                        ai_score REAL,
                        is_correct INTEGER,
                        formative_feedback TEXT,
                        misconceptions_json TEXT DEFAULT '[]',
                        self_assessed INTEGER NOT NULL DEFAULT 0,
                        mastery_applied INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        evaluated_at TEXT,
                        latency_ms INTEGER,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

CREATE TABLE telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    );

CREATE TABLE tenants (
                        client_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        default_policy TEXT NOT NULL DEFAULT 'skippable',
                        created_at TEXT NOT NULL
                    );
