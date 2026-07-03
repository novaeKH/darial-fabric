#!/usr/bin/env bash
set -euo pipefail

docker compose \
  -f docker-compose.yml \
  -f docker-compose.clickhouse.yml \
  -f docker-compose.kafka.yml \
  -f docker-compose.kafka-consumer.yml \
  -f docker-compose.kafka-outbox.yml \
  -f docker-compose.kafka-bridge.yml \
  -f docker-compose.kafka-dlq.yml \
  -f docker-compose.kafka-health-history.yml \
  down
