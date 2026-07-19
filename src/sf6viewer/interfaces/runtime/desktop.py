"""Loopback-only Uvicorn and pywebview process lifecycle for SF6Viewer.

The browser window and API intentionally share one ``127.0.0.1`` origin.  No
authentication cookies are created by this host, and the mounted API exposes
only its already-sanitized read projections: raw evidence and browser auth
material never cross this boundary.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, time

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import Page
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from sf6viewer.application.services.login_service import LoginService
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.auth.dpapi_vault import DpapiAuthVault
from sf6viewer.infrastructure.buckler.playwright_auth import PlaywrightAuthBrowser
from sf6viewer.infrastructure.db.engine import (
    create_engine_for,
    create_session_factory,
    run_migrations,
)
from sf6viewer.infrastructure.db.models.accounts import AccountModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api

LOOPBACK_HOST = "127.0.0.1"
SERVER_START_TIMEOUT_SECONDS = 10.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
BUCKLER_KOREAN_URL = "https://www.streetfighter.com/6/buckler/ko-kr"
AUTHENTICATED_PROFILE_TIMEOUT_MS = 120_000
_PROFILE_USER_CODE_PATTERN = re.compile(r"(?:^|/)profile/([0-9]{10})(?:/|$|[?#])")


class DesktopStartupError(RuntimeError):
    """Raised when the local desktop host cannot become ready safely."""


class NativeLoginBridge:
    """Expose only a minimal, safe native sign-in operation to pywebview."""

    def __init__(self, paths: AppPaths, session_factory: Callable[[], Session]) -> None:
        self._paths = paths
        self._session_factory = session_factory
        self._lock = Lock()

    def login(self, expected_user_code: object) -> dict[str, bool | str]:
        """Authenticate an exact account without exposing browser session material."""
        try:
            expected = UserCode.parse(expected_user_code)
            with self._lock:
                self._assert_account_scope(expected)
                session = self._login(expected)
                self._mark_account_valid(session.user_code)
            return {"ok": True, "user_code": session.user_code.value}
        except DomainError as error:
            return {"ok": False, "code": error.code}
        except Exception:
            # The JavaScript caller must never receive exceptions, URLs, or
            # browser/authentication material.  It recognizes this catalog code.
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    def _login(self, expected: UserCode):
        """Run the interactive browser and keep its session local to DPAPI."""
        service = LoginService(
            auth_browser=PlaywrightAuthBrowser(
                target_url=BUCKLER_KOREAN_URL,
                wait_for_authenticated=_wait_for_authenticated_profile,
                extract_user_code=_extract_profile_user_code,
            ),
            vault=DpapiAuthVault(self._paths),
        )
        return service.login(expected)

    def _assert_account_scope(self, expected: UserCode) -> None:
        """Prevent a second account from mixing with this single-account database."""
        session = self._session_factory()
        try:
            account = session.get(AccountModel, 1)
            if account is not None and account.user_code != expected.value:
                raise error_from_code("SESSION.ACCOUNT_MISMATCH")
        finally:
            session.close()

    def _mark_account_valid(self, user_code: UserCode) -> None:
        """Create or refresh the account projection only after DPAPI save succeeds."""
        session = self._session_factory()
        now_ms = int(time() * 1_000)
        try:
            account = session.get(AccountModel, 1)
            if account is None:
                session.add(
                    AccountModel(
                        id=1,
                        user_code=user_code.value,
                        display_name=None,
                        main_character=None,
                        rank_name=None,
                        current_mr=None,
                        current_lp=None,
                        auth_state="VALID",
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
                )
            elif account.user_code == user_code.value:
                account.auth_state = "VALID"
                account.updated_at_ms = now_ms
            else:
                raise error_from_code("SESSION.ACCOUNT_MISMATCH")
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _wait_for_authenticated_profile(page: Page) -> None:
    """Wait a finite time for an authenticated Buckler profile link to appear."""
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('a[href]')).some((link) =>
        /(?:^|\\/)profile\\/[0-9]{10}(?:\\/|$|[?#])/.test(link.getAttribute('href') || '')
        )""",
        timeout=AUTHENTICATED_PROFILE_TIMEOUT_MS,
    )


def _extract_profile_user_code(page: Page) -> str:
    """Return the exact ten-digit account code from an authenticated profile href."""
    profile_hrefs = page.locator("a[href*='/profile/']").evaluate_all(
        "(links) => links.map((link) => link.getAttribute('href'))"
    )
    if not isinstance(profile_hrefs, list):
        raise RuntimeError("Authenticated profile is unavailable.")

    for href in profile_hrefs:
        if not isinstance(href, str):
            continue
        matched = _PROFILE_USER_CODE_PATTERN.search(href)
        if matched is not None:
            return matched.group(1)

    raise RuntimeError("Authenticated profile is unavailable.")


