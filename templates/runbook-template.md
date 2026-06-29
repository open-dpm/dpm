# Runbook: {namespace}/{entity}

**Manifest version:** {version}
**Runbook version:** 1.0
**Last updated:** {YYYY-MM-DD}
**Status:** Active

---

## Table of Contents

1. [Overview](#1-overview)
2. [Contacts and Escalation](#2-contacts-and-escalation)
3. [Infrastructure Overview](#3-infrastructure-overview)
4. [Common Incidents](#4-common-incidents)
5. [Data Validation Errors](#5-data-validation-errors)
6. [Schema Evolution Procedures](#6-schema-evolution-procedures)
7. [Rollback Procedures](#7-rollback-procedures)
8. [Kafka Operations](#8-kafka-operations)
9. [DLQ Handling](#9-dlq-handling)
10. [Monitoring and Dashboards](#10-monitoring-and-dashboards)
11. [Maintenance Procedures](#11-maintenance-procedures)
12. [Incident History](#12-incident-history)

---

## 1. Overview

### 1.1 Manifest Summary

| Attribute | Value |
|---------|----------|
| **Manifest** | {namespace}/{entity} |
| **Version** | {version} |
| **Owner** | {owner-team} |
| **Criticality** | {High / Medium / Low} |
| **Source system** | {source-system} |
| **Extraction method** | {CDC / Batch / API} |

### 1.2 Data Description

{A short description of what this data represents and its business purpose.}

**Primary use cases:**
- {Scenario 1}
- {Scenario 2}
- {Scenario 3}

### 1.3 SLA Summary

| Metric | Target | Critical threshold |
|---------|------------------|-------------------|
| **Availability** | {99.9%} | Below {99.5%} |
| **Freshness** | {< 1 hour} | {> 2 hours} |
| **DLQ rate** | {< 0.1%} | {> 1%} |
| **Response time (P1)** | {15 min} | - |
| **Recovery time** | {2 hours} | {4 hours} |

---

## 2. Contacts and Escalation

### 2.1 Contact Directory

| Role | Team | Channel | Email | On-call |
|------|---------|-------|-------|-----------|
| **Data owner** | {owner-team} | #{owner-channel} | {owner-email} | {pagerduty-link} |
| **L2 escalation** | data-platform | #data-platform-oncall | data-platform@example.com | - |
| **L3 escalation** | engineering-leads | #engineering-leads | eng-leads@example.com | - |
| **Source system** | {source-team} | #{source-channel} | {source-email} | - |

### 2.2 Escalation Matrix

| Time | Severity | Action |
|-------|----------|----------|
| **0-15 min** | All | On-call acknowledges, begins diagnostics |
| **15-30 min** | P1/P2 | If unresolved, escalate to team lead |
| **30-60 min** | P1 | Escalate to L2 (data-platform), start incident bridge |
| **1-2 hours** | P1 | Escalate to L3, notify downstream consumers |
| **2+ hours** | P1 | Notify leadership, communicate with customers |

### 2.3 Escalation Procedure

1. **Acknowledge the alert** within 5 minutes
2. **Begin diagnostics** using the procedures in this runbook
3. **Update status** in the #data-incidents channel every 15 minutes
4. **Escalate** per the matrix if resolution time exceeds the threshold
5. **Communicate** with affected consumers if an SLA breach is likely
6. **Document** the resolution in the incident history

---

## 3. Infrastructure Overview

### 3.1 Architecture Diagram

```
+-------------------+     +-------------------+     +-------------------+
|   {Source}        | --> |   API Gateway     | --> |   Kafka           |
|   {source-system} |     |   (mTLS + Avro)   |     |   {namespace}.    |
+-------------------+     +-------------------+     |   {entity}.raw    |
                                                    +-------------------+
                                                            |
                                                            v
+-------------------+     +-------------------+     +-------------------+
|   Data Lake       | <-- |   Consumers       | <-- |   Quality         |
|   {namespace}.    |     |   {list}          |     |   Validator       |
|   {entity}        |     +-------------------+     +-------------------+
+-------------------+                                       |
                                                            v
                                                    +-------------------+
                                                    |   DLQ             |
                                                    |   {namespace}.    |
                                                    |   {entity}_dlq    |
                                                    +-------------------+
```

### 3.2 Kafka Topics

| Topic | Purpose | Partitions | Retention | Consumer Groups |
|-------|------------|----------|-----------|-----------------|
| `{namespace}.{entity}.raw` | Raw data from the source | {N} | {7 days} | quality-validator |
| `{namespace}.{entity}_prod` | Validated data | {N} | {30 days} | {consumer-groups} |
| `{namespace}.{entity}_dlq` | Validation errors | {N} | {90 days} | dlq-processor |

### 3.3 Key Endpoints

| Component | Endpoint | Health Check |
|-----------|----------|--------------|
| API Gateway | `https://data-gateway.example.com/{namespace}/{entity}` | `/health` |
| Quality Validator | `http://quality-validator:8080` | `/health` |
| Grafana Dashboard | `https://grafana.example.com/d/{dashboard-id}` | - |

---

## 4. Common Incidents

### 4.1 No Data

**Symptoms:**
- Alert: "No messages in {namespace}.{entity}.raw for {threshold} minutes"
- Grafana: the `kafka_messages_in_total{topic="{namespace}.{entity}.raw"}` metric is not growing
- Consumers report stale data

**Diagnostics:**

```bash
# 1. Check the timestamp of the last message
kafkacat -b kafka:9092 -t {namespace}.{entity}.raw -C -c 1 -o -1 -f '%T\n'

# 2. Check topic health
kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic {namespace}.{entity}.raw

# 3. Check API Gateway logs
kubectl logs -l app=api-gateway --tail=100 | grep "{namespace}.{entity}"

# 4. Check connectivity to the source system
curl -v --cert /certs/{namespace}.{entity}.crt \
     --key /certs/{namespace}.{entity}.key \
     https://data-gateway:443/{namespace}/{entity}/health
```

**Common causes and resolutions:**

| Cause | Diagnostics | Resolution |
|---------|-------------|---------|
| Source system unavailable | API Gateway 5xx errors | Contact the source team |
| Expired mTLS certificate | SSL handshake errors | Rotate the certificate (Section 11.3) |
| Network connectivity | Connection timeout | Check firewall, DNS |
| Kafka broker issue | Under-replicated partitions | Contact the platform team |

---

### 4.2 High Error Rate / DLQ Growth

**Symptoms:**
- Alert: "DLQ > {threshold} for {namespace}.{entity}"
- Grafana: the `dlq_messages_total{topic="{namespace}.{entity}_dlq"}` metric is growing
- Elevated error rate

**Diagnostics:**

```bash
# 1. Check DLQ size
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -e -q | wc -l

# 2. Sample recent DLQ messages - analyze error types
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -c 10 -o end | \
  jq -r '.validation_errors[].rule_name' | sort | uniq -c | sort -rn

# 3. View a full DLQ record with errors
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -c 1 -o end | jq '.'
```

**Common causes and resolutions:**

| Error pattern | Likely cause | Resolution |
|----------------|-------------------|---------|
| `{field}_not_null` | Source sends null | Fix the source or the rule |
| `{field}_format` | Data format changed | Update the schema or the rule |
| `{field}_enum` | New value in the source | Add the enum value |
| `freshness` | Processing delay | Check validator lag |

---

### 4.3 High Latency / Consumer Lag

**Symptoms:**
- Alert: "Consumer lag > {threshold} for {consumer-group}"
- Risk of a freshness SLA breach
- Consumers report data delay

**Diagnostics:**

```bash
# 1. Check consumer lag
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --describe --group quality-validator | grep {namespace}.{entity}

# 2. Check validator processing rate
curl -s http://quality-validator:8080/metrics | \
  grep "messages_processed.*{namespace}_{entity}"

# 3. Check validator resource usage
kubectl top pods -l app=quality-validator
```

---

## 5. Data Validation Errors

### 5.1 Validation Results

| Result | Destination | Action |
|-----------|------------|----------|
| **Pass** | `{namespace}.{entity}_prod` | Data goes to consumers |
| **Warning** | `{namespace}.{entity}_prod` + log | Data goes through, issue is logged |
| **Error** | `{namespace}.{entity}_dlq` | Data quarantined, alert |

### 5.2 Validation Rules Reference

| Rule | Severity | Description | Typical fix |
|---------|----------|----------|---------------------|
| `{id}_not_null` | error | Primary key cannot be null | Fix the source data |
| `{field}_format` | error/warning | Field format validation | Update the format or the rule |
| `{field}_range` | error | Numeric range check | Fix the source or the range |
| `{field}_enum` | error | Allowed values check | Add the value or fix the source |

---

## 6. Schema Evolution Procedures

### 6.1 Non-breaking Changes (MINOR version)

**Allowed changes:**
- Adding a nullable field
- Adding a field with a default value
- Adding a new enum value
- Updating field documentation

**Procedure:**

```bash
# 1. Update schema.avsc with the new field
# 2. Bump the version in manifest.yaml (MINOR bump)
# 3. Update the changelog in manifest.yaml
# 4. Validate the changes
dpm validate examples/{namespace}/{entity}/
dpm breaking-changes examples/{namespace}/{entity}/

# 5. Create an MR, get approval
# 6. Merge and deploy
```

### 6.2 Breaking Changes (MAJOR version)

**Breaking changes require:**
- Publishing the new version alongside the current one (do not edit it in place)
- Notifying consumers: those declared in the contract, plus the rest tracked by your access/policy layer
- An agreed migration/grace period (set per contract — no fixed minimum)
- Following the deprecation process until all consumers have migrated, then retiring the old version

---

## 7. Rollback Procedures

### 7.1 Manifest Rollback

```bash
# 1. Identify the last working commit
git log --oneline examples/{namespace}/{entity}/

# 2. Revert to the previous version
git revert {commit-hash}

# 3. Create an emergency MR with the [EMERGENCY] prefix
git push origin emergency/{namespace}-{entity}-rollback

# 4. Express approval (one approval from on-call)
# 5. Deploy the rolled-back manifest
# 6. Verify data flow recovery
```

### 7.2 Data Rollback (Iceberg Time Travel)

```sql
-- 1. List available snapshots
SELECT * FROM {namespace}.{entity}.snapshots ORDER BY committed_at DESC LIMIT 10;

-- 2. View data at a previous snapshot
SELECT * FROM {namespace}.{entity} FOR VERSION AS OF {snapshot_id} LIMIT 10;

-- 3. Roll back to a snapshot (WARNING: destructive operation)
CALL system.rollback_to_snapshot('{namespace}.{entity}', {snapshot_id});
```

---

## 8. Kafka Operations

### 8.1 Consumer Lag Management

```bash
# Total lag
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --describe --group {consumer-group}

# Detailed lag per partition
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --describe --group {consumer-group} --verbose
```

### 8.2 Offset Reset

```bash
# 1. Stop the consumers in the group
kubectl scale deployment {consumer-deployment} --replicas=0

# 2. Reset the offset to a timestamp
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group {consumer-group} \
  --topic {namespace}.{entity}_prod \
  --reset-offsets --to-datetime 2026-01-15T00:00:00.000 \
  --execute

# 3. Restart the consumers
kubectl scale deployment {consumer-deployment} --replicas={N}
```

---

## 9. DLQ Handling

### 9.1 DLQ Structure

```json
{
  "original_record": { ... },
  "validation_errors": [
    {
      "rule_name": "amount_positive",
      "field": "amount",
      "value": -100,
      "message": "Amount must be non-negative"
    }
  ],
  "failed_at": "2026-01-15T10:30:00Z",
  "source_topic": "{namespace}.{entity}.raw",
  "source_partition": 0,
  "source_offset": 12345
}
```

### 9.2 DLQ Analysis

```bash
# Number of records in the DLQ
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -e -q | wc -l

# Group errors by rule
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -e | \
  jq -r '.validation_errors[].rule_name' | sort | uniq -c | sort -rn
```

### 9.3 DLQ Reprocessing

**Option 1: Reprocess after fixing a rule**

```bash
# After fixing quality_rules.yml and deploying:
python scripts/dlq_reprocess.py \
  --topic {namespace}.{entity}_dlq \
  --target {namespace}.{entity}.raw \
  --batch-size 1000
```

**Option 2: Manual fix and replay**

```bash
# 1. Export DLQ records
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -e > to_fix.json

# 2. Fix the records
python scripts/fix_records.py to_fix.json fixed.json

# 3. Replay the fixed records
kafkacat -b kafka:9092 -t {namespace}.{entity}.raw -P < fixed.json
```

---

## 10. Monitoring and Dashboards

### 10.1 Grafana Dashboards

| Dashboard | URL | Purpose |
|---------|-----|------------|
| Manifests overview | `https://grafana.example.com/d/{manifest-overview-id}` | Summary of all manifests |
| {namespace}/{entity} | `https://grafana.example.com/d/{entity-dashboard-id}` | Detailed manifest metrics |
| Kafka Cluster | `https://grafana.example.com/d/{kafka-dashboard-id}` | Kafka health |
| Quality Validator | `https://grafana.example.com/d/{validator-dashboard-id}` | Validator metrics |

### 10.2 Key Metrics

| Metric | PromQL | Alert threshold |
|---------|--------|--------------|
| Message rate | `rate(kafka_messages_in_total{topic="{namespace}.{entity}.raw"}[5m])` | < 1 per 10m |
| DLQ rate | `rate(dlq_messages_total{topic="{namespace}.{entity}_dlq"}[5m])` | > 1% of input |
| Consumer Lag | `kafka_consumer_lag{group="{consumer-group}"}` | > 10000 |
| Validation latency | `histogram_quantile(0.99, validation_duration_seconds{...})` | > 1s |

---

## 11. Maintenance Procedures

### 11.1 Daily Checks

- [ ] Check data freshness against the SLA
- [ ] Check DLQ size (should be < 100)
- [ ] Review overnight alerts
- [ ] Confirm consumer lag is stable

### 11.2 Weekly Checks

- [ ] Analyze DLQ error patterns for trends
- [ ] Check storage growth
- [ ] Check backup status
- [ ] Review and acknowledge warnings

### 11.3 Certificate Rotation

```bash
# Check expiry
openssl x509 -in /certs/{namespace}.{entity}.crt -noout -dates
```

### 11.4 Iceberg Table Maintenance

```sql
-- Expire old snapshots (run weekly)
CALL system.expire_snapshots('{namespace}.{entity}', TIMESTAMP '2026-01-01 00:00:00', 10);

-- Remove orphan files (weekly)
CALL system.remove_orphan_files('{namespace}.{entity}');

-- Compact small files (daily as needed)
CALL system.rewrite_data_files('{namespace}.{entity}');
```

---

## 12. Incident History

| Date | Incident | Root cause | Resolution | Duration | Postmortem |
|------|----------|------------------|---------|--------------|------------|
| {YYYY-MM-DD} | {Short description} | {Cause} | {How it was resolved} | {Time} | {Link} |

---

## Appendix: Command Reference

```bash
# === Topic operations ===
# List topics
kafka-topics.sh --bootstrap-server kafka:9092 --list | grep {namespace}

# Describe a topic
kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic {namespace}.{entity}.raw

# === Consumer operations ===
# List consumer groups
kafka-consumer-groups.sh --bootstrap-server kafka:9092 --list

# Describe a consumer group
kafka-consumer-groups.sh --bootstrap-server kafka:9092 --describe --group {consumer-group}

# === Message operations ===
# Read the last message
kafkacat -b kafka:9092 -t {namespace}.{entity}_prod -C -c 1 -o -1

# Count messages
kafkacat -b kafka:9092 -t {namespace}.{entity}_dlq -C -e -q | wc -l
```

---

*Last updated: {YYYY-MM-DD}*
*Maintained by: {owner-team}*
*Questions: #{owner-channel} or {owner-email}*
