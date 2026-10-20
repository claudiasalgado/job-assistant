"""Worker del job-assistant: recibe los trabajos de Pub/Sub (push) y genera los CV.

Uso en local:
    uv run --package worker --env-file .env fastapi dev services/worker/src/worker/main.py --port 8001
"""

import base64
import logging
from functools import cache
from typing import Annotated

from core.events import EventPublisher
from core.models import Application, Task, TaskMessage
from core.repository import ApplicationRepository, ProfileRepository, TaskRepository
from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, Field, ValidationError

from worker.extractor import extract_offer
from worker.matcher import match_skills
from worker.render import CVTooLongError, fit_to_one_page, render_pdf
from worker.tailor import tailor_cv

# Cloud Run manda a Cloud Logging todo lo que se escribe en stdout/stderr
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

app = FastAPI(title="job-assistant-worker")


@cache
def get_applications() -> ApplicationRepository:
    return ApplicationRepository()


@cache
def get_profiles() -> ProfileRepository:
    return ProfileRepository()


@cache
def get_tasks() -> TaskRepository:
    return TaskRepository()


@cache
def get_events() -> EventPublisher:
    return EventPublisher()


Applications = Annotated[ApplicationRepository, Depends(get_applications)]
Profiles = Annotated[ProfileRepository, Depends(get_profiles)]
Tasks = Annotated[TaskRepository, Depends(get_tasks)]
Events = Annotated[EventPublisher, Depends(get_events)]


class PubSubMessage(BaseModel):
    data: str  # base64 del JSON de TaskMessage
    message_id: str = Field(alias="messageId")


class PushEnvelope(BaseModel):
    """El "sobre" con el que Pub/Sub entrega cada mensaje en una subscription push."""

    message: PubSubMessage
    subscription: str


class PermanentError(Exception):
    """Un fallo que se repetiría igual en cada reintento: no merece la pena reintentar."""


# Pub/Sub solo entiende el código de respuesta: 2xx borra el mensaje y cualquier
# otra cosa hace que lo reintente. 204 es "hecho" sin cuerpo
DONE = Response(status_code=204)
RETRY = Response(status_code=500)


@app.post("/pubsub")
def handle_push(
    envelope: PushEnvelope, applications: Applications, profiles: Profiles, tasks: Tasks, events: Events
) -> Response:
    try:
        message = TaskMessage.model_validate_json(base64.b64decode(envelope.message.data))
    except (ValueError, ValidationError):
        # Un mensaje mal formado no se arregla reintentando: se descarta y queda en el log
        logger.error("Mensaje %s mal formado, descartado", envelope.message.message_id)
        return DONE

    task = tasks.claim(message.task_id)
    if task is None:
        logger.info("Task %s: ya hecho, en marcha o inexistente", message.task_id)
        return DONE

    logger.info("Task %s: intento %d", task.id, task.attempts)
    try:
        application = _generate_cv(task, applications, profiles)
    except PermanentError as error:
        tasks.fail(task.id, str(error))
        logger.warning("Task %s: fallo permanente: %s", task.id, error)
        return DONE
    except Exception as error:
        # Cualquier otra cosa (Gemini, red, Firestore...) puede ir bien la próxima vez:
        # el task vuelve a queued (no failed) para que el frontend sepa que se reintentará
        tasks.retry_later(task.id, f"{type(error).__name__}: {error}")
        logger.exception("Task %s: fallo, Pub/Sub lo reintentará", task.id)
        return RETRY

    tasks.finish(task.id)
    logger.info("Task %s: hecho, candidatura %s", task.id, task.application_id)

    # La analítica es secundaria: si falla, se pierde una fila de BigQuery, pero no
    # se reintenta el task (otra llamada a Gemini y otro CV) por un evento
    try:
        events.created(application)
    except Exception:
        logger.exception("Task %s: no se pudo publicar el evento created", task.id)
    return DONE


def _generate_cv(task: Task, applications: ApplicationRepository, profiles: ProfileRepository) -> Application:
    """Lo mismo que hacía la api en el sprint 2, ahora fuera de la petición HTTP."""
    offer_text = applications.get_file(task.application_id, "offer.txt")
    if offer_text is None:
        raise PermanentError("No está la oferta en Cloud Storage")

    offer = extract_offer(offer_text.decode())
    language = task.language or offer.language
    profile = profiles.get(language)
    if profile is None:
        raise PermanentError(f"No hay perfil en '{language}'")

    try:
        cv = fit_to_one_page(tailor_cv(offer, profile))
    except CVTooLongError as error:
        raise PermanentError(str(error)) from error

    application = Application(
        id=task.application_id,
        created_at=task.created_at,
        language=language,
        extracted=offer,
        warnings=cv.warnings,
        match=match_skills(offer, profile),
    )
    # Mismo orden que en el sprint 2 (decisión 017): primero el fichero, el documento al final
    applications.put_file(application.id, "cv.pdf", render_pdf(cv), "application/pdf")
    applications.save(application)
    return application
