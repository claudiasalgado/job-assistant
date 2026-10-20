#!/usr/bin/env bash
# Permisos mínimos de la service account api-runtime (decisión 019).
# Se ejecuta una vez; repetirlo no duplica nada. Lo sustituirá Terraform en el sprint 5.
#   bash infra/iam-api.sh

# -e: para en el primer error; -u: error si una variable no existe; pipefail: un fallo dentro de un | también cuenta
set -euo pipefail

PROJECT=job-assistant-clau
BUCKET=gs://clau-job-assistant
MEMBER="serviceAccount:api-runtime@${PROJECT}.iam.gserviceaccount.com"

# Firestore: leer y escribir documentos (Firestore usa los roles de Datastore)
gcloud projects add-iam-policy-binding "$PROJECT" --member="$MEMBER" \
  --role=roles/datastore.user --condition=None --quiet --format=none

# Vertex AI: desde el sprint 3 la api ya no llama a Gemini (lo hace el worker), así
# que no tiene aiplatform.user. Publicar en cv-tasks se concede en infra/pubsub.sh

# Cloud Storage: objetos de este bucket y de ningún otro
gcloud storage buckets add-iam-policy-binding "$BUCKET" --member="$MEMBER" \
  --role=roles/storage.objectUser --quiet --format=none

echo "Permisos concedidos a $MEMBER"

# --- IAP delante del servicio api (decisión 020) ---
PROJECT_NUMBER=333565578201
REGION=europe-west4
# La cuenta con la que se ejecuta el script: así el email no queda escrito en el repo
USER_EMAIL=$(gcloud config get-value account 2>/dev/null)

# El agente de IAP es quien llama de verdad a Cloud Run, así que necesita ser invoker
gcloud run services add-iam-policy-binding api --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role=roles/run.invoker --quiet --format=none

# Quién puede pasar por IAP: solo Clau
gcloud iap web add-iam-policy-binding --project="$PROJECT" --region="$REGION" \
  --resource-type=cloud-run --service=api \
  --member="user:${USER_EMAIL}" --role=roles/iap.httpsResourceAccessor --quiet --format=none

echo "IAP: acceso concedido a $USER_EMAIL"
