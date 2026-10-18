import os
from pathlib import Path

from core.models import ExtractedOffer
from google import genai
from google.genai import types

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract_offer.md"


def extract_offer(offer_text: str, client: genai.Client | None = None) -> ExtractedOffer:
    """Extrae los datos estructurados de una oferta con Gemini en Vertex AI."""
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise RuntimeError("Falta la variable de entorno GEMINI_MODEL (ver .env.example)")

    # Sin argumentos, el cliente lee proyecto, región y modo Vertex del entorno
    client = client or genai.Client()

    response = client.models.generate_content(
        model=model,
        contents=offer_text,
        config=types.GenerateContentConfig(
            system_instruction=PROMPT_PATH.read_text(encoding="utf-8"),
            response_mime_type="application/json",
            response_json_schema=ExtractedOffer.model_json_schema(),
            # Extraer no es creativo: la misma oferta debe dar el mismo JSON
            temperature=0,
        ),
    )

    if not response.text:
        raise ValueError("Gemini devolvió una respuesta vacía (¿filtro de seguridad?)")

    return ExtractedOffer.model_validate_json(response.text)
