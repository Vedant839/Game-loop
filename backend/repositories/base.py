"""Base repository for game-loop persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.database import Database


class BaseRepository:
    """Base repository providing database access."""

    def __init__(self, db: Database) -> None:
        self.db = db

