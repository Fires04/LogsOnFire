"""agent push model — replaces SSH-pull hosts with push agents

BREAKING CHANGE: this is a hard cutover, not a data-preserving migration.
`hosts` and `host_credentials` are dropped outright — existing SSH
credentials become meaningless the moment this runs (there is no agent
token to migrate them to; a token is a secret only an operator can safely
receive). `log_sources` rows referencing the old `hosts` table are dropped
along with it, and any `dashboard_panels`/`resource_grants` rows that
referenced hosts or their log sources are cleared so nothing is left
silently pointing at a deleted row.

After this runs, every monitored host must be manually re-enrolled as an
Agent (POST /api/agents) and have its log sources reconfigured from
scratch. See README's upgrade notes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Panels/grants pointing at soon-to-be-deleted log_sources/hosts would
    # otherwise be left dangling (SQLite doesn't enforce FKs by default, so
    # this wouldn't error — it would just silently rot).
    op.execute("DELETE FROM dashboard_panels")
    op.execute("DELETE FROM resource_grants WHERE resource_type = 'host'")

    op.drop_table("log_sources")
    op.drop_table("host_credentials")
    op.drop_table("hosts")

    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_rtt_ms", sa.Integer(), nullable=True),
        sa.Column("agent_version", sa.String(50), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_agents_token_hash", "agents", ["token_hash"], unique=True)

    op.create_table(
        "log_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("path_or_pattern", sa.String(1000), nullable=False),
        sa.Column("regex_base_dir", sa.String(1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("log_sources")
    op.drop_index("ix_agents_token_hash", table_name="agents")
    op.drop_table("agents")

    op.create_table(
        "hosts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=False, server_default="22"),
        sa.Column("connection_type", sa.String(20), nullable=False),
        sa.Column("ssh_username", sa.String(255), nullable=True),
        sa.Column("auth_type", sa.String(20), nullable=True),
        sa.Column("known_host_key", sa.String(4000), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "host_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("encrypted_password", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_private_key", sa.LargeBinary(), nullable=True),
        sa.Column("encrypted_private_key_passphrase", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "log_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("host_id", sa.String(36), sa.ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("path_or_pattern", sa.String(1000), nullable=False),
        sa.Column("regex_base_dir", sa.String(1000), nullable=True),
    )
