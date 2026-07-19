def test_package_exposes_v2_development_version() -> None:
    import sf6viewer

    assert sf6viewer.__version__ == "2.0.0.dev0"
