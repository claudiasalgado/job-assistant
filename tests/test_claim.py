"""Regla de claim: qué entrega de Pub/Sub puede coger un task (decisión 022).

La transacción en sí se probó contra Firestore real (10 claims simultáneos, uno gana);
aquí se prueba la regla, que es lo que puede romperse al tocar el código.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from core.models import Task
from core.repository import RUNNING_LEASE, can_claim

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def task(state, updated_ago=timedelta(0)):
    return Task(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        state=state,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - updated_ago,
    )


@pytest.mark.parametrize(
    ("state", "updated_ago", "expected"),
    [
        ("queued", timedelta(0), True),
        ("failed", timedelta(0), True),
        ("done", timedelta(0), False),
        ("done", timedelta(days=1), False),
        ("running", timedelta(minutes=1), False),
        ("running", RUNNING_LEASE + timedelta(seconds=1), True),
    ],
)
def test_can_claim(state, updated_ago, expected):
    assert can_claim(task(state, updated_ago), NOW) is expected
