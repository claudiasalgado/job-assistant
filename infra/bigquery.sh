#!/usr/bin/env bash
# Analítica del sprint 4 (decisión 023): topic application-events -> subscription de
# BigQuery -> tabla application_events, sin código de ingesta. Se puede repetir.
#   bash infra/bigquery.sh

set -euo pipefail

PROJECT=job-assistant-clau
PROJECT_NUMBER=333565578201
LOCATION=europe-west4
DATASET=job_assistant
TABLE="${PROJECT}:${DATASET}.application_events"
PUBSUB_AGENT="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

exists() { gcloud pubsub "$1" describe "$2" --project="$PROJECT" >/dev/null 2>&1; }

# --- Dataset y tabla ---
bq --project_id="$PROJECT" show "$DATASET" >/dev/null 2>&1 \
  || bq --project_id="$PROJECT" --location="$LOCATION" mk --dataset --description="Seguimiento de candidaturas" "$DATASET"

# Las cuatro primeras columnas las rellena Pub/Sub (--write-metadata); el resto son los
# campos de ApplicationEvent. Particionada por día: las consultas por fecha solo leen
# (y solo pagan) los días que piden
bq --project_id="$PROJECT" show "$TABLE" >/dev/null 2>&1 || bq --project_id="$PROJECT" mk --table \
  --time_partitioning_field=publish_time --time_partitioning_type=DAY \
  --description="Un evento por cada cambio de una candidatura (append-only)" \
  "$TABLE" \
  subscription_name:STRING,message_id:STRING,publish_time:TIMESTAMP,attributes:STRING,event_id:STRING,application_id:STRING,event_type:STRING,from_status:STRING,to_status:STRING,company:STRING,title:STRING,match_score:INTEGER

# Estado actual de cada candidatura: el último evento de cada una. El primer QUALIFY
# quita filas duplicadas (Pub/Sub entrega at least once, y también a BigQuery)
bq --project_id="$PROJECT" query --use_legacy_sql=false --quiet "
CREATE OR REPLACE VIEW \`${PROJECT}.${DATASET}.applications_current\` AS
WITH events AS (
  SELECT * FROM \`${PROJECT}.${DATASET}.application_events\`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY publish_time) = 1
),
created AS (
  SELECT application_id, MIN(publish_time) AS created_at
  FROM events
  GROUP BY application_id
)
SELECT
  e.application_id,
  e.company,
  e.title,
  e.match_score,
  e.to_status AS status,
  c.created_at,
  e.publish_time AS updated_at
FROM events AS e
JOIN created AS c USING (application_id)
WHERE TRUE
QUALIFY ROW_NUMBER() OVER (PARTITION BY e.application_id ORDER BY e.publish_time DESC) = 1"

# El agente de Pub/Sub escribe en la tabla: permisos solo sobre esta tabla
bq --project_id="$PROJECT" add-iam-policy-binding --member="$PUBSUB_AGENT" --role=roles/bigquery.dataEditor "$TABLE" >/dev/null
bq --project_id="$PROJECT" add-iam-policy-binding --member="$PUBSUB_AGENT" --role=roles/bigquery.metadataViewer "$TABLE" >/dev/null

# --- Topic y subscription de BigQuery ---
exists topics application-events || gcloud pubsub topics create application-events --project="$PROJECT" --quiet
exists topics application-events-dead || gcloud pubsub topics create application-events-dead --project="$PROJECT" --quiet
exists subscriptions application-events-dead-inspect || gcloud pubsub subscriptions create application-events-dead-inspect \
  --project="$PROJECT" --topic=application-events-dead --message-retention-duration=7d --quiet

# --use-table-schema: cada campo del JSON va a su columna, en vez de todo el JSON en una
# --write-metadata: añade publish_time, message_id... (de ahí sale la fecha del evento)
# Sin --drop-unknown-fields: un campo nuevo en el evento sin su columna falla y va a la DLQ,
# en vez de perderse sin avisar
exists subscriptions application-events-bigquery || gcloud pubsub subscriptions create application-events-bigquery \
  --project="$PROJECT" \
  --topic=application-events \
  --bigquery-table="${PROJECT}.${DATASET}.application_events" \
  --use-table-schema \
  --write-metadata \
  --dead-letter-topic=application-events-dead \
  --max-delivery-attempts=5 \
  --quiet

# Quién publica eventos: la api (cambios de estado) y el worker (candidaturas nuevas)
for SA in api-runtime worker-runtime; do
  gcloud pubsub topics add-iam-policy-binding application-events --project="$PROJECT" \
    --member="serviceAccount:${SA}@${PROJECT}.iam.gserviceaccount.com" \
    --role=roles/pubsub.publisher --quiet --format=none
done
# Para la DLQ, igual que en cv-tasks (decisión 022)
gcloud pubsub topics add-iam-policy-binding application-events-dead --project="$PROJECT" \
  --member="$PUBSUB_AGENT" --role=roles/pubsub.publisher --quiet --format=none
gcloud pubsub subscriptions add-iam-policy-binding application-events-bigquery --project="$PROJECT" \
  --member="$PUBSUB_AGENT" --role=roles/pubsub.subscriber --quiet --format=none

echo "BigQuery listo: application-events -> ${DATASET}.application_events (vista applications_current)"
