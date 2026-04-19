"""Initial migration

Revision ID: 0e32c993ee7c
Revises: 
Create Date: 2026-03-08 10:35:56.916390

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0e32c993ee7c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create users table first — other tables reference it via FK.
    # Only the columns that existed at this point in the migration history
    # are created here; subsequent migrations add the rest incrementally.
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table('batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('current_level', sa.String(length=50), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    op.create_table('approved_students',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('is_registered', sa.Boolean(), nullable=True),
    sa.Column('registered_user_id', sa.Integer(), nullable=True),
    sa.Column('registered_at', sa.DateTime(), nullable=True),
    sa.Column('added_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], ),
    sa.ForeignKeyConstraint(['registered_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('batch_id', 'name', name='unique_batch_student')
    )

    # batch_id on users and its FK are added by the next migration (4d7bf55a091f).


def downgrade():
    op.drop_table('approved_students')
    op.drop_table('batches')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
