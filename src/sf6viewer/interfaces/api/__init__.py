"""Loopback-only, read-only HTTP interface for the desktop application."""

from sf6viewer.interfaces.api.app import create_read_api

__all__ = ["create_read_api"]
