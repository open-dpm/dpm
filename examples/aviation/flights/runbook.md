# Runbook: aviation/flights

## Overview

Aircraft flight data from the OpenSky Network API.

## Components

| Component | Description |
|-----------|-------------|
| Producer | `flights_producer.py` — fetches data from the OpenSky API |
| Raw Topic | `aviation.flights.raw` |
| Prod Topic | `aviation.flights_prod` |
| DLQ Topic | `aviation.flights_dlq` |

## Monitoring

### Dashboard

URL: ${DASHBOARD_URL}/d/flights-pipeline

### Key metrics

- `dpm_messages_processed_total{topic="aviation.flights.raw"}` — incoming messages
- `dpm_messages_processed_total{topic="aviation.flights_prod"}` — valid messages
- `dpm_messages_processed_total{topic="aviation.flights_dlq"}` — rejected messages
- `dpm_dlq_rate` — DLQ percentage

## Troubleshooting

### No data in the prod topic

1. Check the producer status:
   ```bash
   docker logs flights-producer
   ```

2. Check the API gateway:
   ```bash
   curl http://localhost:8080/health
   ```

3. Check the quality validator:
   ```bash
   systemctl status quality-validator
   journalctl -u quality-validator -f
   ```

### High DLQ rate

1. Inspect validation errors:
   ```bash
   /opt/kafka/current/bin/kafka-console-consumer.sh \
     --bootstrap-server localhost:9092 \
     --topic aviation.flights_dlq \
     --from-beginning --max-messages 10
   ```

2. Common causes:
   - Stale data (timestamp older than 5 minutes)
   - Malformed ICAO24 value
   - Coordinates out of range

### OpenSky API unavailable

1. Check the API status:
   ```bash
   curl https://opensky-network.org/api/states/all
   ```

2. While it is down, the producer retries with exponential backoff.

## Contacts

- **Team**: data-platform
- **Slack**: #data-platform
- **Email**: data-platform@example.com
