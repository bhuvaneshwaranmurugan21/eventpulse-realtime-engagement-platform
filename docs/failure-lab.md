# Failure lab

| Scenario | Expected observable result |
|---|---|
| Identical duplicate | Count unchanged; duplicate metric increments |
| Same ID, changed payload | Batch rejected as identity conflict |
| Out-of-order within watermark | Aggregate updated once |
| Event older than watermark | Late archive updated; online aggregate unchanged |
| Invalid contract record | Quarantine count and reason recorded |
| Consumer crash before checkpoint | No state or checkpoint becomes visible |
| Restart from checkpoint | Identical checkpoint digest |
| Single hot user | Hottest-partition ratio breaches threshold |
| Shard throttling | Backlog/iterator-age alarm fires; no data loss claim without replay proof |
| Downstream outage | Consumer retries are bounded; quarantine or backlog remains observable |

