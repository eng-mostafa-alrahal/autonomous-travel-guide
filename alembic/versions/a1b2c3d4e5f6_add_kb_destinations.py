"""add kb_destinations

Revision ID: a1b2c3d4e5f6
Revises: 31121b69cc8e
Create Date: 2026-06-06 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "31121b69cc8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_destinations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("destination_key", sa.String(length=512), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_kb_destinations_destination_key"),
        "kb_destinations",
        ["destination_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_kb_destinations_destination_key"), table_name="kb_destinations"
    )
    op.drop_table("kb_destinations")
