import json
import os
import re
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

# Enteros y decimales con punto o coma: "3", "80", "0,86", "1.000"
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def tailor_cv(
    offer: ExtractedOffer, profile: Profile, client: genai.Client | None = None
) -> TailoredCV:
    """Genera un CV adaptado a la oferta: Gemini propone, el código valida y monta."""
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise RuntimeError("Falta la variable de entorno GEMINI_MODEL (ver .env.example)")

    client = client or genai.Client()

    # Minimización de datos: Gemini no necesita nombre, email ni teléfono
    payload = {
        "offer": offer.model_dump(),
        "profile": profile.model_dump(exclude={"personal"}),
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
    return build_tailored_cv(draft, profile, language=offer.language)


def _numbers(text: str) -> set[str]:
    """Cifras de un texto, normalizadas para que "0,86" y "0.86" cuenten igual."""
    return {n.replace(",", ".") for n in NUMBER_RE.findall(text)}


def build_tailored_cv(draft: TailoredCVDraft, profile: Profile, language: str) -> TailoredCV:
    """Valida el borrador contra el perfil y monta el CV final.

    Todo lo que no se puede verificar en el perfil se descarta y queda
    anotado en warnings (decisión 007).
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
            if _numbers(draft_ach.text) != _numbers(original.text):
                warnings.append(
                    f"Logro descartado: {original.id} cambia las cifras del original "
                    f"({draft_ach.text!r})"
                )
                continue
            seen_achievements.add(original.id)
            achievements.append(
                TailoredAchievement(
                    source_id=original.id, text=draft_ach.text, original_text=original.text
                )
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
        language=language,
        personal=profile.personal,
        summary=draft.summary,
        experience=experience,
        education=profile.education,
        skills=skills,
        languages=profile.languages,
        warnings=warnings,
    )
