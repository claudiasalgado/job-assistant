"""Respuestas del worker a Pub/Sub: el código HTTP decide si se reintenta (decisión 022)."""

import base64
import uuid
from datetime import UTC, datetime

import pytest
from conftest import FakeApplications, FakeEvents, FakeProfiles, FakeTasks, returns
from core.models import Task, TaskMessage
from fastapi.testclient import TestClient
from worker import main


@pytest.fixture
def fakes(profile):
    return {
        "applications": FakeApplications(),
        "profiles": FakeProfiles({"es": profile}),
        "tasks": FakeTasks(),
        "events": FakeEvents(),
    }


@pytest.fixture
def client(fakes):
    overrides = {
        main.get_applications: fakes["applications"],
        main.get_profiles: fakes["profiles"],
        main.get_tasks: fakes["tasks"],
        main.get_events: fakes["events"],
    }
    for dependency, fake in overrides.items():
        main.app.dependency_overrides[dependency] = returns(fake)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture
def task(fakes):
    now = datetime.now(UTC)
    task = Task(id=uuid.uuid4(), application_id=uuid.uuid4(), created_at=now, updated_at=now)
    fakes["tasks"].create(task)
    return task


def push(client, data: bytes):
    envelope = {"message": {"data": base64.b64encode(data).decode(), "messageId": "1"}, "subscription": "s"}
    return client.post("/pubsub", json=envelope)


def push_task(client, task):
    return push(client, TaskMessage(task_id=task.id).model_dump_json().encode())


def test_exito_marca_done_y_publica_created(client, fakes, task, application, monkeypatch):
    monkeypatch.setattr(main, "_generate_cv", lambda *args: application)

    assert push_task(client, task).status_code == 204
    assert fakes["tasks"].get(task.id).state == "done"
    assert [e[0] for e in fakes["events"].events] == ["created"]


def test_mensaje_duplicado_no_repite_el_trabajo(client, fakes, task, application, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_generate_cv", lambda *args: calls.append(1) or application)

    push_task(client, task)
    assert push_task(client, task).status_code == 204

    assert len(calls) == 1
    assert fakes["tasks"].get(task.id).attempts == 1


def test_fallo_transitorio_devuelve_500_para_reintentar(client, fakes, task, monkeypatch):
    def boom(*args):
        raise ConnectionError("Gemini no responde")

    monkeypatch.setattr(main, "_generate_cv", boom)

    assert push_task(client, task).status_code == 500
    # queued y no failed: el frontend sabe que va a reintentarse
    saved = fakes["tasks"].get(task.id)
    assert saved.state == "queued"
    assert "Gemini no responde" in saved.error


def test_fallo_permanente_devuelve_204_y_queda_failed(client, fakes, task, monkeypatch):
    def no_profile(*args):
        raise main.PermanentError("No hay perfil en 'fr'")

    monkeypatch.setattr(main, "_generate_cv", no_profile)

    assert push_task(client, task).status_code == 204
    assert fakes["tasks"].get(task.id).state == "failed"


def test_si_falla_el_evento_el_task_sigue_done(client, fakes, task, application, monkeypatch):
    monkeypatch.setattr(main, "_generate_cv", lambda *args: application)

    def broken(application):
        raise TimeoutError("Pub/Sub no responde")

    fakes["events"].created = broken

    assert push_task(client, task).status_code == 204
    assert fakes["tasks"].get(task.id).state == "done"


def test_mensaje_mal_formado_se_descarta(client):
    assert push(client, b"no es json").status_code == 204


def test_task_inexistente_se_descarta(client):
    assert push(client, TaskMessage(task_id=uuid.uuid4()).model_dump_json().encode()).status_code == 204


def test_sin_oferta_en_almacenamiento_es_fallo_permanente(client, fakes, task):
    # _generate_cv real: falla antes de llamar a Gemini porque no hay offer.txt
    assert push_task(client, task).status_code == 204
    assert fakes["tasks"].get(task.id).state == "failed"
