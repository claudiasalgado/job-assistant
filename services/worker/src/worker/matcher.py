import json
import os
from pathlib import Path

from core.models import ExtractedOffer, Profile, SkillCoverage, SkillMatch, SkillMatchDraft
from google import genai
from google.genai import types

PROMPT_PATH = Path(__file__).parent / "prompts" / "match_skills.md"

# Peso de las obligatorias en la puntuación; el resto es de las deseables (decisión 023)
MUST_HAVE_WEIGHT = 0.8


def match_skills(
    offer: ExtractedOffer, profile: Profile, client: genai.Client | None = None
) -> SkillMatch | None:
    """Compara las skills de la oferta con las del perfil: Gemini empareja, el código puntúa.

    None si la oferta no pide ninguna skill: no hay nada que puntuar.
    """
    if not offer.must_have_skills and not offer.nice_to_have:
        return None

    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise RuntimeError("Falta la variable de entorno GEMINI_MODEL (ver .env.example)")

    client = client or genai.Client()

    # Solo los nombres: el nivel y los años no cambian si una skill cubre a otra
    payload = {
        "must_have_skills": offer.must_have_skills,
        "nice_to_have": offer.nice_to_have,
        "profile_skills": [s.name for s in profile.skills],
    }

    response = client.models.generate_content(
        model=model,
        contents=json.dumps(payload, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_PATH.read_text(encoding="utf-8"),
            response_mime_type="application/json",
            response_json_schema=SkillMatchDraft.model_json_schema(),
            # Emparejar no es creativo: la misma oferta debe dar la misma puntuación
            temperature=0,
        ),
    )

    if not response.text:
        raise ValueError("Gemini devolvió una respuesta vacía (¿filtro de seguridad?)")

    return build_skill_match(SkillMatchDraft.model_validate_json(response.text), offer, profile)


def build_skill_match(draft: SkillMatchDraft, offer: ExtractedOffer, profile: Profile) -> SkillMatch:
    """Valida el borrador y calcula la puntuación. Función pura: se prueba sin Gemini.

    Una skill de la oferta solo cuenta como cubierta si Gemini la empareja con
    un nombre que existe de verdad en el perfil (como en la decisión 007). Las
    que Gemini se salte cuentan como no cubiertas.
    """
    profile_names = {s.name.casefold() for s in profile.skills}

    def covered(offer_skills: list[str], coverage: list[SkillCoverage]) -> set[str]:
        claimed = {
            c.offer_skill.casefold()
            for c in coverage
            if c.profile_skill is not None and c.profile_skill.casefold() in profile_names
        }
        return {s for s in offer_skills if s.casefold() in claimed}

    must = covered(offer.must_have_skills, draft.must_have)
    nice = covered(offer.nice_to_have, draft.nice_to_have)

    ratios = []
    if offer.must_have_skills:
        ratios.append((MUST_HAVE_WEIGHT, len(must) / len(offer.must_have_skills)))
    if offer.nice_to_have:
        ratios.append((1 - MUST_HAVE_WEIGHT, len(nice) / len(offer.nice_to_have)))
    # Si falta una de las dos listas, la otra pesa el 100 %
    score = sum(weight * ratio for weight, ratio in ratios) / sum(weight for weight, _ in ratios)

    return SkillMatch(
        score=round(score * 100),
        matched=[s for s in offer.must_have_skills + offer.nice_to_have if s in must | nice],
        gaps=[s for s in offer.must_have_skills if s not in must],
        missing_nice_to_have=[s for s in offer.nice_to_have if s not in nice],
    )
