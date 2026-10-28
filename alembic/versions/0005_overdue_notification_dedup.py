"""one overdue notification per task

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_notifications_overdue_per_task",
        "notifications",
        ["task_id", "type"],
        unique=True,
        postgresql_where=sa.text("type = 'overdue'"),
    )


def downgrade() -> None:
    op.drop_index("uq_notifications_overdue_per_task", table_name="notifications")
