"""tenant_settings.default_turnaround_hours

Revision ID: d1e2f3a4b5c6
Revises: c3a1f9d2b7e4
Create Date: 2026-06-13 12:10:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c3a1f9d2b7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenant_settings',
        sa.Column(
            'default_turnaround_hours',
            sa.Integer(),
            server_default='4',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('tenant_settings', 'default_turnaround_hours')
