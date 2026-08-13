"""Launch a normal installed browser for user-driven Buckler authentication."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_LOOPBACK_HOST = "127.0.0.1"
_START_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class NativeLoginBrowser:
    """One native browser process exposing a temporary loopback CDP endpoint."""

    process: subprocess.Popen[bytes]
    endpoint_url: str

    def close(self) -> None:
        """Stop only the browser process owned by this login attempt."""
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def launch_native_login_browser(profile_dir: Path, target_url: str) -> NativeLoginBrowser:
    """Start Chrome or Edge without Playwright's browser automation launch flags."""
    executable = _installed_browser_executable()
    profile_dir.mkdir(parents=True, exist_ok=True)
    debugging_port = _available_loopback_port()
    command = _browser_command(executable, profile_dir, debugging_port, target_url)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    browser = NativeLoginBrowser(
        process=process,
        endpoint_url=f"http://{_LOOPBACK_HOST}:{debugging_port}",
    )
    try:
        _wait_for_cdp(browser)
    except Exception:
        browser.close()
        raise
    return browser


def _browser_command(
    executable: Path,
    profile_dir: Path,
    debugging_port: int,
    target_url: str,
) -> list[str]:
    return [
        str(executable),
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-address={_LOOPBACK_HOST}",
        f"--remote-debugging-port={debugging_port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        target_url,
    ]


def _installed_browser_executable() -> Path:
    candidates: list[Path] = []
    for environment_name, relative_paths in (
        (
            "PROGRAMFILES",
            (
                Path("Google/Chrome/Application/chrome.exe"),
                Path("Microsoft/Edge/Application/msedge.exe"),
            ),
        ),
        (
            "PROGRAMFILES(X86)",
            (
                Path("Google/Chrome/Application/chrome.exe"),
                Path("Microsoft/Edge/Application/msedge.exe"),
            ),
        ),
        (
            "LOCALAPPDATA",
            (Path("Google/Chrome/Application/chrome.exe"),),
        ),
    ):
        base = os.environ.get(environment_name)
        if base is not None:
            candidates.extend(Path(base) / relative_path for relative_path in relative_paths)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Google Chrome or Microsoft Edge is required for interactive login.")


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((_LOOPBACK_HOST, 0))
        return int(probe.getsockname()[1])


def _wait_for_cdp(browser: NativeLoginBrowser) -> None:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    version_url = f"{browser.endpoint_url}/json/version"
    while time.monotonic() < deadline:
        if browser.process.poll() is not None:
            raise RuntimeError("The interactive login browser exited during startup.")
        try:
            with opener.open(version_url, timeout=0.25) as response:
                json.load(response)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("The interactive login browser did not become ready.")
