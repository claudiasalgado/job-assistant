import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExtractedOffer(BaseModel):
    """Datos estructurados que se extraen del texto de una oferta.

    Las descripciones de los campos también son instrucciones para Gemini
    (se envían como parte del esquema), así que están escritas para él.
    """

    company: str | None = Field(
        description="Nombre de la empresa que contrata. null si no aparece."
    )
    title: str = Field(description="Título del puesto tal y como aparece en la oferta.")
    location: str | None = Field(
        description="Ciudad y país del puesto. null si no se indica."
    )
    modality: Literal["remote", "hybrid", "onsite"] | None = Field(
        description="Modalidad de trabajo. null si no se puede deducir."
    )
    language: str = Field(
        description="Idioma en el que está escrita la oferta, como código ISO 639-1 (es, en, ca...)."
    )
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "unspecified"] = Field(
        description=(
            "Nivel pedido. Deduce por los años de experiencia si no se dice "
            "(hasta 2 años: junior, 3 a 5: mid, más de 5: senior). "
            "unspecified si no hay base para decidirlo."
        )
    )
    must_have_skills: list[str] = Field(
        description=(
            "Tecnologías y habilidades obligatorias. Nombres cortos y canónicos "
            "('Python', 'Google Cloud Platform'), nunca frases. Solo las que aparecen en la oferta."
        )
    )
    nice_to_have: list[str] = Field(
        description=(
            "Tecnologías y habilidades deseables o que suman puntos, con el mismo "
            "formato que must_have_skills. Lista vacía si no hay."
        )
    )
    salary_raw: str | None = Field(
        description=(
            "Salario copiado literalmente de la oferta, sin interpretar ni convertir. "
            "null si no se menciona."
        )
    )
    responsibilities: list[str] = Field(
        description="Tareas principales del puesto, una frase corta por elemento."
    )


# --- Perfil (refleja data/samples/profile.json) ---


class Achievement(BaseModel):
    id: str
    text: str


class Experience(BaseModel):
    id: str
    company: str
    title: str
    location: str | None
    start: str
    end: str | None
    achievements: list[Achievement]


class Education(BaseModel):
    institution: str
    degree: str
    start: str
    end: str | None
    description: str | None = None
    details: list[str] = []


class Skill(BaseModel):
    name: str
    level: Literal["beginner", "intermediate", "advanced"]
    years: int
    # Agrupa las skills en el CV ("Cloud y MLOps"); sin categoría van en una sola línea
    category: str | None = None


class Language(BaseModel):
    name: str
    level: str


class Personal(BaseModel):
    name: str
    email: str
    phone: str | None
    location: str | None
    links: dict[str, str]


class Volunteering(BaseModel):
    organization: str
    description: str


class Project(BaseModel):
    name: str
    description: str
    stack: list[str]
    url: str | None


class Profile(BaseModel):
    """Perfil en un solo idioma: hay un fichero por idioma con los mismos ids."""

    language: str  # ISO 639-1 del texto del perfil
    personal: Personal
    # Como se presenta la persona en la cabecera; lo copia el código, nunca Gemini
    headline: str
    # Solo para comparar con la oferta: el CV no lo muestra ni Gemini lo menciona
    seniority: Literal["intern", "junior", "mid", "senior", "lead"]
    summary: str
    experience: list[Experience]
    education: list[Education]
    skills: list[Skill]
    languages: list[Language]
    certifications: list[str] = []
    volunteering: list[Volunteering] = []
    projects: list[Project] = []


# --- CV adaptado: lo que propone Gemini (borrador) ---


class DraftAchievement(BaseModel):
    source_id: str = Field(
        description="Id exacto del logro del perfil en el que se basa este punto."
    )
    text: str = Field(
        description=(
            "El logro reformulado para esta oferta, en el idioma del perfil. "
            "Conserva todas las cifras, porcentajes y datos del original sin cambiarlos."
        )
    )


class DraftExperience(BaseModel):
    experience_id: str = Field(description="Id exacto de la experiencia del perfil.")
    achievements: list[DraftAchievement] = Field(
        description="Los logros de esa experiencia más relevantes para la oferta, del más al menos relevante."
    )


class TailoredCVDraft(BaseModel):
    """Lo único que genera Gemini. Empresas, cargos y fechas los pone el código."""

    summary: str = Field(
        description=(
            "Resumen profesional de 2 o 3 frases adaptado a la oferta, en el idioma del perfil. "
            "Solo puede afirmar lo que se deduce del perfil."
        )
    )
    experiences: list[DraftExperience] = Field(
        description="Todas las experiencias del perfil, de más a menos relevante."
    )
    skills: list[str] = Field(
        description=(
            "Nombres de skills del perfil a destacar, copiados exactamente tal cual "
            "aparecen en el perfil. No incluyas ninguna que no esté en el perfil."
        )
    )


