#!/usr/bin/env bash
# Identidades del sprint 3 (decisión 022). Se puede repetir sin duplicar nada.
#   bash infra/iam-worker.sh

set -euo pipefail

PROJECT=job-assistant-clau
BUCKET=gs://clau-job-assistant

# Crea la service account solo si no existe (create falla si ya está)
ensure_sa() {
  gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" --project="$PROJECT" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$1" --project="$PROJECT" --description="$2" --quiet
}

# --- worker-runtime: la identidad con la que se ejecuta el worker ---
ensure_sa worker-runtime "Identidad del servicio worker en Cloud Run"
WORKER="serviceAccount:worker-runtime@${PROJECT}.iam.gserviceaccount.com"

# Firestore: leer y actualizar tasks, guardar candidaturas
gcloud projects add-iam-policy-binding "$PROJECT" --member="$WORKER" \
  --role=roles/datastore.user --condition=None --quiet --format=none
# Vertex AI: desde el sprint 3, solo el worker llama a Gemini
gcloud projects add-iam-policy-binding "$PROJECT" --member="$WORKER" \
  --role=roles/aiplatform.user --condition=None --quiet --format=none
# Cloud Storage: leer la oferta y los perfiles, escribir el PDF
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="$WORKER" \
  --role=roles/storage.objectUser --quiet --format=none

# --- pubsub-push: la identidad con la que Pub/Sub firma sus llamadas al worker ---
# Separada de worker-runtime: quien llama y quien se ejecuta no tienen por qué ser el mismo
ensure_sa pubsub-push "Identidad de Pub/Sub al entregar mensajes al worker"

echo "Identidades del worker listas"
