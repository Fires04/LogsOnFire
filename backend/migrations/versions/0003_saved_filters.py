"""saved filters — reusable grep expressions per user

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("expression", sa.String(500), nullable=False),
    )
    op.create_index("ix_saved_filters_user_id", "saved_filters", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_filters_user_id", table_name="saved_filters")
    op.drop_table("saved_filters")
