#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
[[ -f "$PROJECT_DIR/.env" ]] && source "$PROJECT_DIR/.env"

: "${RUNPOD_API_KEY:?Set RUNPOD_API_KEY in .env or environment}"
API="https://api.runpod.io/graphql?api_key=${RUNPOD_API_KEY}"

BUILD_NUM="${1:-$(date +%Y%m%d%H%M)}"
FULL_TAG="${IMAGE_TAG}-${BUILD_NUM}"
FULL_IMAGE="${IMAGE_BASE}:${FULL_TAG}"

_gql() {
  curl -sS "$API" -H "Content-Type: application/json" -d "$1" | jq .
}

echo "==> Building ${FULL_IMAGE} on Cloud Shell..."
gcloud cloud-shell ssh --command "cd workspace/worker-${ENDPOINT_NAME} && \
  git pull && \
  docker buildx build --push --platform linux/amd64 -t ${FULL_IMAGE} ."

echo ""
echo "==> Updating template ${TEMPLATE_ID} image to ${FULL_IMAGE}..."
_gql "$(jq -n --arg id "$TEMPLATE_ID" --arg img "$FULL_IMAGE" --arg templateId "$TEMPLATE_ID" '{
  query: "mutation SaveTemplate($input: SaveTemplateInput!) { saveTemplate(input: $input) { id imageName } }",
  variables: {
    input: {
      id: $id,
      imageName: $img,
      name: $templateId,
      containerDiskInGb: 75,
      volumeInGb: 0,
      dockerArgs: "",
      isServerless: true,
      startJupyter: false,
      startSsh: true,
      env: [
        {key: "HUGGINGFACE_TOKEN", value: "{{ RUNPOD_SECRET_HF_TOKEN }}"},
        {key: "HF_TOKEN", value: "{{ RUNPOD_SECRET_HF_TOKEN }}"},
      ]
    }
  }
}')"

echo ""
echo "==> Terminating all workers..."
POD_IDS=$(curl -sS "$API" -H "Content-Type: application/json" \
  -d "{\"query\":\"{ myself { endpoints { pods { id } } } }\"}" \
  | jq -r '.data.myself.endpoints[0].pods[].id // empty')
if [[ -z "$POD_IDS" ]]; then
  echo "   No workers running"
else
  for pod_id in $POD_IDS; do
    echo "   Terminating $pod_id..."
    _gql "$(jq -n --arg pid "$pod_id" '{
      query: "mutation { podTerminate(input: {podId: \"\($pid)\"}) }"
    }')"
  done
fi

echo ""
echo "==> Purging queue..."
"$SCRIPT_DIR/rp" purge

sleep 5

echo ""
echo "==> Sending test requests..."
"$SCRIPT_DIR/queue.sh"

echo ""
echo "==> Deploy complete: ${FULL_IMAGE}"