# --- CV adaptado final: borrador validado + datos del perfil ---


class TailoredAchievement(BaseModel):
    source_id: str
    text: str
    original_text: str


class TailoredExperience(BaseModel):
    id: str
    company: str
    title: str
    location: str | None
    start: str
    end: str | None
    achievements: list[TailoredAchievement]


class TailoredCV(BaseModel):
    language: str
    personal: Personal
    headline: str
    summary: str
    experience: list[TailoredExperience]
    education: list[Education]
    skills: list[Skill]
    languages: list[Language]
    certifications: list[str]
    volunteering: list[Volunteering]
    projects: list[Project]
    warnings: list[str] = []


# --- Matching de skills: lo que propone Gemini (borrador) ---


class SkillCoverage(BaseModel):
    offer_skill: str = Field(
        description="Una skill de la oferta, copiada exactamente como aparece en su lista."
    )
    profile_skill: str | None = Field(
        description=(
            "Nombre exacto de la skill del perfil que la cubre, copiado tal cual. Solo "
            "equivalencias reales ('GCP' y 'Google Cloud Platform'), nunca parecidas "
            "('Java' no cubre 'JavaScript'). null si ninguna la cubre."
        )
    )


class SkillMatchDraft(BaseModel):
    """Lo único que genera Gemini en el matching. La puntuación la calcula el código."""

    must_have: list[SkillCoverage] = Field(description="Una entrada por cada skill de must_have_skills.")
    nice_to_have: list[SkillCoverage] = Field(description="Una entrada por cada skill de nice_to_have.")


# --- Matching de skills final: borrador validado + puntuación ---


class SkillMatch(BaseModel):
    # 0-100: 80 % las obligatorias y 20 % las deseables (decisión 023)
    score: int
    # Skills de la oferta que cubre el perfil, con el nombre de la oferta
    matched: list[str]
    # Obligatorias que el perfil no cubre: lo que hay que preparar o explicar
    gaps: list[str]
    missing_nice_to_have: list[str]


# --- Candidatura: lo que se guarda en Firestore (applications/{id}) ---

ApplicationStatus = Literal[
    "cv_ready", "applied", "screening", "interview", "offer", "rejected", "ghosted"
]


class Application(BaseModel):
    """Una oferta y el CV generado para ella.

    El id es el nombre del documento, no un campo dentro de él. Los ficheros
    (offer.txt, cv.pdf) van en Cloud Storage bajo applications/{id}/, así que
    sus rutas se deducen del id y no se guardan.
    """

    id: uuid.UUID
    created_at: datetime
    language: str
    extracted: ExtractedOffer
    warnings: list[str]
    # Con valor por defecto: las candidaturas anteriores al sprint 4 no los tienen
    status: ApplicationStatus = "cv_ready"
    match: SkillMatch | None = None


# --- Eventos para BigQuery: lo que viaja por el topic application-events ---


class ApplicationEvent(BaseModel):
    """Un cambio en una candidatura. Cada campo es una columna de la tabla de BigQuery.

    No lleva fecha: la subscription de BigQuery escribe la hora de publicación
    (publish_time) junto a cada fila.
    """

    # Lo genera quien publica: Pub/Sub puede escribir la misma fila dos veces y
    # la vista de BigQuery se queda con una por event_id
    event_id: str
    application_id: str
    event_type: Literal["created", "status_changed"]
    from_status: ApplicationStatus | None = None
    to_status: ApplicationStatus
    company: str | None
    title: str
    match_score: int | None = None


# --- Trabajo asíncrono: lo que se guarda en Firestore (tasks/{id}) ---

TaskState = Literal["queued", "running", "done", "failed"]


class Task(BaseModel):
    """Un trabajo que hace el worker. El frontend consulta su estado por polling.

    La api crea el task y genera también el id de la candidatura que saldrá
    de él; la oferta ya está en Cloud Storage (applications/{id}/offer.txt)
    cuando se publica el mensaje.
    """

    id: uuid.UUID
    application_id: uuid.UUID
    type: Literal["generate_cv"] = "generate_cv"
    state: TaskState = "queued"
    # Idioma pedido para el CV; None: el de la oferta
    language: str | None = None
    # Cuántas veces ha empezado el worker este task (cada entrega de Pub/Sub suma una)
    attempts: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskMessage(BaseModel):
    """Lo que viaja en el mensaje de Pub/Sub: solo el id, el resto está en el task."""

    task_id: uuid.UUID
