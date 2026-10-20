#!/usr/bin/env bash
# Construye la imagen de la api en Cloud Build y la despliega en Cloud Run.
# Se lanza desde la raíz del repo:
#   bash infra/deploy-api.sh

set -euo pipefail

PROJECT=job-assistant-clau
REGION=europe-west4

# 1. Build en Cloud Build (amd64, en la UE) y push a Artifact Registry
gcloud builds submit . \
  --project="$PROJECT" \
  --region="$REGION" \
  --config=infra/cloudbuild.yaml \
  --substitutions=_SERVICE=api \
  --default-buckets-behavior=regional-user-owned-bucket

# 2. Nueva revisión de Cloud Run con esa imagen
# --no-allow-unauthenticated: solo entra quien tenga run.invoker (tú, como Owner, y el agente de IAP)
# --iap: login con Google delante del servicio (decisión 020); el cliente OAuth se configuró a mano
# --service-account: se ejecuta como api-runtime y no como la cuenta por defecto con Editor
# --max-instances=2: tope de coste; un bucle de peticiones no puede escalar sin límite
# --memory=512Mi: desde el sprint 3 la api ya no genera PDFs (decisión 022)
# Sin --min-instances: escala a cero y no cuesta nada mientras no se usa
gcloud run deploy api \
  --project="$PROJECT" \
  --region="$REGION" \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/job-assistant/api:latest" \
  --service-account="api-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --iap \
  --max-instances=2 \
  --memory=512Mi \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},GCS_BUCKET=clau-job-assistant,TASKS_TOPIC=cv-tasks" \
  --quiet
