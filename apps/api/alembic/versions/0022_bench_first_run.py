"""Bench gate: first-run authorizations (ADR-0030 amendment)

The registry entry that opens a bench write must be `observed` with evidence, but the evidence is written AFTER the first maneuver. The owner
can therefore mark ONE prior authorization `first_run`: it stands in for the missing `observed` entry (an `identified` + `supported` entry of
the exact profile is still required) and only while no `observed`/`certified` entry exists for that operation/profile. It stays single-use,
inside its window and bound to the bench target; every other condition is unchanged. Written only by the owner CLI.

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bench_authorizations ADD COLUMN first_run boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE bench_authorizations DROP COLUMN first_run")
