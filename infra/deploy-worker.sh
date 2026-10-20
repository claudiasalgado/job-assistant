#!/usr/bin/env bash
# Construye la imagen del worker en Cloud Build y la despliega en Cloud Run.
# Se lanza desde la raíz del repo:
#   bash infra/deploy-worker.sh

set -euo pipefail

PROJECT=job-assistant-clau
REGION=europe-west4

# 1. Build en Cloud Build (amd64, en la UE) y push a Artifact Registry
gcloud builds submit . \
  --project="$PROJECT" \
  --region="$REGION" \
  --config=infra/cloudbuild.yaml \
  --substitutions=_SERVICE=worker \
  --default-buckets-behavior=regional-user-owned-bucket

# 2. Nueva revisión de Cloud Run con esa imagen
# --no-allow-unauthenticated sin IAP: solo lo llama Pub/Sub, con la cuenta pubsub-push
# --service-account: worker-runtime, con Gemini, Firestore y el bucket (decisión 022)
# --timeout=300: un CV tarda ~20 s; por debajo del plazo de 600 s que Pub/Sub espera al push
# --concurrency=4: cada petición maqueta un PDF; con más a la vez, 1 GiB se quedaría corto
# --memory=1Gi: WeasyPrint con las fuentes cabe justo en los 512Mi por defecto
gcloud run deploy worker \
  --project="$PROJECT" \
  --region="$REGION" \
  --image="${REGION}-docker.pkg.dev/${PROJECT}/job-assistant/worker:latest" \
  --service-account="worker-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --max-instances=2 \
  --concurrency=4 \
  --timeout=300 \
  --memory=1Gi \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},GOOGLE_GENAI_USE_ENTERPRISE=true,GEMINI_MODEL=gemini-2.5-flash,GCS_BUCKET=clau-job-assistant" \
  --quiet
