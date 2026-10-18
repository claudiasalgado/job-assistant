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
