"""add holidays and batch exceptions tables

Revision ID: 6dd84eab2d09
Revises: 55554861d924
Create Date: 2026-04-14 22:51:38.503590

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6dd84eab2d09'
down_revision = '55554861d924'
branch_labels = None
depends_on = None


def upgrade():
    # holidays and batch_exceptions are now created by the initial migration
    # (0e32c993ee7c), including their indexes. Nothing to do here.
    pass


def downgrade():
    # Tables and indexes are owned by the initial migration's downgrade.
    pass
