#!/usr/bin/env bash
# Create the streaming topics once. Safe to re-run.
set -euo pipefail

BROKERS="-X brokers=redpanda:9092"
RETENTION_MS=$((24 * 60 * 60 * 1000))  # 24 hours: a restarted consumer can replay a full day

for topic in gps.pings vehicle.telemetry; do
  if rpk topic describe "$topic" $BROKERS >/dev/null 2>&1; then
    echo "topic $topic already exists"
  else
    rpk topic create "$topic" $BROKERS --partitions 3 --replicas 1 \
      --topic-config retention.ms=$RETENTION_MS \
      --topic-config cleanup.policy=delete
  fi
done

rpk topic list $BROKERS
