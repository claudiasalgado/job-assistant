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
