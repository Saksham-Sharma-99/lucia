"""remove orchestrator agent: it is a platform service now (D1)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02 20:30:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENT = "(SELECT id FROM agents WHERE handle = 'orchestrator')"
STATEMENTS = [
    f"DELETE FROM compiled_agent_firm_mappings WHERE agent_id = {_AGENT}",
    f"DELETE FROM agent_prompts WHERE agent_id = {_AGENT}",
    "DELETE FROM agents WHERE handle = 'orchestrator'",
]


def upgrade() -> None:
    for sql in STATEMENTS:
        op.execute(sql)


def downgrade() -> None:
    """Data only; the deleted rows are not restored."""
