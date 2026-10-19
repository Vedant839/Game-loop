"""Learner Service managing learner profiles, mastery tracking, and dynamic difficulty tiering."""

from __future__ import annotations

import logging
from backend.schemas.session import LearnerProfile

logger = logging.getLogger(__name__)


class LearnerService:
    def __init__(self) -> None:
        # Key: (client_id, user_id)
        self._profiles: dict[tuple[str, str], LearnerProfile] = {}

    def get_or_create_profile(self, client_id: str, user_id: str) -> LearnerProfile:
        key = (client_id, user_id)
        if key not in self._profiles:
            self._profiles[key] = LearnerProfile(
                user_id=user_id,
                client_id=client_id,
                concept_mastery={},
                streak=0,
                friction_index=1.0,
                total_interventions=0,
                total_correct=0,
            )
        return self._profiles[key]

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


_learner_service_instance: LearnerService | None = None


def get_learner_service() -> LearnerService:
    global _learner_service_instance
    if _learner_service_instance is None:
        _learner_service_instance = LearnerService()
    return _learner_service_instance
