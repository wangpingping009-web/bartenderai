"""Create the authenticated product schema.

Revision ID: 20260821_01
Revises:
"""
from alembic import op

from app.db.models import Base

revision = "20260821_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
