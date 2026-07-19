"""Executable entry point for the loopback-only desktop application."""

from sf6viewer.interfaces.runtime.desktop import run_desktop


def main() -> int:
    """Start SF6Viewer's v2 desktop runtime."""
    return run_desktop()
