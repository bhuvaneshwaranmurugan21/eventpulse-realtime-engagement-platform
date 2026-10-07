# EventPulse Realtime Engagement Platform

[![Semantic oracles](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/workflows/stage3-oracles.yml/badge.svg?branch=main)](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/workflows/stage3-oracles.yml) ![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white) ![AWS design only](https://img.shields.io/badge/AWS-design_only-orange)

EventPulse implements an event-time engagement consumer with deterministic event identity, shard watermarks, sessionization, quarantine and partial-batch retries. Its shared Lambda/Kinesis-shaped handler is locally verified with filesystem and SQLite adapters, reference oracles and process-death/restart tests. AWS adapter request construction is design-tested; managed AWS deployment and service behavior remain unverified.

[Architecture](docs/architecture.md) · [Local verification](part2/stage3/docs/audits/completion.md) · [Known limits](part2/stage3/docs/known-limits.md)
