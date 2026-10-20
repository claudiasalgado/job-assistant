"""Datos y dobles de prueba compartidos. Ningún test llama a GCP ni a Gemini."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from core.models import (
    Application,
    DraftAchievement,
    DraftExperience,
    ExtractedOffer,
    Profile,
    TailoredCVDraft,
    Task,
)
from core.repository import can_claim

SAMPLES = Path(__file__).parent.parent / "data" / "samples"


@pytest.fixture
def profile() -> Profile:
    return Profile.model_validate_json((SAMPLES / "profile.es.json").read_text(encoding="utf-8"))


@pytest.fixture
def offer() -> ExtractedOffer:
    return ExtractedOffer(
        company="Nubelia Analytics",
        title="Junior Data Engineer",
        location="Madrid",
        modality="hybrid",
        language="es",
        seniority="junior",
        must_have_skills=["Python", "SQL", "Git"],
        nice_to_have=["GCP", "Pytest"],
        salary_raw=None,
        responsibilities=[],
    )


@pytest.fixture
def faithful_draft(profile) -> TailoredCVDraft:
    """Un borrador que copia el perfil tal cual: todo es válido."""
    return TailoredCVDraft(
        summary="Resumen de prueba.",
        skills=[s.name for s in profile.skills],
        experiences=[
            DraftExperience(
                experience_id=e.id,
                achievements=[DraftAchievement(source_id=a.id, text=a.text) for a in e.achievements],
            )
            for e in profile.experience
        ],
    )


@pytest.fixture
def application(offer) -> Application:
    return Application(
        id=uuid.uuid4(), created_at=datetime.now(UTC), language="es", extracted=offer, warnings=[]
    )


# --- Dobles en memoria de los repositorios y colas (se inyectan con dependency_overrides) ---


class FakeApplications:
    def __init__(self):
        self.docs: dict[uuid.UUID, Application] = {}
        self.files: dict[tuple[uuid.UUID, str], bytes] = {}

    def save(self, application):
        self.docs[application.id] = application.model_copy(deep=True)

    def get(self, application_id):
        return self.docs.get(application_id)

    def list_recent(self, limit=100):
        return sorted(self.docs.values(), key=lambda a: a.created_at, reverse=True)[:limit]

    def put_file(self, application_id, name, data, content_type):
        self.files[(application_id, name)] = data

    def get_file(self, application_id, name):
        return self.files.get((application_id, name))


class FakeProfiles:
    def __init__(self, profiles: dict[str, Profile]):
        self.profiles = profiles

    def get(self, language):
        return self.profiles.get(language)

    def languages(self):
        return sorted(self.profiles)


class FakeTasks:
    """Misma regla de claim que la real (can_claim), sin transacción."""

    def __init__(self):
        self.docs: dict[uuid.UUID, Task] = {}

    def create(self, task):
        self.docs[task.id] = task

    def get(self, task_id):
        return self.docs.get(task_id)

    def claim(self, task_id):
        task = self.docs.get(task_id)
        if task is None or not can_claim(task, datetime.now(UTC)):
            return None
        self.docs[task_id] = task.model_copy(update={"state": "running", "attempts": task.attempts + 1})
        return self.docs[task_id]

    def finish(self, task_id):
        self.docs[task_id] = self.docs[task_id].model_copy(update={"state": "done"})

    def fail(self, task_id, error):
        self.docs[task_id] = self.docs[task_id].model_copy(update={"state": "failed", "error": error})

    def retry_later(self, task_id, error):
        self.docs[task_id] = self.docs[task_id].model_copy(update={"state": "queued", "error": error})


class FakeQueue:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def publish(self, message):
        if self.fail:
            raise TimeoutError("Pub/Sub no responde")
        self.sent.append(message)


class FakeEvents:
    def __init__(self):
        self.events = []

    def created(self, application):
        self.events.append(("created", application.id, None, application.status))

    def status_changed(self, application, from_status):
        self.events.append(("status_changed", application.id, from_status, application.status))


def returns(obj):
    """Una dependencia que devuelve siempre el mismo objeto.

    Sin parámetros a propósito: con `lambda fake=fake: fake`, FastAPI tomaría
    `fake` por un parámetro de la petición y pasaría una copia de su valor.
    """
    return lambda: obj
