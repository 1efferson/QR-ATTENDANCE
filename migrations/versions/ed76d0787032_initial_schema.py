"""initial_schema

Revision ID: ed76d0787032
Revises: 
Create Date: 2026-04-19 22:43:51.089800

"""
from alembic import op
import sqlalchemy as sa

revision = 'ed76d0787032'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('current_level', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('level_started_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('holidays',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date')
    )
    op.create_index('ix_holidays_date', 'holidays', ['date'], unique=False)

    op.create_table('batch_exceptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_batch_exception_batch_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_id', 'date', name='unique_batch_exception_date')
    )
    op.create_index('ix_batch_exceptions_batch_date', 'batch_exceptions', ['batch_id', 'date'], unique=False)

    op.create_table('batch_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_batch_schedule_batch_id'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_id', 'weekday', name='unique_batch_weekday')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=True),
    sa.Column('google_id', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('level', sa.String(length=50), nullable=True),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('batch_id', sa.Integer(), nullable=True),
    sa.Column('is_synced_to_sheets', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_user_batch_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_batch_id', 'users', ['batch_id'], unique=False)
    op.create_index('ix_users_batch_role', 'users', ['batch_id', 'role'], unique=False)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_google_id', 'users', ['google_id'], unique=True)
    op.create_index('ix_users_synced_to_sheets', 'users', ['is_synced_to_sheets', 'role'], unique=False)

    op.create_table('absences',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('notified', sa.Boolean(), nullable=True),
    sa.Column('notified_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_absence_batch_id'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'],),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'date', name='unique_student_absence_date')
    )
    op.create_table('approved_students',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('is_registered', sa.Boolean(), nullable=True),
    sa.Column('registered_user_id', sa.Integer(), nullable=True),
    sa.Column('registered_at', sa.DateTime(), nullable=True),
    sa.Column('added_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name='fk_approved_student_batch_id'),
    sa.ForeignKeyConstraint(['registered_user_id'], ['users.id'],),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_id', 'name', name='unique_batch_student')
    )
    op.create_index('ix_approved_students_registered', 'approved_students', ['is_registered'], unique=False)
    op.create_index(
        'ix_approved_students_batch_lower_email',
        'approved_students',
        [sa.text('batch_id'), sa.text('lower(email)')],
        unique=True
    )

    op.create_table('attendance',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('course_code', sa.String(length=20), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=256), nullable=True),
    sa.Column('is_personal_time', sa.Boolean(), nullable=False),
    sa.Column('student_level', sa.String(length=50), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'],),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attendance_timestamp', 'attendance', ['timestamp'], unique=False)
    op.create_index('ix_attendance_user_id', 'attendance', ['user_id'], unique=False)
    op.create_index('ix_attendance_user_timestamp', 'attendance', ['user_id', 'timestamp'], unique=False)
    op.create_index(
        'uix_user_level_date',
        'attendance',
        ['user_id', 'student_level', sa.text("date(timestamp)")],
        unique=True
    )

    op.create_table('blocked_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=False),
    sa.Column('user_agent', sa.String(length=256), nullable=True),
    sa.Column('reason', sa.String(length=100), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('attempted_data', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'],),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('blocked_attempts')
    op.drop_index('uix_user_level_date', table_name='attendance')
    op.drop_index('ix_attendance_user_timestamp', table_name='attendance')
    op.drop_index('ix_attendance_user_id', table_name='attendance')
    op.drop_index('ix_attendance_timestamp', table_name='attendance')
    op.drop_table('attendance')
    op.drop_index('ix_approved_students_batch_lower_email', table_name='approved_students')
    op.drop_index('ix_approved_students_registered', table_name='approved_students')
    op.drop_table('approved_students')
    op.drop_table('absences')
    op.drop_index('ix_users_synced_to_sheets', table_name='users')
    op.drop_index('ix_users_google_id', table_name='users')
    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_batch_role', table_name='users')
    op.drop_index('ix_users_batch_id', table_name='users')
    op.drop_table('users')
    op.drop_table('batch_schedules')
    op.drop_index('ix_batch_exceptions_batch_date', table_name='batch_exceptions')
    op.drop_table('batch_exceptions')
    op.drop_index('ix_holidays_date', table_name='holidays')
    op.drop_table('holidays')
    op.drop_table('batches')