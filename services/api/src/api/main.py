"""API HTTP del job-assistant (sprint 2: un solo servicio, todo síncrono).

Uso en local:
    uv run --package api --env-file .env fastapi dev services/api/src/api/main.py
"""

import uuid
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated

from core.models import Application, Profile
from core.repository import ApplicationRepository, ProfileRepository
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from worker.extractor import extract_offer
from worker.render import render_pdf
from worker.tailor import tailor_cv

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="job-assistant")


# El frontend lo sirve la misma api: mismo origen, así que no hay CORS y la
# cookie de IAP viaja sola en cada fetch. Fuera del esquema de /docs
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Un solo repositorio por proceso, creado en la primera petición y no al
# importar: así importar el módulo no exige credenciales, y en los tests se
# sustituye con app.dependency_overrides[get_repository]
@cache
def get_repository() -> ApplicationRepository:
    return ApplicationRepository()


@cache
def get_profiles() -> ProfileRepository:
    return ProfileRepository()


Repository = Annotated[ApplicationRepository, Depends(get_repository)]
Profiles = Annotated[ProfileRepository, Depends(get_profiles)]


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


def _load_profile(language: str, profiles: ProfileRepository) -> Profile:
    profile = profiles.get(language)
    if profile is None:
        available = profiles.languages()
        raise HTTPException(
            status_code=422,
            detail=f"No hay perfil en '{language}'. Disponibles: {', '.join(available) or 'ninguno'}",
        )
    return profile


# Con def y no async def: Gemini, WeasyPrint, Firestore y GCS bloquean, y FastAPI
# ejecuta las funciones def en un hilo aparte para no congelar el resto de peticiones
@app.post("/applications", status_code=201)
def create_application(body: ApplicationCreate, repo: Repository, profiles: Profiles) -> ApplicationOut:
    # Si el idioma ya se conoce, se comprueba antes de llamar a Gemini: un error gratis
    if body.language:
        _load_profile(body.language, profiles)

    offer = extract_offer(body.offer_text)
    language = body.language or offer.language
    profile = _load_profile(language, profiles)
    cv = tailor_cv(offer, profile)

    # El id lo genera la api, no el almacenamiento: es lo que hará idempotente
    # el worker en el sprint 3
    application = Application(
        id=uuid.uuid4(),
        created_at=datetime.now(UTC),
        language=language,
        extracted=offer,
        warnings=cv.warnings,
    )

    # Primero los ficheros y el documento al final: si algo falla a medias
    # quedan ficheros huérfanos en GCS, nunca un documento que apunta a un PDF
    # que no existe
    repo.put_file(application.id, "offer.txt", body.offer_text.encode(), "text/plain; charset=utf-8")
    repo.put_file(application.id, "cv.pdf", render_pdf(cv), "application/pdf")
    repo.save(application)

    return ApplicationOut.from_application(application)


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
