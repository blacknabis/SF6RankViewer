"""Tests for application-owned storage paths and atomic writes."""

from pathlib import Path

import pytest

from sf6viewer.infrastructure.storage.app_paths import AppPaths, atomic_write_bytes


def test_from_root_is_independent_of_the_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "injected-root"
    paths = AppPaths.from_root(root)

    monkeypatch.chdir(tmp_path)

    assert paths.root == root
    assert paths.database_path == root / "data" / "sf6viewer-v2.db"
    assert paths.auth_path == root / "auth" / "buckler.dpapi"


def test_from_root_rejects_relative_paths_regardless_of_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()

    monkeypatch.chdir(first_directory)
    with pytest.raises(ValueError) as first_error:
        AppPaths.from_root(Path("injected-root"))

    monkeypatch.chdir(second_directory)
    with pytest.raises(ValueError) as second_error:
        AppPaths.from_root(Path("injected-root"))

    assert str(first_error.value) == "AppPaths root must be absolute."
    assert str(second_error.value) == "AppPaths root must be absolute."


def test_from_windows_local_app_data_uses_local_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    working_directory = tmp_path / "other-working-directory"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    paths = AppPaths.from_windows_local_app_data()

    assert paths.root == tmp_path / "local-app-data" / "SF6Viewer"


def test_paths_expose_the_required_child_locations(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path)

    assert paths.database == tmp_path / "data" / "sf6viewer-v2.db"
    assert paths.auth == tmp_path / "auth" / "buckler.dpapi"
    assert paths.database_path == tmp_path / "data" / "sf6viewer-v2.db"
    assert paths.auth_path == tmp_path / "auth" / "buckler.dpapi"
    assert paths.backgrounds_dir == tmp_path / "backgrounds"
    assert paths.legacy_backups_dir == tmp_path / "legacy" / "backups"
    assert paths.legacy_reports_dir == tmp_path / "legacy" / "reports"
    assert paths.logs_dir == tmp_path / "logs"
    assert paths.crash_dir == tmp_path / "crash"
    assert paths.login_browser_profile_dir == tmp_path / "browser" / "login"
    assert paths.runtime_path == tmp_path / "runtime" / "instance.json"


def test_ensure_directories_creates_only_required_directories_idempotently(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path / "app")

    paths.ensure_directories()
    paths.ensure_directories()

    assert {
        path.relative_to(paths.root)
        for path in paths.root.rglob("*")
        if path.is_dir()
    } == {
        Path("auth"),
        Path("backgrounds"),
        Path("browser"),
        Path("browser/login"),
        Path("crash"),
        Path("data"),
        Path("legacy"),
        Path("legacy/backups"),
        Path("legacy/reports"),
        Path("logs"),
        Path("runtime"),
    }


def test_atomic_write_replaces_target_and_leaves_no_owned_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "payload.bin"

    atomic_write_bytes(target, b"new payload")

    assert target.read_bytes() == b"new payload"
    assert list(target.parent.glob(".payload.bin.*.tmp")) == []


def test_atomic_write_preserves_existing_target_when_replacement_fails(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"old payload")
    unrelated_temp = tmp_path / ".payload.bin.unrelated.tmp"
    unrelated_temp.write_bytes(b"keep me")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated replacement failure")

    with pytest.raises(OSError, match="simulated replacement failure"):
        atomic_write_bytes(target, b"new payload", replace=fail_replace)

    assert target.read_bytes() == b"old payload"
    assert unrelated_temp.read_bytes() == b"keep me"
    assert list(tmp_path.glob(".payload.bin.*.tmp")) == [unrelated_temp]


def test_atomic_write_removes_its_temp_file_when_fsync_fails(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"old payload")

    def fail_fsync(file_descriptor: int) -> None:
        raise OSError("simulated fsync failure")

    with pytest.raises(OSError, match="simulated fsync failure"):
        atomic_write_bytes(target, b"new payload", fsync=fail_fsync)

    assert target.read_bytes() == b"old payload"
    assert list(tmp_path.glob(".payload.bin.*.tmp")) == []
