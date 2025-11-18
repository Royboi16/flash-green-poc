"""Create trades and orders tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_create_trades_orders"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("qty_mwh", sa.Float(), nullable=False),
        sa.Column("spot_price", sa.Float(), nullable=False),
        sa.Column("fut_price", sa.Float(), nullable=False),
        sa.Column("profit", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=False), nullable=False, index=True),
        sa.Column("repo_tx_hash", sa.String(), nullable=True),
        sa.Column("repo_cash_token", sa.String(), nullable=True),
        sa.Column("repo_asset_token", sa.String(), nullable=True),
        sa.Column("repo_timestamp", sa.DateTime(timezone=False), nullable=True),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty_requested", sa.Float(), nullable=False),
        sa.Column("qty_filled", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=False), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("trades")
