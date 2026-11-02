#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=adefifp22909
REGION=us-central1
ZONE=us-central1-a
DB_INSTANCE=hw5-db-instance
STOPPER_JOB=check-sql-hourly
SECRET=hw6-db-pass
BUCKET=cs528-pagerank-eddielu-1790373540
VM=hw6-models
SA_NAME=hw6-models-sa
SA_EMAIL=$SA_NAME@$PROJECT.iam.gserviceaccount.com
OUT=gs://$BUCKET/hw6

gcloud config set project "$PROJECT" --quiet 2>/dev/null

cleanup() {
  echo
  echo "== Cleanup: deleting the VM, stopping the database, resuming the hourly stopper"
  gcloud compute instances delete "$VM" --zone="$ZONE" --quiet 2>/dev/null || true
  gcloud sql instances patch "$DB_INSTANCE" --activation-policy=NEVER --quiet || true
  gcloud scheduler jobs resume "$STOPPER_JOB" --location="$REGION" --quiet || true
  echo "Database activation policy: $(gcloud sql instances describe "$DB_INSTANCE" --format='value(settings.activationPolicy)')"
  echo "Stopper job state: $(gcloud scheduler jobs describe "$STOPPER_JOB" --location="$REGION" --format='value(state)')"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

echo "== Starting the database and pausing the hourly stopper"
gcloud scheduler jobs pause "$STOPPER_JOB" --location="$REGION" --quiet 2>/dev/null || true
gcloud sql instances patch "$DB_INSTANCE" --activation-policy=ALWAYS --quiet
echo "Database state: $(gcloud sql instances describe "$DB_INSTANCE" --format='value(state)')"

echo "== Setting up the service account $SA_NAME"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="HW6 models VM"
  sleep 10
fi
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/cloudsql.client --condition=None >/dev/null
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin >/dev/null
echo "Roles: Cloud SQL Client (project), Secret Accessor ($SECRET only), Storage Object Admin ($BUCKET only)"

echo "== Clearing old results in $OUT/"
gcloud storage rm "$OUT/**" --quiet 2>/dev/null || true

echo "== Creating the VM $VM"
gcloud compute instances delete "$VM" --zone="$ZONE" --quiet 2>/dev/null || true
gcloud compute instances create "$VM" \
  --zone="$ZONE" \
  --machine-type=e2-medium \
  --image-family=debian-12 --image-project=debian-cloud \
  --service-account="$SA_EMAIL" --scopes=cloud-platform \
  --metadata=bucket="$BUCKET" \
  --metadata-from-file=startup-script=startup.sh,hw6-models=hw6_models.py,migrate-sql=migrate.sql,requirements=requirements.txt

echo "== Waiting for results (usually 3-5 minutes)"
for i in $(seq 1 60); do
  if gcloud storage ls "$OUT/summary.txt" >/dev/null 2>&1; then
    break
  fi
  if gcloud storage ls "$OUT/error.txt" >/dev/null 2>&1; then
    echo "The VM reported an error:"
    gcloud storage cat "$OUT/error.txt"
    exit 1
  fi
  if [ "$i" -eq 60 ]; then
    echo "Timed out after 15 minutes with no results"
    exit 1
  fi
  sleep 15
done

echo
echo "===== $OUT/summary.txt ====="
gcloud storage cat "$OUT/summary.txt"
echo
echo "===== $OUT/ip_country_test_predictions.csv (first 15 rows) ====="
gcloud storage cat "$OUT/ip_country_test_predictions.csv" | head -n 16 || true
echo
echo "===== $OUT/income_test_predictions.csv (first 15 rows) ====="
gcloud storage cat "$OUT/income_test_predictions.csv" | head -n 16 || true
echo
echo "===== Files in $OUT/ ====="
gcloud storage ls -l "$OUT/"
