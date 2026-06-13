"""orders.pickup_at (giờ hẹn giao)

Revision ID: c3a1f9d2b7e4
Revises: 8824c0db78cf
Create Date: 2026-06-13 09:10:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a1f9d2b7e4'
down_revision: Union[str, None] = '8824c0db78cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Thêm nullable trước để backfill đơn cũ, sau đó set NOT NULL.
    op.add_column('orders', sa.Column('pickup_at', sa.DateTime(timezone=True), nullable=True))
    # Backfill đơn cũ = created_at + 4 giờ (giá trị hợp lý mặc định).
    op.execute(
        "UPDATE orders SET pickup_at = created_at + interval '4 hours' "
        "WHERE pickup_at IS NULL"
    )
    op.alter_column('orders', 'pickup_at', nullable=False)


def downgrade() -> None:
    op.drop_column('orders', 'pickup_at')
