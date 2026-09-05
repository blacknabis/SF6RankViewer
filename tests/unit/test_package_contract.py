from pathlib import Path


def test_release_version_is_consistent_across_package_and_exe_metadata() -> None:
    import sf6viewer

    assert sf6viewer.__version__ == "2.4.1"

    version_info = (Path(__file__).parents[2] / "packaging" / "version_info.txt").read_text(
        encoding="utf-8"
    )
    assert f"StringStruct(u'FileVersion', u'{sf6viewer.__version__}')" in version_info
    assert f"StringStruct(u'ProductVersion', u'{sf6viewer.__version__}')" in version_info
