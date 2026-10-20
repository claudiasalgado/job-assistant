"""API HTTP del job-assistant (sprint 3: el trabajo pesado lo hace el worker vía Pub/Sub).

Uso en local:
    uv run --package api --env-file .env fastapi dev services/api/src/api/main.py
"""

import os
import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated

from core.models import Application, Task, TaskMessage
from core.repository import ApplicationRepository, ProfileRepository, TaskRepository
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from google.cloud import pubsub_v1
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="job-assistant")


# El frontend lo sirve la misma api: mismo origen, así que no hay CORS y la
# cookie de IAP viaja sola en cada fetch. Fuera del esquema de /docs
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Un solo cliente por proceso, creado en la primera petición y no al importar:
# así importar el módulo no exige credenciales, y en los tests se sustituyen
# con app.dependency_overrides
@cache
def get_repository() -> ApplicationRepository:
    return ApplicationRepository()


@cache
def get_profiles() -> ProfileRepository:
    return ProfileRepository()


@cache
def get_tasks() -> TaskRepository:
    return TaskRepository()


class TaskQueue:
    """Publica los trabajos en el topic de Pub/Sub del que lee el worker."""

    def __init__(self):
        topic = os.environ.get("TASKS_TOPIC")
        if not topic:
            raise RuntimeError("Falta la variable de entorno TASKS_TOPIC (ver .env.example)")
        self._publisher = pubsub_v1.PublisherClient()
        self._topic = self._publisher.topic_path(os.environ["GOOGLE_CLOUD_PROJECT"], topic)

    def publish(self, message: TaskMessage) -> None:
        # publish es asíncrono y devuelve un future; result() espera a que Pub/Sub
        # confirme que lo ha guardado, y si no lo confirma lanza la excepción aquí
        self._publisher.publish(self._topic, message.model_dump_json().encode()).result(timeout=30)


@cache
def get_queue() -> TaskQueue:
    return TaskQueue()


Repository = Annotated[ApplicationRepository, Depends(get_repository)]
Profiles = Annotated[ProfileRepository, Depends(get_profiles)]
Tasks = Annotated[TaskRepository, Depends(get_tasks)]
Queue = Annotated[TaskQueue, Depends(get_queue)]


class ApplicationCreate(BaseModel):
    # El límite evita pagar a Gemini por un texto absurdo o pegado por error
    offer_text: str = Field(min_length=50, max_length=20_000)
    # Va dentro del nombre de un objeto del bucket: solo un código ISO de dos letras
    language: str | None = Field(
        default=None, pattern=r"^[a-z]{2}$", description="Idioma del CV. Por defecto, el de la oferta"
    )


class ApplicationOut(Application):
    # La URL es de esta api, no un dato: se calcula al responder y no se guarda
    cv_pdf_url: str

    @classmethod
    def from_application(cls, application: Application) -> "ApplicationOut":
        return cls(
            **application.model_dump(),
            cv_pdf_url=f"/applications/{application.id}/cv.pdf",
        )


# 202 Accepted: la petición se ha aceptado pero el trabajo no está hecho todavía.
# Responde en lo que tardan tres escrituras, sin esperar a Gemini ni al PDF
@app.post("/applications", status_code=202)
def create_application(
    body: ApplicationCreate, repo: Repository, profiles: Profiles, tasks: Tasks, queue: Queue
) -> Task:
    # Si el idioma ya se conoce, se comprueba antes de encolar: un error gratis e inmediato
    if body.language and profiles.get(body.language) is None:
        available = profiles.languages()
        raise HTTPException(
            status_code=422,
            detail=f"No hay perfil en '{body.language}'. Disponibles: {', '.join(available) or 'ninguno'}",
        )

    # Los dos ids los genera la api: el task_id es lo que hace idempotente al worker
    now = datetime.now(UTC)
    task = Task(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        language=body.language,
        created_at=now,
        updated_at=now,
    )

    # Primero la oferta y el task, el mensaje al final: cuando el worker lo
    # reciba, todo lo que necesita ya existe
    repo.put_file(task.application_id, "offer.txt", body.offer_text.encode(), "text/plain; charset=utf-8")
    tasks.create(task)
    try:
        queue.publish(TaskMessage(task_id=task.id))
    except Exception as error:
        # Sin mensaje nadie lo procesaría: se marca como fallido en vez de dejarlo en queued para siempre
        tasks.fail(task.id, f"No se pudo encolar: {type(error).__name__}")
        raise HTTPException(status_code=503, detail="No se pudo encolar el trabajo, prueba de nuevo") from error

    return task


# El frontend pregunta aquí cada pocos segundos hasta que el task acaba (polling)
@app.get("/tasks/{task_id}")
def get_task(task_id: uuid.UUID, tasks: Tasks) -> Task:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    return task


# El id se declara como UUID: FastAPI rechaza con 422 cualquier otra cosa, así
# que nadie puede colar un "../" en la ruta del fichero en GCS
@app.get("/applications/{application_id}")
def get_application(application_id: uuid.UUID, repo: Repository) -> ApplicationOut:
    application = repo.get(application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Candidatura no encontrada")
    return ApplicationOut.from_application(application)


@app.get("/applications/{application_id}/cv.pdf")
def get_cv_pdf(application_id: uuid.UUID, repo: Repository) -> Response:
    pdf = repo.get_file(application_id, "cv.pdf")
    if pdf is None:
        raise HTTPException(status_code=404, detail="CV no encontrado")
    return Response(content=pdf, media_type="application/pdf")
