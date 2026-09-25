# EventPulse architecture authority

**Status:** `DESIGN_ONLY`
**Contract:** `1.0.0`
**Authoritative AWS Region:** `ap-south-2`
**Source checkpoint:** `cac96a23648be8512c5cab58774217169d7e5829` / tree `17bcfb451e52e4cdce7975b09de76e4848a29138`

## Purpose

EventPulse processes user engagement events under duplicate delivery, event-time disorder, poison input, interruption and replay. The authority is the versioned schema, semantic contract, recovery protocol and ADR in this repository. Draft PR #1 remains a historical implementation candidate; it is not the authority and is not merged by this stage.

The thirty-minute allowed-lateness window deliberately matches the thirty-minute inactivity gap. That bound permits a late midpoint event to merge two still-open session components while preserving deterministic closure. Worked boundary sequences are in `contracts/semantic-examples-v1.json`.

## Selected bounded architecture

1. Producers validate schema `1.0.0`, set `partition_key=user_id`, and publish to one provisioned Kinesis shard for the lab.
2. A Python AWS Lambda consumer reads through an event source mapping with parallelization factor 1.
3. The handler validates and canonicalizes each record, then writes immutable raw bytes to S3 with a deterministic key and conditional create.
4. DynamoDB `TransactWriteItems` atomically records the event identity, version-checked session/aggregate state, materialized output and an outbox row when required.
5. A bounded outbox publisher sends quarantine/redrive notifications to SQS. DynamoDB remains the durable quarantine authority; SQS delivery is at least once.
6. CloudWatch records service and custom metrics. A separate failure S3 prefix retains records discarded by the Lambda event source mapping.
7. Replay reads only integrity-verified raw objects into a new `generation_id`; it cannot overwrite the live generation.

## Dependency order

Schema validation precedes archive. Archive precedes the DynamoDB transaction. Transaction success precedes Lambda acknowledgement. Outbox delivery may occur later because the authoritative outbox row is part of the transaction. A failure at any boundary follows `contracts/recovery-protocol-v1.json`.

## State keys

- `EVENT#<event_id>`: first payload digest, classification, expiry and generation.
- `USER#<user_id>#OPEN`: versioned open session components and partition watermark.
- `SESSION#<generation_id>#<session_id>`: immutable closed output.
- `QUARANTINE#<reason>#<event_id>#<payload_digest>`: durable disposition.
- `OUTBOX#<outbox_id>`: notification status and retry metadata.

## Consistency boundary

The S3 archive and DynamoDB transaction are not one atomic operation. Archive is intentionally first. A crash after archive leaves a replayable record and no acknowledged application effect; the retry verifies the same digest and completes the transaction. A crash after the transaction is absorbed by the event identity and state-version conditions. The design claims idempotent application effects only after implementation and managed failure proof. It never claims transport exactly once.

## Draft reconciliation

The draft processor proves useful local ideas but differs from this authority: it uses a batch-global maximum, has no dedupe TTL, throws on identity conflict, stores one compact session tuple, simulates an atomic in-memory checkpoint and defaults Terraform to `ap-south-1`. Future implementation must adapt it to this contract rather than treating those draft choices as final.
