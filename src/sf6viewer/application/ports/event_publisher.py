"""Ports for publishing durable domain events and safe warnings."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol, TypeAlias

from sf6viewer.domain.events import DomainEvent


DiagnosticIdFactory: TypeAlias = Callable[[], str]


class EventPublisher(Protocol):
    """Publishes events only after their accompanying transaction commits."""

    def publish(self, events: Sequence[DomainEvent]) -> None:
        """Publish an ordered batch of committed events."""
        raise NotImplementedError


class WarningSink(Protocol):
    """Records an operational warning without exposing exception details."""

    def warn(
        self,
        code: Literal["EVENT_PUBLISH_FAILED"],
        *,
        diagnostic_id: str,
    ) -> None:
        """Record a safe, typed warning."""
        raise NotImplementedError
