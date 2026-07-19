"""Safe orchestration for interactive and restored authentication sessions."""

from __future__ import annotations

from sf6viewer.application.ports.auth_browser import AuthBrowser
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession, DpapiAuthVault

_INTERACTIVE_LOGIN_FAILED = "Interactive sign-in could not be completed."
_INVALID_EXPECTED_USER_CODE = "expected_user_code must be a UserCode."
_AUTH_STORAGE_UNAVAILABLE = "Authentication storage is unavailable."


class LoginService:
    """Validates authenticated accounts before saving or restoring sessions."""

    def __init__(self, auth_browser: AuthBrowser, vault: DpapiAuthVault) -> None:
        self._auth_browser = auth_browser
        self._vault = vault

    def login(self, expected_user_code: UserCode) -> AuthSession:
        """Run interactive sign-in and save a session for the expected account only."""
        expected_user_code = _canonical_expected_user_code(expected_user_code)
        try:
            session = self._auth_browser.login_interactively()
        except DomainError:
            raise
        except Exception:
            raise RuntimeError(_INTERACTIVE_LOGIN_FAILED) from None

        if not isinstance(session, AuthSession):
            raise RuntimeError(_INTERACTIVE_LOGIN_FAILED)
        if session.user_code != expected_user_code:
            self._clear_vault()
            raise error_from_code("SESSION.ACCOUNT_MISMATCH")

        self._save_vault(session)
        return session

    def restore(self, expected_user_code: UserCode) -> AuthSession:
        """Restore the saved session for the expected account without browser access."""
        expected_user_code = _canonical_expected_user_code(expected_user_code)
        session = self._load_vault()
        if session is None:
            raise error_from_code("SESSION.MISSING")
        if session.user_code != expected_user_code:
            self._clear_vault()
            raise error_from_code("SESSION.ACCOUNT_MISMATCH")
        return session

    def clear(self) -> None:
        """Clear only the persisted authentication session."""
        self._clear_vault()

    def _save_vault(self, session: AuthSession) -> None:
        try:
            self._vault.save(session)
        except DomainError:
            raise
        except Exception:
            raise RuntimeError(_AUTH_STORAGE_UNAVAILABLE) from None

    def _load_vault(self) -> AuthSession | None:
        try:
            return self._vault.load()
        except DomainError:
            raise
        except Exception:
            raise RuntimeError(_AUTH_STORAGE_UNAVAILABLE) from None

    def _clear_vault(self) -> None:
        try:
            self._vault.clear()
        except DomainError:
            raise
        except Exception:
            raise RuntimeError(_AUTH_STORAGE_UNAVAILABLE) from None


def _canonical_expected_user_code(expected_user_code: UserCode) -> UserCode:
    """Return the canonical expected user code without accepting raw values."""
    if not isinstance(expected_user_code, UserCode):
        raise TypeError(_INVALID_EXPECTED_USER_CODE)
    return UserCode.parse(expected_user_code.value)
