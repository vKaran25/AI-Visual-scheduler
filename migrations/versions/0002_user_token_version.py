"""add user token version for logout revocation"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade():
    op.drop_column("user", "token_version")
