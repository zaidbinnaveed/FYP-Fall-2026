#!/usr/bin/env bash
# Phase D0 acceptance: every service in the dev stack is running and healthy, and the HTTP
# probes answer. Run after `docker compose ... up --wait`.
set -euo pipefail

COMPOSE=(docker compose -f "$(dirname "$0")/../docker-compose.dev.yml")
EXPECTED=(db storage mailpit api worker inference frontend)
failed=0

for service in "${EXPECTED[@]}"; do
  cid=$("${COMPOSE[@]}" ps -q "$service")
  if [[ -z "$cid" ]]; then
    echo "FAIL $service: no container"
    failed=1
    continue
  fi
  state=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$cid")
  if [[ "$state" == "running/healthy" ]]; then
    echo "OK   $service: $state"
  else
    echo "FAIL $service: $state"
    failed=1
  fi
done

probe() {
  local name=$1 url=$2
  if body=$(curl -fsS --max-time 5 "$url"); then
    echo "OK   $name $url -> $body"
  else
    echo "FAIL $name $url"
    failed=1
  fi
}

probe api http://127.0.0.1:8000/healthz
probe api http://127.0.0.1:8000/readyz
probe storage http://127.0.0.1:8333/healthz
probe frontend http://127.0.0.1:5173/
# The inference service is internal-only (no host port); probe it inside the network.
if "${COMPOSE[@]}" exec -T inference python -c \
  "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8001/readyz',timeout=3).read().decode())"; then
  echo "OK   inference /readyz (in-network)"
else
  echo "FAIL inference /readyz"
  failed=1
fi

# Error envelope reaches the outside world unchanged.
envelope=$(curl -sS --max-time 5 http://127.0.0.1:8000/api/v1/does-not-exist)
if echo "$envelope" | python3 -c 'import json,sys; b=json.load(sys.stdin); assert set(b)=={"error_code","message","details","request_id"} and b["error_code"]=="NOT_FOUND"'; then
  echo "OK   api error envelope -> $envelope"
else
  echo "FAIL api error envelope -> $envelope"
  failed=1
fi

exit "$failed"
