def test_package_exposes_v21_release_version() -> None:
    import sf6viewer

    assert sf6viewer.__version__ == "2.1.0"
