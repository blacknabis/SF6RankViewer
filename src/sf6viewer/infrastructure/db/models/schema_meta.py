"""Schema metadata mapping."""

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class SchemaMetaModel(Base):
    """Singleton metadata for the application-owned schema."""

    __tablename__ = "schema_meta"
    __table_args__ = (CheckConstraint("id = 1", name="ck_schema_meta_singleton_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
