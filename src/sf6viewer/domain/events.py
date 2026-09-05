"""Domain events emitted after durable state changes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | Mapping[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """An immutable, JSON-safe notification of a completed domain action."""

    name: str
    occurred_at_ms: int
    payload: Mapping[str, JsonValue]
