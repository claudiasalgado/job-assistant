# job-assistant

Adapta un CV a una oferta de empleo con Gemini, sin dejar que el modelo invente nada.

Gemini propone qué contenido del perfil mostrar y cómo redactarlo para la oferta. El código valida esa propuesta contra el perfil antes de montar el PDF: lo que no se puede verificar se descarta o vuelve al texto original, y cada cambio queda anotado como aviso.

## Cómo funciona

```
oferta.txt ──▶ extractor (Gemini) ──▶ ExtractedOffer
                                          │
profile.<idioma>.json ────────────────────┤
                                          ▼
                              adaptador (Gemini) ──▶ borrador
                                                        │
                                          validación en código
                                                        │
                                                        ▼
                                  TailoredCV ──▶ Jinja2 + WeasyPrint ──▶ PDF
```

- **Extractor** (`services/worker/src/worker/extractor.py`): convierte el texto de la oferta en datos estructurados, con salida JSON forzada por un esquema Pydantic y temperatura 0.
- **Adaptador** (`tailor.py`): Gemini elige y reescribe logros, ordena skills y escribe el resumen. Recibe el perfil profesional, nunca los datos personales.
- **Validación** (`build_tailored_cv`): descarta identificadores inventados, devuelve al texto original los logros con cifras cambiadas, avisa de experiencias omitidas, de skills que no están en el perfil y de niveles profesionales en el resumen.
- **Render** (`render.py`): plantilla HTML única y PDF/UA accesible, pensado para que lo lea un ATS.

Elegir idioma es elegir perfil: hay un `profile.es.json` y un `profile.en.json`, y Gemini no traduce.

## Uso

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/), un proyecto de GCP con Vertex AI y credenciales por defecto (`gcloud auth application-default login`). En macOS, WeasyPrint necesita `brew install pango`.

```bash
cp .env.example .env          # y rellena tu proyecto de GCP
uv sync --all-packages
uv run --package worker --env-file .env cv data/samples/offer_01.txt --lang es
```

El PDF se guarda en `data/private/output/`. Los perfiles y ofertas reales van en `data/private/`, que git ignora. El repo solo contiene datos de ejemplo ficticios en `data/samples/`.

## Estructura

```
packages/core/      modelos Pydantic compartidos
services/worker/    extracción, adaptación, validación y PDF
services/api/       API HTTP (pendiente)
data/samples/       ofertas y perfiles ficticios
docs/decisiones.md  registro de decisiones de arquitectura
```

## Decisiones

Cada decisión, con la alternativa descartada y el motivo, está en [docs/decisiones.md](docs/decisiones.md).

## Limitaciones conocidas

- El texto libre (resumen y logros reescritos) no se puede validar del todo con reglas: a veces atribuye tareas de la oferta o añade finalidades. La persona revisa cada CV antes de enviarlo; un LLM como juez está en el roadmap.
- Dos ofertas sin nombre de empresa, o dos CV para la misma empresa e idioma, generan el mismo fichero y el segundo sobrescribe al primero.
- Las skills duplicadas a propósito para los ATS ("GCP" y "Google Cloud Platform") pueden salir juntas en el CV.

## Próximos pasos

API en Cloud Run con un worker que procesa las ofertas por Pub/Sub, persistencia en Firestore y Cloud Storage, métricas en BigQuery, matching entre oferta y perfil antes de generar el CV, e infraestructura con Terraform.
