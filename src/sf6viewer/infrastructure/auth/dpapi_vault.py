"""Windows current-user DPAPI persistence for browser authentication state."""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import sys
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final, cast

from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.storage.app_paths import AppPaths, atomic_write_bytes

_CRYPTPROTECT_UI_FORBIDDEN: Final = 0x1
_UNSUPPORTED_PLATFORM: Final = "DPAPI authentication storage is only supported on Windows."
_SAVE_FAILED: Final = "Authentication data could not be saved."
_LOAD_FAILED: Final = "Authentication data could not be loaded."
_CLEAR_FAILED: Final = "Authentication data could not be cleared."
_INITIALIZATION_FAILED: Final = "DPAPI authentication storage is unavailable."

_NativeFunction = Callable[..., int]
_LocalFree = Callable[[object], object]


class _DataBlob(ctypes.Structure):
    """The DATA_BLOB structure used by the Windows DPAPI APIs."""

    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _DpapiFailure(Exception):
    """Internal marker for a native DPAPI operation failure."""


@dataclass(frozen=True, slots=True)
class AuthSession:
    """The authenticated user and opaque browser storage-state bytes."""

    user_code: UserCode
    storage_state: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.user_code, UserCode):
            raise TypeError("user_code must be a UserCode.")
        if not isinstance(self.storage_state, bytes):
            raise TypeError("storage_state must be bytes.")

        # Parsing makes the stored code canonical even if a caller supplied a
        # directly constructed UserCode instance.
        object.__setattr__(self, "user_code", UserCode.parse(self.user_code.value))


class DpapiAuthVault:
    """Stores an ``AuthSession`` using Windows current-user DPAPI."""

    def __init__(self, paths: AppPaths) -> None:
        _require_windows()
        self._path = paths.auth
        try:
            self._protect_data, self._unprotect_data, self._local_free = _bind_dpapi()
        except (AttributeError, OSError):
            raise RuntimeError(_INITIALIZATION_FAILED) from None

    def save(self, session: AuthSession) -> None:
        """Encrypt and atomically persist an authenticated browser session."""
        if not isinstance(session, AuthSession):
            raise TypeError("session must be an AuthSession.")

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            encrypted = self._encrypt(_serialize_session(session))
            atomic_write_bytes(self._path, encrypted)
        except (OSError, _DpapiFailure):
            raise RuntimeError(_SAVE_FAILED) from None

    def load(self) -> AuthSession | None:
        """Load and decrypt the saved session, if one exists."""
        try:
            encrypted = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            raise RuntimeError(_LOAD_FAILED) from None

        try:
            return _deserialize_session(self._decrypt(encrypted))
        except Exception:
            # Both malformed payloads and native decryption errors intentionally
            # share one stable public failure that leaks neither data nor OS text.
            raise RuntimeError(_LOAD_FAILED) from None

    def clear(self) -> None:
        """Remove only this vault's configured authentication payload."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            raise RuntimeError(_CLEAR_FAILED) from None

    def _encrypt(self, plaintext: bytes) -> bytes:
        input_blob, input_buffer = _input_blob(plaintext)
        output_blob = _DataBlob()

        succeeded = self._protect_data(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        # Keep the backing buffer alive until CryptProtectData has returned.
        del input_buffer
        if not succeeded:
            _free_output_buffer(output_blob, self._local_free)
            raise _DpapiFailure

        return _copy_and_free(output_blob, self._local_free)

    def _decrypt(self, encrypted: bytes) -> bytes:
        input_blob, input_buffer = _input_blob(encrypted)
        output_blob = _DataBlob()

        succeeded = self._unprotect_data(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
        # Keep the backing buffer alive until CryptUnprotectData has returned.
        del input_buffer
        if not succeeded:
            _free_output_buffer(output_blob, self._local_free)
            raise _DpapiFailure

        return _copy_and_free(output_blob, self._local_free)


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(_UNSUPPORTED_PLATFORM)


def _bind_dpapi() -> tuple[_NativeFunction, _NativeFunction, _LocalFree]:
    """Bind only the Windows functions needed by this adapter."""
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    protect_data = crypt32.CryptProtectData
    protect_data.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    protect_data.restype = wintypes.BOOL

    unprotect_data = crypt32.CryptUnprotectData
    unprotect_data.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    unprotect_data.restype = wintypes.BOOL

    local_free = kernel32.LocalFree
    local_free.argtypes = [wintypes.HLOCAL]
    local_free.restype = wintypes.HLOCAL
    return (
        cast(_NativeFunction, protect_data),
        cast(_NativeFunction, unprotect_data),
        cast(_LocalFree, local_free),
    )


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    """Create a native input blob while retaining the Python backing buffer."""
    buffer = ctypes.create_string_buffer(data, max(len(data), 1))
    blob = _DataBlob(
        cbData=len(data),
        pbData=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _copy_and_free(output_blob: _DataBlob, local_free: _LocalFree) -> bytes:
    """Copy a DPAPI output buffer and always return it to LocalFree."""
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        _free_output_buffer(output_blob, local_free)


def _free_output_buffer(output_blob: _DataBlob, local_free: _LocalFree) -> None:
    """Release a native output buffer if the Windows API allocated one."""
    if output_blob.pbData:
        local_free(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))


def _serialize_session(session: AuthSession) -> bytes:
    payload = {
        "storage_state": base64.b64encode(session.storage_state).decode("ascii"),
        "user_code": session.user_code.value,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _deserialize_session(payload: bytes) -> AuthSession:
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Invalid authentication payload.")

    encoded_state = decoded.get("storage_state")
    user_code = decoded.get("user_code")
    if not isinstance(encoded_state, str) or not isinstance(user_code, str):
        raise ValueError("Invalid authentication payload.")

    try:
        storage_state = base64.b64decode(encoded_state, validate=True)
    except binascii.Error as error:
        raise ValueError("Invalid authentication payload.") from error
    return AuthSession(UserCode.parse(user_code), storage_state)
