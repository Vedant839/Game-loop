"""Learner Service managing learner profiles, mastery tracking, and dynamic difficulty tiering."""

from __future__ import annotations

import logging
from backend.database import Database, get_database
from backend.schemas.session import LearnerProfile

logger = logging.getLogger(__name__)


class LearnerService:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or get_database()
        # Key: (client_id, user_id)
        self._profiles: dict[tuple[str, str], LearnerProfile] = {}

    def get_or_create_profile(self, client_id: str, user_id: str) -> LearnerProfile:
        key = (client_id, user_id)
        if key in self._profiles:
            return self._profiles[key]

        # Check SQLite persistence
        db_data = self.db.load_learner_profile(client_id, user_id)
        if db_data:
            profile = LearnerProfile(
                user_id=db_data["user_id"],
                client_id=db_data["client_id"],
                concept_mastery=db_data["concept_mastery"],
                streak=db_data["streak"],
                friction_index=db_data["friction_index"],
                total_interventions=db_data["total_interventions"],
                total_correct=db_data["total_correct"],
            )
        else:
            profile = LearnerProfile(
                user_id=user_id,
                client_id=client_id,
                concept_mastery={},
                streak=0,
                friction_index=1.0,
                total_interventions=0,
                total_correct=0,
            )
            self._persist_profile(profile)

        self._profiles[key] = profile
        return profile

    def _persist_profile(self, profile: LearnerProfile) -> None:
        self.db.save_learner_profile(
            client_id=profile.client_id,
            user_id=profile.user_id,
            concept_mastery=profile.concept_mastery,
            streak=profile.streak,
            friction_index=profile.friction_index,
            total_interventions=profile.total_interventions,
            total_correct=profile.total_correct,
        )

    def resolve_intervention_tier(
        self,
        profile: LearnerProfile,
        concept: str,
        tier_override: int | None = None,
    ) -> int:
        """Deterministically resolves the appropriate difficulty tier (1, 2, or 3)."""
        if tier_override in (1, 2, 3):
            return tier_override

        mastery = profile.concept_mastery.get(concept, 0.5)
        streak = profile.streak

        # High competence or winning streak -> Tier 3
        if streak >= 2 or mastery >= 0.8:
            return 3
        # Struggling or low mastery -> Tier 1 (Guided Scaffold)
        if streak <= -2 or mastery < 0.4:
            return 1
        # Baseline standard -> Tier 2
        return 2

    def record_attempt(
        self,
        client_id: str,
        user_id: str,
        concept: str,
        is_correct: bool,
        tier: int,
        friction_seconds: float = 0.0,
    ) -> tuple[float, int]:
        """Update learner mastery and calculate delta and recommended next tier."""
        profile = self.get_or_create_profile(client_id, user_id)
        old_mastery = profile.concept_mastery.get(concept, 0.5)

        if is_correct:
            profile.streak = max(1, profile.streak + 1)
            delta = 0.10 * tier
            new_mastery = min(1.0, round(old_mastery + delta, 2))
            profile.total_correct += 1
        else:
            profile.streak = min(-1, profile.streak - 1)
            delta = -0.10
            new_mastery = max(0.0, round(old_mastery + delta, 2))

        profile.concept_mastery[concept] = new_mastery
        profile.total_interventions += 1

        self._persist_profile(profile)

        mastery_delta = round(new_mastery - old_mastery, 2)
        next_tier = self.resolve_intervention_tier(profile, concept)

        logger.info(
            "Learner (%s:%s) concept '%s' updated: mastery %.2f -> %.2f (tier %d, next_tier %d)",
            client_id,
            user_id,
            concept,
            old_mastery,
            new_mastery,
            tier,
            next_tier,
        )
        return mastery_delta, next_tier

    def record_skip(
        self,
        client_id: str,
        user_id: str,
        session_id: str,
        intervention_id: str,
        concept: str,
    ) -> None:
        """Record an explicit intervention skip.
        
        Per SPEC.md §55.1(3), skips leave mastery unmodified (ΔM = 0) and are recorded
        as missing evidence rather than a negative penalty or failure.
        """
        profile = self.get_or_create_profile(client_id, user_id)
        # Mastery and streak remain untouched (missing evidence).
        self.db.record_telemetry(
            client_id=client_id,
            session_id=session_id,
            user_id=user_id,
            event_type="intervention_skipped",
            payload={
                "intervention_id": intervention_id,
                "concept": concept,
                "missing_evidence": True,
                "current_mastery": profile.concept_mastery.get(concept, 0.5),
            },
        )
        logger.info(
            "Learner (%s:%s) skipped intervention '%s' (concept: '%s') - recorded as missing evidence",
            client_id,
            user_id,
            intervention_id,
            concept,
        )


_learner_service_instance: LearnerService | None = None


def get_learner_service(db: Database | None = None) -> LearnerService:
    global _learner_service_instance
    if _learner_service_instance is None:
        _learner_service_instance = LearnerService(db)
    return _learner_service_instance


