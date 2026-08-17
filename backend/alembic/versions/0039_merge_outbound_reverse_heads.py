"""0039 merge outbound unique and reverse request heads

Revision ID: 0039_merge_heads
Revises: 0038_outbound_draft_unique, 0038_reverse_requests
"""
from __future__ import annotations

from typing import Union

revision: str = "0039_merge_heads"
down_revision: Union[str, tuple[str, str], None] = (
    "0038_outbound_draft_unique",
    "0038_reverse_requests",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
