def test_package_exposes_v2_release_version() -> None:
    import sf6viewer

    assert sf6viewer.__version__ == "2.0.0"
