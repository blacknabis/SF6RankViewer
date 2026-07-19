"""Application boundary for an interactive authentication browser."""

from __future__ import annotations

from typing import Protocol

from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession


class AuthBrowser(Protocol):
    """Completes a user-driven sign-in and returns its authenticated session."""

    def login_interactively(self) -> AuthSession:
        """Wait for the user to finish interactive sign-in before returning."""
        raise NotImplementedError
