"""Small, redacted JSONL diagnostic logging primitives."""

import errno
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Final

_REDACTED: Final = "[REDACTED]"
_UNSAFE: Final = "[UNSAFE]"
_SECRET_KEYS: Final = frozenset(
    {"cookie", "token", "authorization", "storage_state", "password", "csrf", "nonce"}
)
_LOG_NAME_PATTERN: Final = re.compile(r"^sf6viewer-(\d{8})(?:\.([1-9]\d*))?\.jsonl$")
_LOCK_FILE_NAME: Final = ".sf6viewer.lock"
_LOCK_TIMEOUT_SECONDS: Final = 5.0
_LOCK_RETRY_SECONDS: Final = 0.05


class _InterprocessFileLock:
    """A finite-wait advisory lock backed by an application-owned lock file."""

    def __init__(self, path: Path, timeout_seconds: float) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._file: BinaryIO | None = None
        self._acquired = False

    def __enter__(self) -> "_InterprocessFileLock":
        try:
            self._file = self._path.open("a+b")
            self._ensure_lock_byte()
            deadline = time.monotonic() + self._timeout_seconds
            while not self._try_acquire():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out acquiring JSONL log lock.")
                time.sleep(min(_LOCK_RETRY_SECONDS, remaining))
            self._acquired = True
            return self
        except BaseException:
            self._close()
            raise

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        try:
            if self._acquired:
                self._release()
        finally:
            self._close()

    def _ensure_lock_byte(self) -> None:
        if self._file is None:
            raise RuntimeError("JSONL log lock file was not opened.")
        self._file.seek(0, 2)
        if self._file.tell() == 0:
            self._file.write(b"\0")
            self._file.flush()

    def _try_acquire(self) -> bool:
        if self._file is None:
            raise RuntimeError("JSONL log lock file was not opened.")
        if os.name == "nt":
            import msvcrt

            try:
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    return False
                raise
            return True

        try:
            import fcntl
        except ImportError as error:
            raise RuntimeError("No supported interprocess file lock is available.") from error

        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise
        return True

    def _release(self) -> None:
        if self._file is None:
            raise RuntimeError("JSONL log lock file was not opened.")
        if os.name == "nt":
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            try:
                import fcntl
            except ImportError as error:
                raise RuntimeError("No supported interprocess file lock is available.") from error
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._acquired = False

    def _close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def redact(value: object) -> object:
    """Recursively redact sensitive mapping values while preserving safe JSON shapes."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and key.casefold() in _SECRET_KEYS
                else redact(item)
            )
            for key, item in value.items()
        }
    return _UNSAFE


def safe_exception_fields(exc: BaseException, diagnostic_id: str) -> dict[str, str]:
    """Return only non-sensitive exception metadata suitable for diagnostics."""
    return {"exception_type": type(exc).__name__, "diagnostic_id": diagnostic_id}


class JsonlLogSink:
    """A local JSONL sink with redaction, deterministic rotation, and retention."""

    def __init__(
        self,
        log_dir: Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        retention_days: int = 14,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if retention_days < 0:
            raise ValueError("retention_days must not be negative")

        self.log_dir = log_dir
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()

    def write(self, event: Mapping[str, object]) -> Path:
        """Append one redacted JSON object and return its file path."""
        encoded_line = self._encode(event)
        if len(encoded_line) > self.max_bytes:
            raise ValueError("Log event exceeds maximum size.")
        now = self._utc_now()

        with self._lock:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            with _InterprocessFileLock(
                self.log_dir / _LOCK_FILE_NAME, _LOCK_TIMEOUT_SECONDS
            ):
                self._prune(now.date())
                path = self._select_path(now.date(), len(encoded_line))
                with path.open("ab") as log_file:
                    log_file.write(encoded_line)
                    log_file.flush()
                return path

    def prune(self) -> None:
        """Remove expired files matching the SF6Viewer JSONL naming contract."""
        with self._lock:
            if self.log_dir.exists():
                with _InterprocessFileLock(
                    self.log_dir / _LOCK_FILE_NAME, _LOCK_TIMEOUT_SECONDS
                ):
                    self._prune(self._utc_now().date())

    @staticmethod
    def _encode(event: Mapping[str, object]) -> bytes:
        redacted = redact(event)
        serialized = json.dumps(
            redacted, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        return f"{serialized}\n".encode()

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)

    def _select_path(self, current_day: date, incoming_size: int) -> Path:
        suffix: int | None = None
        candidate = self._path_for(current_day, suffix)
        while candidate.exists() and candidate.stat().st_size and (
            candidate.stat().st_size + incoming_size > self.max_bytes
        ):
            suffix = 1 if suffix is None else suffix + 1
            candidate = self._path_for(current_day, suffix)
        return candidate

    def _path_for(self, current_day: date, suffix: int | None) -> Path:
        suffix_text = "" if suffix is None else f".{suffix}"
        return self.log_dir / f"sf6viewer-{current_day:%Y%m%d}{suffix_text}.jsonl"

    def _prune(self, current_day: date) -> None:
        cutoff = current_day - timedelta(days=self.retention_days)
        for path in self.log_dir.iterdir():
            match = _LOG_NAME_PATTERN.fullmatch(path.name)
            if match is None or not path.is_file():
                continue
            try:
                log_day = datetime.strptime(match.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            if log_day < cutoff:
                path.unlink()
