import json
import os
import re
import unicodedata
from pathlib import Path

from core.models import (
    ExtractedOffer,
    Profile,
    TailoredAchievement,
    TailoredCV,
    TailoredCVDraft,
    TailoredExperience,
)
from google import genai
from google.genai import types

PROMPT_PATH = Path(__file__).parent / "prompts" / "tailor_cv.md"

# Campos del perfil que nunca se envían a Gemini
PROFILE_FIELDS_NOT_SENT = {"personal", "seniority"}

# Enteros y decimales con punto o coma: "3", "80", "0,86", "1.000"
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Palabras de nivel que pueden aparecer en el resumen, en palabras completas
SENIORITY_RE = re.compile(r"\b(intern|junior|mid|senior|lead)\b")


def tailor_cv(
    offer: ExtractedOffer, profile: Profile, client: genai.Client | None = None
) -> TailoredCV:
    """Genera un CV adaptado a la oferta: Gemini propone, el código valida y monta.

    El CV sale en el idioma del perfil que se pase: elegir idioma es elegir perfil.
    """
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise RuntimeError("Falta la variable de entorno GEMINI_MODEL (ver .env.example)")

    client = client or genai.Client()

    # Gemini ve todo lo profesional para escribir un buen resumen (decisión 014).
    # Fuera: los datos personales, que no aportan, y el seniority, para que no lo
    # escriba. Es una lista negra: un campo sensible nuevo en Profile se añade aquí.
    payload = {
        "offer": offer.model_dump(),
        "profile": profile.model_dump(exclude=PROFILE_FIELDS_NOT_SENT),
    }

    response = client.models.generate_content(
        model=model,
        contents=json.dumps(payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_PATH.read_text(encoding="utf-8"),
            response_mime_type="application/json",
            response_json_schema=TailoredCVDraft.model_json_schema(),
        ),
    )

    if not response.text:
        raise ValueError("Gemini devolvió una respuesta vacía (¿filtro de seguridad?)")

    draft = TailoredCVDraft.model_validate_json(response.text)
    return build_tailored_cv(draft, profile)


def _numbers(text: str) -> set[str]:
    """Cifras de un texto, normalizadas para que "0,86" y "0.86" cuenten igual."""
    return {n.replace(",", ".") for n in NUMBER_RE.findall(text)}


def _seniority_words(text: str) -> set[str]:
    """Niveles que menciona un texto, sin tildes para que "sénior" cuente como "senior"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return set(SENIORITY_RE.findall(plain))


def build_tailored_cv(draft: TailoredCVDraft, profile: Profile) -> TailoredCV:
    """Valida el borrador contra el perfil y monta el CV final.

    Lo que no existe en el perfil se descarta (decisión 007); un logro con
    las cifras cambiadas vuelve a su texto original (decisión 013). Todo
    queda anotado en warnings.
    """
    warnings: list[str] = []
    experiences_by_id = {e.id: e for e in profile.experience}

    experience: list[TailoredExperience] = []
    seen_experiences: set[str] = set()
    for draft_exp in draft.experiences:
        source_exp = experiences_by_id.get(draft_exp.experience_id)
        if source_exp is None:
            warnings.append(f"Experiencia inexistente descartada: {draft_exp.experience_id}")
            continue
        if source_exp.id in seen_experiences:
            continue
        seen_experiences.add(source_exp.id)

        # Solo vale un logro de esta misma experiencia, no de otra
        achievements_by_id = {a.id: a for a in source_exp.achievements}
        achievements: list[TailoredAchievement] = []
        seen_achievements: set[str] = set()
        for draft_ach in draft_exp.achievements:
            original = achievements_by_id.get(draft_ach.source_id)
            if original is None:
                warnings.append(
                    f"Logro descartado: {draft_ach.source_id} no pertenece a {source_exp.id}"
                )
                continue
            if original.id in seen_achievements:
                continue
            seen_achievements.add(original.id)

            text = draft_ach.text
            # El perfil está en el idioma del CV, así que el original siempre es
            # un respaldo válido: se pierde la adaptación, nunca el logro (decisión 013)
            if _numbers(text) != _numbers(original.text):
                warnings.append(
                    f"Logro {original.id} con el texto original: la versión adaptada "
                    f"cambiaba sus cifras ({text!r})"
                )
                text = original.text
            achievements.append(
                TailoredAchievement(source_id=original.id, text=text, original_text=original.text)
            )

        if not achievements:
            warnings.append(f"La experiencia {source_exp.id} se queda sin logros")

        experience.append(
            TailoredExperience(
                id=source_exp.id,
                company=source_exp.company,
                title=source_exp.title,
                location=source_exp.location,
                start=source_exp.start,
                end=source_exp.end,
                achievements=achievements,
            )
        )

    # El prompt pide incluirlas todas (decisión 009): solo se avisa, no se añaden
    for source_exp in profile.experience:
        if source_exp.id not in seen_experiences:
            warnings.append(f"Experiencia del perfil omitida por Gemini: {source_exp.id}")

    # El resumen no menciona ningún nivel: la persona se presenta en su titular (decisión 011)
    for level in sorted(_seniority_words(draft.summary)):
        warnings.append(f"El resumen menciona un nivel profesional: {level}")

    # Sin distinguir mayúsculas, pero siempre con el nombre tal y como está en el perfil
    skills_by_name = {s.name.casefold(): s for s in profile.skills}
    skills = []
    for name in dict.fromkeys(n.casefold() for n in draft.skills):
        skill = skills_by_name.get(name)
        if skill is None:
            warnings.append(f"Skill que no está en el perfil descartada: {name}")
            continue
        skills.append(skill)

    return TailoredCV(
        language=profile.language,
        personal=profile.personal,
        headline=profile.headline,
        summary=draft.summary,
        experience=experience,
        education=profile.education,
        skills=skills,
        languages=profile.languages,
        certifications=profile.certifications,
        volunteering=profile.volunteering,
        projects=profile.projects,
        warnings=warnings,
    )
