"""Embedded SQLite persistence manager for game-loop V0.3."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from backend.config import get_settings

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite database manager for game-loop sessions, profiles, and telemetry."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            settings = get_settings()
            self.db_path = settings.db_path
        else:
            self.db_path = Path(db_path)

        # Ensure parent directory exists (e.g. data/)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and initialize WAL mode."""
        with self._lock:
            with self.connection() as conn:
                if str(self.db_path) != ":memory:":
                    conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA foreign_keys = ON;")

                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS tenants (
                        client_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        default_policy TEXT NOT NULL DEFAULT 'skippable',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sessions (
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

                    CREATE TABLE IF NOT EXISTS session_interventions (
                        session_id TEXT NOT NULL,
                        intervention_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        PRIMARY KEY (session_id, intervention_id),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS completed_submissions (
                        session_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        PRIMARY KEY (session_id, idempotency_key),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS submissions (
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

                    CREATE TABLE IF NOT EXISTS learner_profiles (
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

                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    );
                    """
                )
        logger.info("Database initialized at %s", self.db_path)

    # -------------------------------------------------------------------------
    # Sessions Persistence
    # -------------------------------------------------------------------------

    def save_session(
        self,
        session_id: str,
        lecture_id: str,
        client_id: str,
        external_user_id: str,
        tier_override: int | None,
        version: int,
        active_intervention_id: str | None,
        active_intervention_tier: int,
        interventions_state: dict[str, str],
        completed_submissions: dict[str, str],
    ) -> None:
        """Persist or update complete runtime session."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id, lecture_id, client_id, external_user_id,
                        tier_override, version, active_intervention_id,
                        active_intervention_tier, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        version = excluded.version,
                        active_intervention_id = excluded.active_intervention_id,
                        active_intervention_tier = excluded.active_intervention_tier,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session_id,
                        lecture_id,
                        client_id,
                        external_user_id,
                        tier_override,
                        version,
                        active_intervention_id,
                        active_intervention_tier,
                        now,
                        now,
                    ),
                )

                for intv_id, state in interventions_state.items():
                    conn.execute(
                        """
                        INSERT INTO session_interventions (session_id, intervention_id, state)
                        VALUES (?, ?, ?)
                        ON CONFLICT(session_id, intervention_id) DO UPDATE SET
                            state = excluded.state
                        """,
                        (session_id, intv_id, state),
                    )

                for idem_key, result_json in completed_submissions.items():
                    conn.execute(
                        """
                        INSERT INTO completed_submissions (session_id, idempotency_key, result_json)
                        VALUES (?, ?, ?)
                        ON CONFLICT(session_id, idempotency_key) DO UPDATE SET
                            result_json = excluded.result_json
                        """,
                        (session_id, idem_key, result_json),
                    )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session record with intervention states and completed submissions from SQLite."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            intv_cursor = conn.execute(
                "SELECT intervention_id, state FROM session_interventions WHERE session_id = ?",
                (session_id,),
            )
            interventions_state = {r["intervention_id"]: r["state"] for r in intv_cursor.fetchall()}

            sub_cursor = conn.execute(
                "SELECT idempotency_key, result_json FROM completed_submissions WHERE session_id = ?",
                (session_id,),
            )
            completed_submissions = {
                r["idempotency_key"]: r["result_json"] for r in sub_cursor.fetchall()
            }

            return {
                "session_id": row["session_id"],
                "lecture_id": row["lecture_id"],
                "client_id": row["client_id"],
                "external_user_id": row["external_user_id"],
                "tier_override": row["tier_override"],
                "version": row["version"],
                "active_intervention_id": row["active_intervention_id"],
                "active_intervention_tier": row["active_intervention_tier"],
                "interventions_state": interventions_state,
                "completed_submissions": completed_submissions,
            }

    # -------------------------------------------------------------------------
    # Learner Profile Persistence
    # -------------------------------------------------------------------------

    def save_learner_profile(
        self,
        client_id: str,
        user_id: str,
        concept_mastery: dict[str, float],
        streak: int,
        friction_index: float,
        total_interventions: int,
        total_correct: int,
    ) -> None:
        """Persist learner profile."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO learner_profiles (
                        client_id, user_id, concept_mastery_json, streak,
                        friction_index, total_interventions, total_correct, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(client_id, user_id) DO UPDATE SET
                        concept_mastery_json = excluded.concept_mastery_json,
                        streak = excluded.streak,
                        friction_index = excluded.friction_index,
                        total_interventions = excluded.total_interventions,
                        total_correct = excluded.total_correct,
                        updated_at = excluded.updated_at
                    """,
                    (
                        client_id,
                        user_id,
                        json.dumps(concept_mastery),
                        streak,
                        friction_index,
                        total_interventions,
                        total_correct,
                        now,
                    ),
                )

    def load_learner_profile(self, client_id: str, user_id: str) -> dict[str, Any] | None:
        """Load learner profile from SQLite."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM learner_profiles WHERE client_id = ? AND user_id = ?",
                (client_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "client_id": row["client_id"],
                "user_id": row["user_id"],
                "concept_mastery": json.loads(row["concept_mastery_json"]),
                "streak": row["streak"],
                "friction_index": row["friction_index"],
                "total_interventions": row["total_interventions"],
                "total_correct": row["total_correct"],
            }

    # -------------------------------------------------------------------------
    # Submissions & Open-Ended Evaluations Persistence
    # -------------------------------------------------------------------------

    def save_submission(
        self,
        submission_id: str,
        session_id: str,
        intervention_id: str,
        idempotency_key: str,
        user_answer: str,
        status: str,
        resumption_policy: str,
        ai_score: float | None = None,
        is_correct: bool | None = None,
        formative_feedback: str | None = None,
        misconceptions: list[str] | None = None,
        self_assessed: bool = False,
        mastery_applied: bool = False,
        created_at: str | None = None,
        evaluated_at: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        created_str = created_at or datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO submissions (
                        submission_id, session_id, intervention_id, idempotency_key,
                        user_answer, status, resumption_policy, ai_score, is_correct,
                        formative_feedback, misconceptions_json, self_assessed,
                        mastery_applied, created_at, evaluated_at, latency_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(submission_id) DO UPDATE SET
                        status = excluded.status,
                        ai_score = excluded.ai_score,
                        is_correct = excluded.is_correct,
                        formative_feedback = excluded.formative_feedback,
                        misconceptions_json = excluded.misconceptions_json,
                        self_assessed = excluded.self_assessed,
                        mastery_applied = excluded.mastery_applied,
                        evaluated_at = excluded.evaluated_at,
                        latency_ms = excluded.latency_ms
                    """,
                    (
                        submission_id,
                        session_id,
                        intervention_id,
                        idempotency_key,
                        user_answer,
                        status,
                        resumption_policy,
                        ai_score,
                        1 if is_correct is True else (0 if is_correct is False else None),
                        formative_feedback,
                        json.dumps(misconceptions or []),
                        1 if self_assessed else 0,
                        1 if mastery_applied else 0,
                        created_str,
                        evaluated_at,
                        latency_ms,
                    ),
                )

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "submission_id": row["submission_id"],
                "session_id": row["session_id"],
                "intervention_id": row["intervention_id"],
                "idempotency_key": row["idempotency_key"],
                "user_answer": row["user_answer"],
                "status": row["status"],
                "resumption_policy": row["resumption_policy"],
                "ai_score": row["ai_score"],
                "is_correct": bool(row["is_correct"]) if row["is_correct"] is not None else None,
                "formative_feedback": row["formative_feedback"],
                "misconceptions": json.loads(row["misconceptions_json"] or "[]"),
                "self_assessed": bool(row["self_assessed"]),
                "mastery_applied": bool(row["mastery_applied"]),
                "created_at": row["created_at"],
                "evaluated_at": row["evaluated_at"],
                "latency_ms": row["latency_ms"],
            }

    # -------------------------------------------------------------------------
    # Telemetry
    # -------------------------------------------------------------------------

    def record_telemetry(
        self,
        client_id: str,
        session_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        ts = timestamp or datetime.now(timezone.utc).timestamp()
        with self._lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO telemetry_events (
                        client_id, session_id, user_id, event_type, payload_json, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (client_id, session_id, user_id, event_type, json.dumps(payload), ts),
                )

    def export_telemetry(
        self, client_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            if client_id:
                cursor = conn.execute(
                    "SELECT * FROM telemetry_events WHERE client_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (client_id, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM telemetry_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "client_id": r["client_id"],
                    "session_id": r["session_id"],
                    "user_id": r["user_id"],
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]


_db_instance: Database | None = None


def get_database(db_path: Path | str | None = None) -> Database:
    global _db_instance
    if _db_instance is None or db_path is not None:
        _db_instance = Database(db_path)
    return _db_instance
