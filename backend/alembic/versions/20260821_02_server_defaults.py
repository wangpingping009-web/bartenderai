"""Add database defaults required by raw SQL repositories.

Revision ID: 20260821_02
Revises: 20260821_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20260821_02"
down_revision = "20260821_01"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _defaults(table: str, columns: list[tuple[str, sa.types.TypeEngine, sa.sql.elements.TextClause]]) -> None:
    with op.batch_alter_table(table) as batch:
        for name, column_type, default in columns:
            batch.alter_column(name, existing_type=column_type, existing_nullable=False,
                               server_default=default)


def upgrade() -> None:
    _defaults("conversations", [
        ("title", sa.String(120), sa.text("'新对话'")), ("created_at", sa.String(), NOW),
        ("updated_at", sa.String(), NOW),
    ])
    _defaults("messages", [("metadata_json", sa.Text(), sa.text("'{}'")),
                            ("created_at", sa.String(), NOW)])
    _defaults("auth_tokens", [("created_at", sa.String(), NOW)])
    _defaults("refresh_tokens", [("created_at", sa.String(), NOW)])
    _defaults("feedback", [
        ("recipe_id", sa.String(80), sa.text("''")), ("recipe_name", sa.String(160), sa.text("''")),
        ("tags_json", sa.Text(), sa.text("'[]'")), ("note", sa.Text(), sa.text("''")),
        ("created_at", sa.String(), NOW),
    ])
    _defaults("creations", [("created_at", sa.String(), NOW)])
    _defaults("prompt_versions", [
        ("description", sa.Text(), sa.text("''")), ("is_active", sa.Boolean(), sa.text("0")),
        ("created_at", sa.String(), NOW),
    ])
    _defaults("jobs", [
        ("status", sa.String(20), sa.text("'queued'")), ("progress", sa.Float(), sa.text("0")),
        ("result_json", sa.Text(), sa.text("'{}'")), ("error", sa.Text(), sa.text("''")),
        ("created_at", sa.String(), NOW), ("updated_at", sa.String(), NOW),
    ])


def downgrade() -> None:
    # Defaults are safe for older code and intentionally retained.
    pass
