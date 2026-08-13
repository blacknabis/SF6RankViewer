"""Application-owned paths and durable local file writes."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class AppPaths:
    """All filesystem locations owned by one SF6Viewer installation."""

    root: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        """Construct stable paths rooted at an injected location."""
        if not root.is_absolute():
            raise ValueError("AppPaths root must be absolute.")
        return cls(root.resolve(strict=False))

    @classmethod
    def from_windows_local_app_data(cls) -> "AppPaths":
        """Construct production paths beneath Windows local application data."""
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data is None:
            raise RuntimeError("LOCALAPPDATA is required for production application paths")
        return cls.from_root(Path(local_app_data) / "SF6Viewer")

    @property
    def database_path(self) -> Path:
        """Path to the v2 SQLite database."""
        return self.root / "data" / "sf6viewer-v2.db"

    @property
    def database(self) -> Path:
        """Path to the v2 SQLite database."""
        return self.database_path

    @property
    def auth_path(self) -> Path:
        """Path to the DPAPI-protected authentication payload."""
        return self.root / "auth" / "buckler.dpapi"

    @property
    def auth(self) -> Path:
        """Path to the DPAPI-protected authentication payload."""
        return self.auth_path

    @property
    def backgrounds_dir(self) -> Path:
        """Directory for application background images."""
        return self.root / "backgrounds"

    @property
    def legacy_backups_dir(self) -> Path:
        """Directory for imported legacy backups."""
        return self.root / "legacy" / "backups"

    @property
    def legacy_reports_dir(self) -> Path:
        """Directory for imported legacy reports."""
        return self.root / "legacy" / "reports"

    @property
    def logs_dir(self) -> Path:
        """Directory for redacted diagnostic logs."""
        return self.root / "logs"

    @property
    def crash_dir(self) -> Path:
        """Directory for crash artifacts."""
        return self.root / "crash"

    @property
    def login_browser_profile_dir(self) -> Path:
        """Dedicated persistent profile for user-driven Buckler authentication."""
        return self.root / "browser" / "login"

    @property
    def runtime_path(self) -> Path:
        """Path to runtime coordination state."""
        return self.root / "runtime" / "instance.json"

    def ensure_directories(self) -> None:
        """Create the application directories, idempotently."""
        directories = (
            self.database_path.parent,
            self.auth_path.parent,
            self.backgrounds_dir,
            self.legacy_backups_dir,
            self.legacy_reports_dir,
            self.logs_dir,
            self.crash_dir,
            self.login_browser_profile_dir,
            self.runtime_path.parent,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(
    target: Path,
    data: bytes,
    *,
    replace: Callable[[Path, Path], object] = os.replace,
    fsync: Callable[[int], object] = os.fsync,
) -> None:
    """Atomically replace *target* using an owned same-directory temp file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    temporary_created = False
    replaced = False

    try:
        with temporary_path.open("xb") as temporary_file:
            temporary_created = True
            temporary_file.write(data)
            temporary_file.flush()
            fsync(temporary_file.fileno())
        replace(temporary_path, target)
        replaced = True
    finally:
        if temporary_created and not replaced:
            temporary_path.unlink(missing_ok=True)
