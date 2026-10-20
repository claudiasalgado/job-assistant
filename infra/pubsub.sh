#!/usr/bin/env bash
# Cola de trabajos del sprint 3 (decisión 022): api -> topic cv-tasks -> push al worker,
# y tras 5 intentos fallidos -> topic cv-tasks-dead. Se puede repetir sin duplicar nada.
# Requiere el worker ya desplegado (necesita su URL).
#   bash infra/pubsub.sh

set -euo pipefail

PROJECT=job-assistant-clau
PROJECT_NUMBER=333565578201
REGION=europe-west4
PUSH_SA="pubsub-push@${PROJECT}.iam.gserviceaccount.com"
# El agente de servicio de Pub/Sub: la cuenta de Google que mueve los mensajes a la DLQ
PUBSUB_AGENT="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

WORKER_URL=$(gcloud run services describe worker --project="$PROJECT" --region="$REGION" --format="value(status.url)")

exists() { gcloud pubsub "$1" describe "$2" --project="$PROJECT" >/dev/null 2>&1; }

# --- Topics ---
exists topics cv-tasks || gcloud pubsub topics create cv-tasks --project="$PROJECT" --quiet
exists topics cv-tasks-dead || gcloud pubsub topics create cv-tasks-dead --project="$PROJECT" --quiet

# Un topic sin subscriptions descarta lo que recibe: esta guarda los mensajes muertos
# 7 días para poder mirarlos (pull: nadie los consume automáticamente)
exists subscriptions cv-tasks-dead-inspect || gcloud pubsub subscriptions create cv-tasks-dead-inspect \
  --project="$PROJECT" --topic=cv-tasks-dead --message-retention-duration=7d --quiet

# --- Subscription push al worker ---
# --push-auth-service-account: Pub/Sub firma cada llamada con un token OIDC de pubsub-push
# --push-auth-token-audience: el token va dirigido a la URL del servicio, que es lo que comprueba Cloud Run
# --ack-deadline=600: lo máximo que Pub/Sub espera la respuesta antes de darla por fallida
# --min/max-retry-delay: espera creciente entre reintentos (10 s, 20 s, 40 s... hasta 10 min)
# --dead-letter-topic + --max-delivery-attempts=5: al quinto fallo, a cv-tasks-dead
SUB_FLAGS=(
  --project="$PROJECT"
  --push-endpoint="${WORKER_URL}/pubsub"
  --push-auth-service-account="$PUSH_SA"
  --push-auth-token-audience="$WORKER_URL"
  --ack-deadline=600
  --min-retry-delay=10s
  --max-retry-delay=600s
  --dead-letter-topic=cv-tasks-dead
  --max-delivery-attempts=5
  --quiet
)
if exists subscriptions cv-tasks-worker; then
  gcloud pubsub subscriptions update cv-tasks-worker "${SUB_FLAGS[@]}"
else
  gcloud pubsub subscriptions create cv-tasks-worker --topic=cv-tasks "${SUB_FLAGS[@]}"
fi

# --- Permisos que conectan las piezas ---
# La api publica trabajos (solo en este topic)
gcloud pubsub topics add-iam-policy-binding cv-tasks --project="$PROJECT" \
  --member="serviceAccount:api-runtime@${PROJECT}.iam.gserviceaccount.com" \
  --role=roles/pubsub.publisher --quiet --format=none
# Pub/Sub puede llamar al worker (solo al worker)
gcloud run services add-iam-policy-binding worker --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${PUSH_SA}" --role=roles/run.invoker --quiet --format=none
# Para la DLQ, el agente de Pub/Sub tiene que poder publicar en el topic muerto
# y quitar el mensaje de la subscription original
gcloud pubsub topics add-iam-policy-binding cv-tasks-dead --project="$PROJECT" \
  --member="$PUBSUB_AGENT" --role=roles/pubsub.publisher --quiet --format=none
gcloud pubsub subscriptions add-iam-policy-binding cv-tasks-worker --project="$PROJECT" \
  --member="$PUBSUB_AGENT" --role=roles/pubsub.subscriber --quiet --format=none

echo "Pub/Sub listo: cv-tasks -> ${WORKER_URL}/pubsub (DLQ: cv-tasks-dead)"
