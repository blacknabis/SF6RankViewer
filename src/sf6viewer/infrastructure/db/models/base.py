"""Declarative metadata shared by the SQLite mappings."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for infrastructure-owned SQLAlchemy mappings."""
