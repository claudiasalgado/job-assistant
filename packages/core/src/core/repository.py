import os
import uuid

from google.api_core.exceptions import NotFound
from google.cloud import firestore, storage

from core.models import Application, Profile

COLLECTION = "applications"
PROFILES_PREFIX = "profiles"


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
