"""The storage seam for Matches.

ADR 0001 puts Match state in an in-memory map "behind a small storage interface"
so SQLite or Redis can slot in later without touching game logic. Callers depend
on :class:`MatchStore`; :class:`InMemoryMatchStore` is the only implementation
for v1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain import Match


class MatchStore(ABC):
    """Persistence interface for Matches, keyed by match id."""

    @abstractmethod
    def add(self, match: Match) -> None:
        """Store ``match``, replacing any existing Match with the same id."""

    @abstractmethod
    def get(self, match_id: str) -> Match | None:
        """Return the Match with this match id, or ``None`` if there is none."""


class InMemoryMatchStore(MatchStore):
    """A plain ``dict`` keyed by match id. Contents are lost on process restart
    and are not safe to share across multiple server workers (ADR 0001)."""

    def __init__(self) -> None:
        self._matches: dict[str, Match] = {}

    def add(self, match: Match) -> None:
        self._matches[match.id] = match

    def get(self, match_id: str) -> Match | None:
        return self._matches.get(match_id)
