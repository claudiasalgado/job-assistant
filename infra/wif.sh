#!/usr/bin/env bash
# Workload Identity Federation para que GitHub Actions despliegue sin claves JSON
# (decisión 025). Se puede repetir sin duplicar nada.
#   bash infra/wif.sh

set -euo pipefail

PROJECT=job-assistant-clau
PROJECT_NUMBER=333565578201
REGION=europe-west4
# El ID numérico del repo no cambia si se renombra o se borra; el nombre sí podría
# reutilizarlo otra persona. Sale de: gh api repos/claudiasalgado/job-assistant --jq .id
REPO_ID=1427334280
SOURCE_BUCKET=gs://${PROJECT}_${REGION}_cloudbuild

# Crea la service account solo si no existe (create falla si ya está). Una cuenta recién
# creada tarda unos segundos en ser válida en la política del proyecto: sin la espera,
# add-iam-policy-binding falla con "does not exist"
ensure_sa() {
  gcloud iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com" --project="$PROJECT" >/dev/null 2>&1 \
    || { gcloud iam service-accounts create "$1" --project="$PROJECT" --description="$2" --quiet && sleep 30; }
}

# --- Pool y proveedor: GCP aprende a fiarse de los tokens que firma GitHub ---
# Un pool agrupa identidades externas; el proveedor dice quién las firma y qué se acepta
gcloud iam workload-identity-pools describe github --project="$PROJECT" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create github \
       --project="$PROJECT" --location=global --display-name="GitHub Actions"

# --issuer-uri: GitHub firma un token OIDC en cada job; GCP valida la firma con sus claves públicas
# --attribute-mapping: copia campos del token a atributos que IAM puede usar en reglas
# --attribute-condition: solo se aceptan tokens de este repo y de la rama main;
#   un pull request o un fork no pueden obtener credenciales
gcloud iam workload-identity-pools providers describe github-actions \
  --project="$PROJECT" --location=global --workload-identity-pool=github >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc github-actions \
       --project="$PROJECT" --location=global --workload-identity-pool=github \
       --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" \
       --attribute-condition="assertion.repository_id=='${REPO_ID}' && assertion.ref=='refs/heads/main'"

# --- ci-build: la identidad con la que corre el build en Cloud Build ---
# Sin ella, el build correría como la cuenta por defecto de Compute, que tiene Editor
ensure_sa ci-build "Identidad de Cloud Build en los builds lanzados por el CI"
BUILD="serviceAccount:ci-build@${PROJECT}.iam.gserviceaccount.com"

# Subir la imagen, solo a este repositorio
gcloud artifacts repositories add-iam-policy-binding job-assistant \
  --project="$PROJECT" --location="$REGION" --member="$BUILD" \
  --role=roles/artifactregistry.writer --quiet --format=none
# Leer el código fuente que sube gcloud builds submit
gcloud storage buckets add-iam-policy-binding "$SOURCE_BUCKET" --member="$BUILD" \
  --role=roles/storage.objectViewer --quiet --format=none
# Escribir los logs del build en Cloud Logging
gcloud projects add-iam-policy-binding "$PROJECT" --member="$BUILD" \
  --role=roles/logging.logWriter --condition=None --quiet --format=none

# --- github-deployer: la identidad que GitHub Actions toma prestada ---
ensure_sa github-deployer "Identidad del CI de GitHub al desplegar"
DEPLOYER="github-deployer@${PROJECT}.iam.gserviceaccount.com"

# Quién puede hacerse pasar por ella: solo los tokens de este repo que pasan la condición
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" --project="$PROJECT" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository_id/${REPO_ID}" \
  --role=roles/iam.workloadIdentityUser --quiet --format=none

# Lanzar builds
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOYER" \
  --role=roles/cloudbuild.builds.editor --condition=None --quiet --format=none
# gcloud builds submit comprueba que el bucket de fuentes existe y sube el código ahí
gcloud storage buckets add-iam-policy-binding "$SOURCE_BUCKET" --member="serviceAccount:$DEPLOYER" \
  --role=roles/storage.admin --quiet --format=none
# Hacer que el build corra como ci-build
gcloud iam service-accounts add-iam-policy-binding "ci-build@${PROJECT}.iam.gserviceaccount.com" \
  --project="$PROJECT" --member="serviceAccount:$DEPLOYER" \
  --role=roles/iam.serviceAccountUser --quiet --format=none

# Cambiar la imagen de los dos servicios, y nada más: run.developer no puede tocar
# quién tiene acceso (eso exige run.admin), así que el CI no puede abrir la api a internet
for SERVICE in api worker; do
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --project="$PROJECT" --region="$REGION" --member="serviceAccount:$DEPLOYER" \
    --role=roles/run.developer --quiet --format=none
  # Cloud Run exige poder actuar como la identidad del servicio en cada revisión nueva
  gcloud iam service-accounts add-iam-policy-binding "${SERVICE}-runtime@${PROJECT}.iam.gserviceaccount.com" \
    --project="$PROJECT" --member="serviceAccount:$DEPLOYER" \
    --role=roles/iam.serviceAccountUser --quiet --format=none
done

echo "Workload Identity Federation lista"
echo "Proveedor: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-actions"
echo "Cuenta:    ${DEPLOYER}"
