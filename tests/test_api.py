"""Endpoints de la api con repositorios y colas en memoria (dependency_overrides)."""

import uuid

import pytest
from api import main
from conftest import FakeApplications, FakeEvents, FakeProfiles, FakeQueue, FakeTasks, returns
from fastapi.testclient import TestClient

OFFER_TEXT = "Buscamos Junior Data Engineer con Python, SQL y Git para nuestro equipo. " * 2


@pytest.fixture
def fakes(profile):
    return {
        "applications": FakeApplications(),
        "profiles": FakeProfiles({"es": profile}),
        "tasks": FakeTasks(),
        "queue": FakeQueue(),
        "events": FakeEvents(),
    }


@pytest.fixture
def client(fakes):
    overrides = {
        main.get_repository: fakes["applications"],
        main.get_profiles: fakes["profiles"],
        main.get_tasks: fakes["tasks"],
        main.get_queue: fakes["queue"],
        main.get_events: fakes["events"],
    }
    for dependency, fake in overrides.items():
        main.app.dependency_overrides[dependency] = returns(fake)
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_crear_candidatura_encola_y_responde_202(client, fakes):
    response = client.post("/applications", json={"offer_text": OFFER_TEXT})

    assert response.status_code == 202
    task = response.json()
    assert task["state"] == "queued"
    # El mensaje lleva solo el id; la oferta está ya en el almacenamiento
    assert [str(m.task_id) for m in fakes["queue"].sent] == [task["id"]]
    assert fakes["applications"].get_file(uuid.UUID(task["application_id"]), "offer.txt") == OFFER_TEXT.encode()


def test_idioma_sin_perfil_falla_antes_de_encolar(client, fakes):
    response = client.post("/applications", json={"offer_text": OFFER_TEXT, "language": "fr"})

    assert response.status_code == 422
    assert "Disponibles: es" in response.json()["detail"]
    assert fakes["queue"].sent == []


@pytest.mark.parametrize("language", ["../x", "ES", "esp"])
def test_idioma_solo_admite_dos_letras(client, language):
    assert client.post("/applications", json={"offer_text": OFFER_TEXT, "language": language}).status_code == 422


def test_oferta_demasiado_corta(client):
    assert client.post("/applications", json={"offer_text": "hola"}).status_code == 422


def test_si_pubsub_falla_el_task_queda_failed(client, fakes):
    fakes["queue"].fail = True

    response = client.post("/applications", json={"offer_text": OFFER_TEXT})

    assert response.status_code == 503
    [task] = fakes["tasks"].docs.values()
    assert task.state == "failed"


def test_task_inexistente_da_404(client):
    assert client.get(f"/tasks/{uuid.uuid4()}").status_code == 404


def test_id_que_no_es_uuid_da_422(client):
    assert client.get("/applications/no-es-un-uuid").status_code == 422


def test_cambiar_estado_publica_el_evento(client, fakes, application):
    fakes["applications"].save(application)

    response = client.patch(f"/applications/{application.id}", json={"status": "applied"})

    assert response.status_code == 200
    assert fakes["applications"].get(application.id).status == "applied"
    assert fakes["events"].events == [("status_changed", application.id, "cv_ready", "applied")]


def test_mismo_estado_no_publica_nada(client, fakes, application):
    fakes["applications"].save(application)

    client.patch(f"/applications/{application.id}", json={"status": "cv_ready"})

    assert fakes["events"].events == []


def test_estado_inventado_da_422(client, fakes, application):
    fakes["applications"].save(application)

    assert client.patch(f"/applications/{application.id}", json={"status": "contratada"}).status_code == 422


def test_listado_con_url_del_pdf(client, fakes, application):
    fakes["applications"].save(application)

    [listed] = client.get("/applications").json()

    assert listed["cv_pdf_url"] == f"/applications/{application.id}/cv.pdf"
