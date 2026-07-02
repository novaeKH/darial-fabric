#!/usr/bin/env bash
set -euo pipefail

docker compose   -f docker-compose.yml   -f docker-compose.clickhouse.yml   -f docker-compose.kafka.yml   up -d
