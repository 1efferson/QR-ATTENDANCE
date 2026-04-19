"""Add BatchSchedule, Absence models and is_personal_time to Attendance

Revision ID: a67b4d596afe
Revises: de6f3a43103c
Create Date: 2026-03-12 14:21:53.649270

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a67b4d596afe'
down_revision = 'de6f3a43103c'
branch_labels = None
depends_on = None


def upgrade():
    # batch_schedules and absences are now created by the initial migration
    # (0e32c993ee7c), so we only need to add the is_personal_time column to
    # the attendance table here.
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_personal_time', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.drop_column('is_personal_time')
