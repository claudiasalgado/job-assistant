# Imagen del servicio api. Desde el sprint 3 no lleva WeasyPrint ni Gemini: eso es del worker.
# El build context es la raíz del repo, porque core está fuera de esta carpeta:
#   docker build -f services/api/Dockerfile -t api .

FROM python:3.12-slim-bookworm

# uv copiado de su imagen oficial, con la misma versión que en local
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

# Bytecode compilado en el build (arranque en frío más rápido), copiar en vez de
# enlazar (la caché de uv no existe en la imagen final) y usar el Python de la imagen
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Primero solo lo que define las dependencias: mientras no cambien, Docker reutiliza
# esta capa y no reinstala nada al tocar el código
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY services/api/pyproject.toml services/api/
RUN uv sync --frozen --no-dev --package api --no-install-workspace

# Después el código, copiado carpeta a carpeta y nunca con "COPY . .": así no
# pueden colarse data/private ni el .env aunque falle el .dockerignore
COPY packages/core packages/core
COPY services/api services/api
RUN uv sync --frozen --no-dev --package api --no-editable

# Sin root: si alguien consigue ejecutar código en el contenedor, no es administrador
RUN useradd --create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH"

# Cloud Run envía el tráfico al puerto 8080 por defecto
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