class LoopbackServer:
    """A Uvicorn server that owns one already-bound IPv4 loopback socket."""

    def __init__(self, app: FastAPI) -> None:
        self._socket = _bind_loopback_socket()
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=LOOPBACK_HOST,
                port=0,
                access_log=False,
                log_config=None,
                log_level="warning",
            )
        )
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._stopped = Event()
        self._lifecycle_lock = Lock()

    @property
    def url(self) -> str:
        """Return the only origin made available to the desktop webview."""
        port = int(self._socket.getsockname()[1])
        return f"http://{LOOPBACK_HOST}:{port}/"

    @property
    def dashboard_url(self) -> str:
        """Return the package dashboard URL on the same loopback origin."""
        return f"{self.url}ui/dashboard.html"

    def start(self, timeout_seconds: float = SERVER_START_TIMEOUT_SECONDS) -> None:
        """Run Uvicorn in the background and wait only for its lifespan startup."""
        with self._lifecycle_lock:
            if self._thread is not None:
                raise RuntimeError("Loopback server has already been started.")
            self._thread = Thread(target=self._serve, name="sf6viewer-loopback", daemon=True)
            self._thread.start()

        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if self._server.started:
                return
            if self._failure is not None or self._stopped.is_set():
                break
            self._stopped.wait(timeout=0.05)

        self.stop()
        raise DesktopStartupError("The local application server did not start.")

    def stop(self, timeout_seconds: float = SERVER_STOP_TIMEOUT_SECONDS) -> None:
        """Request Uvicorn shutdown and wait a bounded time for the server thread."""
        self._server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
        _close_socket(self._socket)

    def _serve(self) -> None:
        try:
            self._server.run(sockets=[self._socket])
        except Exception as error:  # Captured only to turn startup into one safe error.
            self._failure = error
        finally:
            _close_socket(self._socket)
            self._stopped.set()


def _bind_loopback_socket() -> socket.socket:
    """Bind and listen on a transient loopback port before Uvicorn starts.

    The pre-bound socket is passed directly to Uvicorn.  This removes the
    bind-after-selection race that a hard-coded or separately-probed port would
    introduce, while the literal IPv4 loopback address prevents LAN exposure.
    """
    bound_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_address_use is not None:
            bound_socket.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
        bound_socket.bind((LOOPBACK_HOST, 0))
        bound_socket.listen(socket.SOMAXCONN)
        bound_socket.setblocking(False)
        return bound_socket
    except Exception:
        _close_socket(bound_socket)
        raise


def _close_socket(bound_socket: socket.socket) -> None:
    """Close a socket once; repeated cleanup remains harmless."""
    try:
        bound_socket.close()
    except OSError:
        pass


def _web_assets_directory() -> Path:
    """Locate package-owned web assets without consulting the process CWD."""
    return Path(__file__).resolve().parents[1] / "web"


def _compose_application(session_factory: Callable[[], Session]) -> FastAPI:
    """Compose committed API routes with the concurrent package web bundle."""
    assets_directory = _web_assets_directory()
    if not assets_directory.is_dir() or not (assets_directory / "dashboard.html").is_file():
        raise DesktopStartupError("The desktop application bundle is unavailable.")

    app = create_read_api(session_factory)
    app.mount(
        "/ui",
        StaticFiles(directory=str(assets_directory), html=False, check_dir=True),
        name="desktop-web",
    )
    return app


def _open_desktop_window(url: str, *, js_api: object) -> None:
    """Open the same-origin dashboard and block until its pywebview window closes."""
    import webview

    webview.create_window(
        "SF6Viewer",
        url=url,
        width=1280,
        height=800,
        min_size=(900, 600),
        js_api=js_api,
    )
    webview.start(debug=False, http_server=False, private_mode=True)


def _show_safe_startup_error() -> bool:
    """Show a generic pywebview error window without exposing exception details."""
    try:
        import webview

        if webview.windows:
            return False
        webview.create_window(
            "SF6Viewer",
            html=(
                "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
                "<title>SF6Viewer</title></head><body>"
                "<h1>SF6Viewer could not start.</h1>"
                "<p>Restart the app. If the problem continues, check the installation.</p>"
                "</body></html>"
            ),
            width=520,
            height=220,
            resizable=False,
        )
        webview.start(debug=False, http_server=False, private_mode=True)
        return True
    except Exception:
        return False


def run_desktop() -> int:
    """Start, host, and cleanly stop the v2 desktop process.

    Database migrations target only ``%LOCALAPPDATA%\\SF6Viewer``'s v2 file.
    Startup failures are rendered as a generic native webview window when that
    facility is usable; no exception text or private state is placed in a UI.
    """
    engine: Engine | None = None
    server: LoopbackServer | None = None

    try:
        paths = AppPaths.from_windows_local_app_data()
        paths.ensure_directories()
        run_migrations(paths.database)
        engine = create_engine_for(paths)
        session_factory = create_session_factory(engine)
        application = _compose_application(session_factory)
        server = LoopbackServer(application)
        server.start()
        _open_desktop_window(
            server.dashboard_url,
            js_api=NativeLoginBridge(paths, session_factory),
        )
        return 0
    except Exception:
        if server is not None:
            server.stop()
        if engine is not None:
            engine.dispose()
        if _show_safe_startup_error():
            return 1
        raise
    finally:
        if server is not None:
            server.stop()
        if engine is not None:
            engine.dispose()
