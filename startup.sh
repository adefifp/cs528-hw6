#!/bin/bash
MD=http://metadata.google.internal/computeMetadata/v1/instance/attributes
LOG=/var/log/hw6.log
get() { curl -sf -H "Metadata-Flavor: Google" "$MD/$1"; }
BUCKET=$(get bucket)

fail() {
  echo "FAILED: $1" >> "$LOG"
  gcloud storage cp "$LOG" "gs://$BUCKET/hw6/error.txt"
  exit 1
}
run() { echo "+ $*" >> "$LOG"; "$@" >> "$LOG" 2>&1 || fail "$*"; }

mkdir -p /opt/hw6 && cd /opt/hw6 || fail "mkdir"
get hw6-models   > hw6_models.py    || fail "download hw6_models.py"
get migrate-sql  > migrate.sql      || fail "download migrate.sql"
get requirements > requirements.txt || fail "download requirements.txt"

run apt-get -o DPkg::Lock::Timeout=300 update -y
run apt-get -o DPkg::Lock::Timeout=300 install -y python3-venv
run python3 -m venv .venv
run .venv/bin/pip install -q -r requirements.txt
run .venv/bin/python hw6_models.py
echo "DONE" >> "$LOG"
