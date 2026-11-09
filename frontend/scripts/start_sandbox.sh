#!/usr/bin/env bash
# Start the OpenTelemetry demo (the real microservice system we monitor).
#   ./scripts/start_sandbox.sh          full demo (about 6 GB RAM)
#   ./scripts/start_sandbox.sh minimal  without Kafka (about 3 GB RAM; the queue scenario is unavailable)
set -euo pipefail
DEMO_DIR="${AIOPS_DEMO_DIR:-$HOME/opentelemetry-demo}"
if [ ! -d "$DEMO_DIR" ]; then
  git clone --depth 1 https://github.com/open-telemetry/opentelemetry-demo.git "$DEMO_DIR"
fi
cd "$DEMO_DIR"
if [ "${1:-full}" = "minimal" ]; then
  docker compose -f docker-compose.minimal.yml up --force-recreate --remove-orphans --detach
  echo "Minimal mode: set AIOPS_COMPOSE_FILE=docker-compose.minimal.yml so restarts use the same file."
else
  docker compose up --force-recreate --remove-orphans --detach
fi
echo "Demo folder (AIOPS_DEMO_DIR): $DEMO_DIR"
echo "Shop:          http://localhost:8080/"
echo "Feature flags: http://localhost:8080/feature"
echo "Load gen:      http://localhost:8080/loadgen/"
echo "Prometheus:    http://localhost:9090   (metrics appear after a few minutes)"
