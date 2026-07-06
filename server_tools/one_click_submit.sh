#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="${SERVER_URL:-http://54.46.103.244:8787}"
CHANNEL="${CHANNEL:-@sosocw}"
AUTO_UPLOAD="${AUTO_UPLOAD:-true}"
UPLOAD_META="${UPLOAD_META:-true}"
IDS_CSV="${IDS_CSV:-}"

if [[ -z "${IDS_CSV}" ]]; then
  read -r -p "Message IDs (comma separated, e.g. 13991,13993): " IDS_CSV
fi

SERVER_URL="${SERVER_URL%/}"

IFS=',' read -r -a IDS_ARRAY <<< "${IDS_CSV}"
IDS_JSON="["
first=true
for id in "${IDS_ARRAY[@]}"; do
  trimmed="$(echo "$id" | xargs)"
  if [[ -z "$trimmed" ]]; then
    continue
  fi
  if [[ "$first" == true ]]; then
    IDS_JSON="${IDS_JSON}${trimmed}"
    first=false
  else
    IDS_JSON="${IDS_JSON},${trimmed}"
  fi
done
IDS_JSON="${IDS_JSON}]"

payload=$(cat <<EOF
{
  "channel": "${CHANNEL}",
  "message_ids": ${IDS_JSON},
  "auto_upload": ${AUTO_UPLOAD},
  "upload_meta": ${UPLOAD_META}
}
EOF
)

echo "==> Submitting task to ${SERVER_URL}"
curl -sS -X POST "${SERVER_URL}/tasks" \
  -H "Content-Type: application/json" \
  -d "${payload}"
echo ""
