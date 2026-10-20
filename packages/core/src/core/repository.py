import os
import uuid
from datetime import UTC, datetime, timedelta

from google.api_core.exceptions import NotFound
from google.cloud import firestore, storage

from core.models import Application, Profile, Task

COLLECTION = "applications"
PROFILES_PREFIX = "profiles"
TASKS_COLLECTION = "tasks"

# Un task en "running" más tiempo que esto se da por abandonado (la instancia murió
# a medias) y otra entrega puede cogerlo. Supera el máximo que Pub/Sub espera un push
RUNNING_LEASE = timedelta(minutes=10)


def _bucket(bucket_name: str | None, storage_client: storage.Client | None) -> storage.Bucket:
    bucket_name = bucket_name or os.environ.get("GCS_BUCKET")
    if not bucket_name:
        raise RuntimeError("Falta la variable de entorno GCS_BUCKET (ver .env.example)")
    return (storage_client or storage.Client()).bucket(bucket_name)


class ApplicationRepository:
    """Guarda candidaturas: el documento en Firestore y los ficheros en Cloud Storage.

    Los clientes se pueden pasar desde fuera (en los tests, uno falso). Sin
    argumentos, los dos leen el proyecto y las credenciales de ADC.
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        firestore_client: firestore.Client | None = None,
        storage_client: storage.Client | None = None,
    ):
        self._collection = (firestore_client or firestore.Client()).collection(COLLECTION)
        self._bucket = _bucket(bucket_name, storage_client)

    def save(self, application: Application) -> None:
        # El id es el nombre del documento, no un campo. En modo Python (no JSON)
        # created_at se guarda como timestamp de Firestore y no como texto
        data = application.model_dump(exclude={"id"})
        self._collection.document(str(application.id)).set(data)

    def get(self, application_id: uuid.UUID) -> Application | None:
        snapshot = self._collection.document(str(application_id)).get()
        if not snapshot.exists:
            return None
        return Application.model_validate({**snapshot.to_dict(), "id": application_id})

    def put_file(self, application_id: uuid.UUID, name: str, data: bytes, content_type: str) -> None:
        self._blob(application_id, name).upload_from_string(data, content_type=content_type)

    def get_file(self, application_id: uuid.UUID, name: str) -> bytes | None:
        try:
            return self._blob(application_id, name).download_as_bytes()
        except NotFound:
            return None

    def _blob(self, application_id: uuid.UUID, name: str) -> storage.Blob:
        # Mismo prefijo por candidatura que tenía el disco: applications/{id}/cv.pdf
        return self._bucket.blob(f"{COLLECTION}/{application_id}/{name}")


class ProfileRepository:
    """Lee los perfiles (uno por idioma) de Cloud Storage: profiles/profile.{idioma}.json.

    Son el mismo JSON que se edita a mano en data/private/ y se sube con
    gcloud storage cp. Solo se leen enteros, nunca se consultan por campo.
    """

    def __init__(self, bucket_name: str | None = None, storage_client: storage.Client | None = None):
        self._bucket = _bucket(bucket_name, storage_client)

    def get(self, language: str) -> Profile | None:
        try:
            data = self._bucket.blob(f"{PROFILES_PREFIX}/profile.{language}.json").download_as_bytes()
        except NotFound:
            return None
        return Profile.model_validate_json(data)

    def languages(self) -> list[str]:
        # profiles/profile.es.json -> "es"
        blobs = self._bucket.list_blobs(prefix=f"{PROFILES_PREFIX}/profile.")
        return sorted(b.name.removeprefix(f"{PROFILES_PREFIX}/profile.").removesuffix(".json") for b in blobs)


class TaskRepository:
    """Estado de los trabajos asíncronos en Firestore: tasks/{id}."""

    def __init__(self, firestore_client: firestore.Client | None = None):
        self._client = firestore_client or firestore.Client()
        self._collection = self._client.collection(TASKS_COLLECTION)

    def create(self, task: Task) -> None:
        # Firestore no sabe guardar UUID: va como texto (al leer, Pydantic lo convierte)
        data = {**task.model_dump(exclude={"id"}), "application_id": str(task.application_id)}
        # create y no set: falla si el id ya existe, en vez de pisar un task en marcha
        self._collection.document(str(task.id)).create(data)

    def get(self, task_id: uuid.UUID) -> Task | None:
        snapshot = self._collection.document(str(task_id)).get()
        if not snapshot.exists:
            return None
        return Task.model_validate({**snapshot.to_dict(), "id": task_id})

    def claim(self, task_id: uuid.UUID) -> Task | None:
        """Marca el task como running si nadie lo está procesando ya.

        Devuelve el task si esta entrega debe procesarlo, o None si no (no
        existe, ya está hecho o lo tiene otra instancia). La lectura y la
        escritura van en una transacción: dos entregas simultáneas del mismo
        mensaje no pueden coger las dos el task.
        """
        ref = self._collection.document(str(task_id))

        # La función puede ejecutarse varias veces si hay conflicto, así que
        # dentro solo hay lecturas y escrituras de Firestore, nada más
        @firestore.transactional
        def _claim(transaction: firestore.Transaction) -> Task | None:
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            task = Task.model_validate({**snapshot.to_dict(), "id": task_id})

            now = datetime.now(UTC)
            if task.state == "done":
                return None
            if task.state == "running" and now - task.updated_at < RUNNING_LEASE:
                return None

            changes = {"state": "running", "attempts": task.attempts + 1, "error": None, "updated_at": now}
            transaction.update(ref, changes)
            return task.model_copy(update=changes)

        return _claim(self._client.transaction())

    def finish(self, task_id: uuid.UUID) -> None:
        self._update(task_id, state="done")

    def fail(self, task_id: uuid.UUID, error: str) -> None:
        """Fallo definitivo: nadie lo va a reintentar."""
        self._update(task_id, state="failed", error=error)

    def retry_later(self, task_id: uuid.UUID, error: str) -> None:
        """Fallo transitorio: vuelve a la cola con el error anotado hasta que Pub/Sub lo reentregue."""
        self._update(task_id, state="queued", error=error)

    def _update(self, task_id: uuid.UUID, **changes) -> None:
        # Sin transacción: solo escribe aquí la instancia que hizo claim
        self._collection.document(str(task_id)).update({**changes, "updated_at": datetime.now(UTC)})
