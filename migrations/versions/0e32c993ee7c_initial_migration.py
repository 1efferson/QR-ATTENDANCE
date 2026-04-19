"""Initial migration

Revision ID: 0e32c993ee7c
Revises: 
Create Date: 2026-03-08 10:35:56.916390


"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0e32c993ee7c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1. users -- no FK dependencies
    # NOTE: batch_id column is added by migration 4d7bf55a091f.
    #       google_id and nullable password_hash are added by 968040b1c41b.
    #       created_at is added by de6f3a43103c.
    #       is_synced_to_sheets is added by 55554861d924.
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('level', sa.String(length=50), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. batches -- no FK dependencies
    # NOTE: level_started_at is added by migration a8011396b238.
    op.create_table('batches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('current_level', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # 3. batch_schedules -- FK to batches
    # NOTE: migration a67b4d596afe previously created this table; that step
    #       is now superseded by this complete initial snapshot.
    op.create_table('batch_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_batch_schedule_batch_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_id', 'weekday', name='unique_batch_weekday'),
    )

    # 4. approved_students -- FK to batches and users
    # NOTE: batch_id is made nullable by migration 4d7bf55a091f; starts NOT NULL here.
    op.create_table('approved_students',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('is_registered', sa.Boolean(), nullable=True),
        sa.Column('registered_user_id', sa.Integer(), nullable=True),
        sa.Column('registered_at', sa.DateTime(), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_approved_student_batch_id'),
        sa.ForeignKeyConstraint(['registered_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_id', 'name', name='unique_batch_student'),
    )
    op.create_index('ix_approved_students_registered', 'approved_students', ['is_registered'], unique=False)

    # 5. attendance -- FK to users
    # NOTE: is_personal_time is added by migration a67b4d596afe.
    #       student_level is added by migration a8011396b238.
    #       ix_attendance_timestamp and ix_attendance_user_id added by 09cd57cf0740.
    #       ix_attendance_user_timestamp added by 55554861d924.
    op.create_table('attendance',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('course_code', sa.String(length=20), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # Functional unique index: one attendance record per user per calendar day
    op.create_index(
        'uix_user_level_date',
        'attendance',
        ['user_id', text('DATE(timestamp)')],
        unique=True,
    )

    # 6. absences -- FK to users and batches
    op.create_table('absences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('notified', sa.Boolean(), nullable=True),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_absence_batch_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='unique_student_absence_date'),
    )

    # 7. blocked_attempts -- FK to users (nullable)
    op.create_table('blocked_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=False),
        sa.Column('user_agent', sa.String(length=256), nullable=True),
        sa.Column('reason', sa.String(length=100), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('attempted_data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    # 8. holidays -- no FK dependencies
    op.create_table('holidays',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date'),
    )
    op.create_index('ix_holidays_date', 'holidays', ['date'], unique=False)

    # 9. batch_exceptions -- FK to batches
    op.create_table('batch_exceptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_batch_exception_batch_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_id', 'date', name='unique_batch_exception_date'),
    )
    op.create_index('ix_batch_exceptions_batch_date', 'batch_exceptions', ['batch_id', 'date'], unique=False)


def downgrade():
    op.drop_index('ix_batch_exceptions_batch_date', table_name='batch_exceptions')
    op.drop_table('batch_exceptions')
    op.drop_index('ix_holidays_date', table_name='holidays')
    op.drop_table('holidays')
    op.drop_table('blocked_attempts')
    op.drop_table('absences')
    op.drop_index('uix_user_level_date', table_name='attendance')
    op.drop_table('attendance')
    op.drop_index('ix_approved_students_registered', table_name='approved_students')
    op.drop_table('approved_students')
    op.drop_table('batch_schedules')
    op.drop_table('batches')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
