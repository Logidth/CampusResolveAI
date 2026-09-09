"""initial_schema

Revision ID: 8edd964457db
Revises: 
Create Date: 2026-09-09 12:24:41.382503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8edd964457db'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. complaints table
    if "complaints" not in existing_tables:
        op.create_table(
            "complaints",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("urgency", sa.String(length=50), nullable=True),
            sa.Column("status", sa.String(length=50), server_default="open", nullable=False),
            sa.Column("assigned_authority", sa.String(length=150), nullable=True),
            sa.Column("initial_authority", sa.String(length=150), nullable=True),
            sa.Column("ticket_id", sa.String(length=50), nullable=True),
            sa.Column("student_email", sa.String(length=150), nullable=True),
            sa.Column("student_name", sa.String(length=150), nullable=True),
            sa.Column("escalation_level", sa.Integer(), server_default="0", nullable=False),
            sa.Column("no_auto_escalation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("photo_url", sa.Text(), nullable=True),
            sa.Column("secondary_category", sa.String(length=50), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("sla_deadline", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_complaints_id"), "complaints", ["id"], unique=False)
        op.create_index(op.f("ix_complaints_ticket_id"), "complaints", ["ticket_id"], unique=False)
        op.create_index(op.f("ix_complaints_student_email"), "complaints", ["student_email"], unique=False)
    else:
        existing_cols = {c["name"] for c in inspector.get_columns("complaints")}
        if "secondary_category" not in existing_cols:
            op.add_column("complaints", sa.Column("secondary_category", sa.String(length=50), nullable=True))
        if "summary" not in existing_cols:
            op.add_column("complaints", sa.Column("summary", sa.Text(), nullable=True))
        if "initial_authority" not in existing_cols:
            op.add_column("complaints", sa.Column("initial_authority", sa.String(length=150), nullable=True))
        if "resolved_at" not in existing_cols:
            op.add_column("complaints", sa.Column("resolved_at", sa.DateTime(), nullable=True))
        if "photo_url" not in existing_cols:
            op.add_column("complaints", sa.Column("photo_url", sa.Text(), nullable=True))
        if "ticket_id" not in existing_cols:
            op.add_column("complaints", sa.Column("ticket_id", sa.String(length=50), nullable=True))
        if "student_email" not in existing_cols:
            op.add_column("complaints", sa.Column("student_email", sa.String(length=150), nullable=True))
        if "student_name" not in existing_cols:
            op.add_column("complaints", sa.Column("student_name", sa.String(length=150), nullable=True))
        if "no_auto_escalation" not in existing_cols:
            op.add_column("complaints", sa.Column("no_auto_escalation", sa.Boolean(), server_default=sa.text("false"), nullable=False))
        if "escalation_level" not in existing_cols:
            op.add_column("complaints", sa.Column("escalation_level", sa.Integer(), server_default="0", nullable=False))
        if "sla_deadline" not in existing_cols:
            op.add_column("complaints", sa.Column("sla_deadline", sa.DateTime(), nullable=True))

        existing_indexes = {ix["name"] for ix in inspector.get_indexes("complaints")}
        if "ix_complaints_ticket_id" not in existing_indexes:
            try:
                op.create_index("ix_complaints_ticket_id", "complaints", ["ticket_id"], unique=False)
            except Exception:
                pass
        if "ix_complaints_student_email" not in existing_indexes:
            try:
                op.create_index("ix_complaints_student_email", "complaints", ["student_email"], unique=False)
            except Exception:
                pass

    # 2. student_conduct table
    if "student_conduct" not in existing_tables:
        op.create_table(
            "student_conduct",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("student_email", sa.String(length=150), nullable=False),
            sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_warned_at", sa.DateTime(), nullable=True),
            sa.Column("reported_to_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_student_conduct_id"), "student_conduct", ["id"], unique=False)
        op.create_index(op.f("ix_student_conduct_student_email"), "student_conduct", ["student_email"], unique=True)
    else:
        existing_cols = {c["name"] for c in inspector.get_columns("student_conduct")}
        if "reported_to_principal" not in existing_cols:
            op.add_column("student_conduct", sa.Column("reported_to_principal", sa.Boolean(), server_default=sa.text("false"), nullable=False))

    # 3. activity_log table
    if "activity_log" not in existing_tables:
        op.create_table(
            "activity_log",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("complaint_id", sa.Integer(), sa.ForeignKey("complaints.id"), nullable=False),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_activity_log_id"), "activity_log", ["id"], unique=False)

    # 4. users table
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(length=50), nullable=False),
            sa.Column("email", sa.String(length=150), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=150), nullable=False),
            sa.Column("role", sa.String(length=50), nullable=False),
            sa.Column("assigned_authority", sa.String(length=150), nullable=True),
            sa.Column("tier", sa.String(length=100), nullable=True),
            sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
        op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    else:
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        if "must_change_password" not in existing_cols:
            op.add_column("users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False))
        if "tier" not in existing_cols:
            op.add_column("users", sa.Column("tier", sa.String(length=100), nullable=True))
        if "assigned_authority" not in existing_cols:
            op.add_column("users", sa.Column("assigned_authority", sa.String(length=150), nullable=True))


def downgrade() -> None:
    op.drop_table("activity_log")
    op.drop_table("complaints")
    op.drop_table("student_conduct")
    op.drop_table("users")
