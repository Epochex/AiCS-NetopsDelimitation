# NetOps Project State

- Last updated: 2026-03-31 UTC
- Scope: current repository posture, current mounted runtime facts, and active delivery boundary

## Current Objective

The repository is no longer in the "can raw logs be parsed at all?" phase.
The current objective is to keep the whole chain stable and explainable:

1. FortiGate syslog is turned into structured fact events
2. structured facts move through Kafka into deterministic alerting
3. alerts are persisted into audit and hot-query surfaces
4. bounded AIOps emits suggestions from alert context
5. the runtime console projects the result as an operator-readable chain

The evaluation questions at this stage are practical:

- can the chain stay tied to real runtime artifacts
- can evidence survive from ingest into alert and suggestion products
- can alerts be audited from files and queried from ClickHouse
- can the UI show the runtime path honestly without implying execution already exists

## Current Dataflow

The active repository mainline is:

`FortiGate -> edge/fortigate-ingest -> edge/edge_forwarder -> netops.facts.raw.v1 -> core/correlator -> netops.alerts.v1 -> alerts_sink / alerts_store / aiops_agent -> netops.aiops.suggestions.v1 -> frontend runtime gateway`

The current architectural meaning of each step is:

- `fortigate-ingest`: normalize vendor text into replayable facts
- `edge_forwarder`: decouple edge file handling from shared transport
- `correlator`: keep first-pass detection deterministic
- `alerts_sink`: preserve emitted alerts as audit records
- `alerts_store`: preserve queryable recent history
- `aiops_agent`: assemble evidence and emit bounded suggestions
- `frontend gateway`: project runtime artifacts into a read-only operator surface

## Current Mounted Runtime Facts

The workspace currently exposes `/data/netops-runtime`.
The following facts are directly derived from those mounted artifacts:

| Runtime slice | Observed fact |
| --- | --- |
| Alert sink coverage | `554` hourly files, `152,481` alert records |
| Alert sink range | `2026-03-04T15:09:11+00:00` to `2026-03-27T23:00:17+00:00` |
| Suggestion sink coverage | `480` hourly files |
| Suggestion sink range | `2026-03-09T05:08:56.549849+00:00` to `2026-03-31T15:36:55.895982+00:00` |
| Latest 6 alert partitions | `504` alerts from `2026-03-27T18:00:14+00:00` to `2026-03-27T23:00:17+00:00` |
| Latest 6 suggestion partitions | `3,703` suggestions from `2026-03-31T10:00:16.165096+00:00` to `2026-03-31T15:36:55.895982+00:00` |
| Last 24 alert partitions | `warning=2067`, `critical=2`; `deny_burst_v1=2067`, `bytes_spike_v1=2` |
| Last 24 suggestion partitions | `alert=9058`, `cluster=1353`; provider `template=10411` |

Important honesty note:

- the current workspace does not expose a live `/data/fortigate-runtime` volume
- the mounted suggestion sink is newer than the mounted alert sink
- the newest suggestion batches still mostly reference March 26 alert context

This means the repository clearly demonstrates alert and suggestion products, but this mounted workspace should not be described as a perfectly synchronized live snapshot across every runtime layer.

## What Is Already Landed

- replay-aware FortiGate ingest
- edge forwarding into Kafka raw topic
- deterministic alerting on `netops.alerts.v1`
- alert JSONL audit persistence
- ClickHouse-backed hot alert storage
- bounded AIOps suggestion path with `alert` and `cluster` scopes
- read-only runtime gateway and operator console

## What Is Explicitly Outside The Current Delivered Path

- device write-back
- approval workflows that mutate live state
- production-grade closed-loop remediation
- model-driven first-pass detection on the full raw stream
- any claim that the current frontend is already an execution console

## Active Constraints

- inference cannot be treated as a free hot-path dependency
- replay and audit still matter more than narrative polish
- the frontend is a projection layer over runtime artifacts, not a control plane
- JSONL and ClickHouse are both kept because audit and hot retrieval are different jobs

## Related Documents

- [Edge runtime guide](./EDGE_RUNTIME_GUIDE.md)
- [Core runtime guide](./CORE_RUNTIME_GUIDE.md)
- [Frontend workspace guide](./FRONTEND_WORKSPACE_GUIDE.md)
- [FortiGate ingest field reference](./FORTIGATE_INGEST_FIELD_REFERENCE_EN.md)
- [Frontend runtime architecture](./FRONTEND_RUNTIME_ARCHITECTURE_20260328_EN.md)
- [Controlled validation log](./CONTROLLED_VALIDATION_20260322.md)
