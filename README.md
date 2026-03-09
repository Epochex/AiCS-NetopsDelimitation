## Towards NetOps: Hybrid AIOps Platform for Network Awareness and Automated Remediation
[![English](https://img.shields.io/badge/Language-English-1f6feb)](./README.md) [![简体中文](https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-2ea043)](./README_CN.md)

> Hybrid AIOps Platform: Deterministic Streaming Core + CPU Local LLM (On-Demand) + Multi-Agent Orchestration

#### Project Overview

This project aims to build a **distributed AIOps platform (Towards NetOps)** for complex network operations scenarios, following the main line of **Edge Fact Ingestion → Core Streaming Analytics → LLM-Augmented Reasoning → Remediation Loop**, and progressively implementing an engineering capability evolution from anomaly detection and evidence-chain attribution to remediation recommendation and execution control. The platform does not target “real-time LLM inference on full-volume logs”; instead, it is built on a stable data plane and explainable evidence flow, and performs on-demand intelligent augmented analysis for high-value anomaly clusters on the core side, in order to achieve a deployable balance among cost, real-time performance, and operability.

#### Architecture Paradigm

The system adopts a layered architecture of **Edge Ingestion + Core Analytics**. The edge side is responsible for near-source log collection, structured fact eventization, audit trail retention, and replayable persistence, converting raw device logs into a sustainably consumable fact event stream; the core side is responsible for streaming data plane hosting, event aggregation and correlation analysis, and evidence-chain construction, and on this basis introduces an **LLM-augmented analytics layer** for alert explanation, situation summarization, attribution assistance, and Runbook draft generation. This augmentation layer adopts a **resident service + rate-limited queue** operating mode: rule-based/streaming modules perform real-time detection and high-value anomaly filtering, while the LLM performs low-concurrency, on-demand inference only on alert-level context, avoiding contention with the real-time performance and system resources of the main path.

> [!IMPORTANT]
> The platform target is not “real-time LLM inference on full-volume logs,” but on-demand intelligent augmented analysis of high-value anomaly clusters based on a stable data plane and explainable evidence flow.

- Current Technical Route Under Resource Constraints

Under current resource constraints (no GPU on the core side, CPU-only inference), the technical route of this project is explicitly **“deterministic streaming analytics as the primary path + on-demand LLM augmentation”**: real-time detection, basic aggregation, and correlation computation are handled by rule-based/stream processing modules; the LLM is responsible for explanation and planning generation over compressed high-value evidence context. This design enables the platform, without relying on local training or continuous high-cost API calls, to still progressively evolve toward Multiple Agent + LLM collaborative analysis and automated remediation closed-loop capability.

> [!NOTE]
> At the current stage, the priorities are: stable data plane, explainable evidence flow, and runnable core pipeline; the LLM is connected on demand as an alert-level augmentation module.

The project construction sequence is expected to proceed in the following stages:

1. **Phase 1: Engineering implementation of the edge fact ingestion layer**  
   Complete ingestion of FortiGate logs (and potentially additional network device logs in the future), ensuring the input is auditable, recoverable, and replayable.

2. **Phase 2: Core-side data plane and minimal streaming consumption pipeline**  
   Establish the data plane on the core side, and complete event transport decoupling and basic aggregation analytics.

3. **Phase 3: Introduction of AIOps augmented analytics capabilities**  
   Based on AIOps principles, progressively introduce Multiple Agent + LLM capabilities for correlation analysis, network situational awareness, evidence-chain attribution, and automated self-healing Runbook generation.

4. **Phase 4: Remediation loop extension**  
   Under explainability and verifiability constraints, extend to remediation recommendations, human approval execution, and low-perception automated self-healing.

## Design Boundary

> [!WARNING]
> At the current stage, this project does not take “per-event LLM judgment over the full event stream” as an architectural target.  
> The main path is handled by deterministic streaming modules for real-time detection and basic correlation; LLM/Agent components are used for on-demand augmented analysis of high-value alert clusters and remediation recommendation generation.

## Current Progress Snapshot (2026-03-08)

> [!TIP]
> Runtime ownership is now explicit: `edge/*` only for edge node components, `core/*` only for core node components.

### Implemented Runtime Flow

```mermaid
flowchart LR
  A[edge/fortigate-ingest] --> B[edge/edge_forwarder]
  B --> C[Kafka: netops.facts.raw.v1]
  C --> D[core/correlator<br/>quality_gate + rules]
  D --> E[Kafka: netops.alerts.v1]
  E --> F[core/alerts_sink<br/>hourly JSONL]
  E --> G[core/alerts_store<br/>ClickHouse]
  E --> H[core/aiops_agent]
  H --> I[Kafka: netops.aiops.suggestions.v1]
```

### Implemented Modules and Stack

| Layer | Module | Responsibility | Tech |
| --- | --- | --- | --- |
| Edge ingest | `edge/fortigate-ingest` | Parse FortiGate logs, checkpoint replay, DLQ/metrics output | Python, JSONL |
| Edge filter/forward | `edge/edge_forwarder` | Noise suppression + forward to core topic | Python, Kafka |
| Core correlator | `core/correlator` | Quality gate, rule matching, alert emit, manual offset commit | Python, Kafka |
| Alert persistence | `core/alerts_sink` | Persist alerts to hourly JSONL | Python |
| Hot analytics store | `core/alerts_store` | Consume alerts and store structured records | ClickHouse, `clickhouse-connect` |
| AIOps assistant (minimal) | `core/aiops_agent` | Build suggestion payloads for high-value alerts | Python, Kafka |
| Ops tooling | `core/benchmark/*` | Runtime watch and warning-noise observation | Python, `kubectl` |

### AIOps Agent Module Diagram

```mermaid
flowchart TD
  M[core.aiops_agent.main] --> C[app_config]
  M --> IO[runtime_io]
  M --> SVC[service]
  SVC --> CL[cluster_aggregator]
  SVC --> CTX[context_lookup]
  SVC --> ENG[suggestion_engine]
  SVC --> OUT[output_sink]
```

- `app_config`: normalize env config and enforce severity gate policy.
- `runtime_io`: initialize Kafka/ClickHouse clients in one place.
- `cluster_aggregator`: aggregate alerts by `rule_id + severity + service + src_device_key` in a sliding window.
- `service`: consume alerts, trigger cluster suggestions, and commit offsets only on successful handling.
- `context_lookup`: query recent-similar counts from ClickHouse for context enrichment.
- `suggestion_engine`: generate stable suggestion payload schema.
- `output_sink`: persist hourly JSONL evidence for audit/replay.

### Reliability Hardening Already Applied

- Release script now avoids updating edge runtime image during core-only releases.
- Post-release validation was added to verify module importability in running pods (to catch image/content mismatch early).
- Core consumers moved to `enable_auto_commit=False` and commit offsets after successful processing.
- Rule thresholds are profile-based (`core/correlator/rule_profile.py`) for environment-specific tuning.

### Baseline Verification (before merge/release)

```bash
python3 -m pytest -q tests/core
python3 -m compileall -q core
bash -n core/automatic_scripts/release_core_app.sh
```

> [!NOTE]
> `tests/core` now covers `rules`, `quality_gate`, `alerts_sink`, `alerts_store`, and `aiops_agent` (including cluster aggregation) minimal behavior.
> Current baseline is suitable for iterative AIOps feature development on top of the existing core pipeline.

## 1.1 Project Positioning and Current Architecture Boundary
The current project architecture is centered around **r230 (edge collection) → r450 (core data plane and analytics processing)**, i.e., near-source collection and factization on the edge side, and subsequent streaming processing, correlation analysis, evidence-chain attribution, and automated remediation capability implementation on the core side. This means the project has completed the most critical input-plane landing work in platform construction and has entered the architecture advancement stage oriented toward core capability expansion.

The project is currently at the stage where the **Edge Fact Ingestion Layer has been deployed and is running stably**, while the **Core Analytics / Causality / Remediation layer is under continuous development**. The system runs on a **k3s** cluster; the `fortigate-ingest` component on the `edge` side has been containerized, deployed, and is continuously running, undertaking edge-side ingestion and factization of FortiGate logs. The current node role split is: **netops-node2 (r230) for edge ingestion**, and **netops-node1 (r450) as the hosting node for the core data plane and analytics side**. The platform has entered the cluster runtime stage for foundational AIOps components.

> [!IMPORTANT]
> The current architecture focus is to extend toward the core-side data plane and analytics capabilities based on the already-running edge ingestion component.

Node role allocation is as follows:
- **netops-node2 (r230)**: Edge ingestion side (Edge Ingestion; Ingest Pod development and deployment completed, running stably)
- **netops-node1 (r450)**: Core side (Data Plane / Core Analytics; under continuous development)

## 1.2 Currently Implemented Components (Edge / FortiGate Ingestion)
`edge/fortigate-ingest` has been containerized, deployed, and is continuously running in the k3s cluster, and currently performs the following responsibilities:

- Ingest FortiGate syslog inputs (active log + rotated logs, including `.gz`)
- Process historical backfill and near-real-time tailing in a fixed order (`rotated → active`)
- Parse syslog header and FortiGate `key=value` payload
- Perform field type normalization and structured event generation
- Output directly consumable fact event streams (JSONL)
- Output DLQ and ingest metrics (for bad-sample isolation and runtime observability)
- Persist checkpoints (including `inode/offset` and `completed` dedup ledger), supporting restart recovery, rotation handling, and traceable replay localization

The edge side has already formed a stable **fact event production pipeline** based on the overall router environment, providing unified input for subsequent core-side streaming consumption, correlation analysis, and root-cause reasoning.

---
## 2. Edge Components
### 2.1 Ingest Component
> ## FortiGate Log Input / Ingest / Parsed Output Specification  
> Raw log (`/data/fortigate-runtime/input/fortigate.log`) format analysis  
> FortiGate log input format, structured event output format (JSONL), field semantics, and ingest processing pipeline, for data ingestion, analytics development, troubleshooting audit, and downstream streaming integration.

### 2.1.1 Raw FortiGate Log Format (Input)
The input of `edge/fortigate-ingest` is not a single file, but **a set of FortiGate log files in the same directory**: the continuously appended active file `fortigate.log`, plus historical files generated by an external rotation mechanism, `fortigate.log-YYYYMMDD-HHMMSS` and `fortigate.log-YYYYMMDD-HHMMSS.gz`. On startup and in the main loop, ingest first scans and processes all rotated files matching the naming rule in filename timestamp order (for historical log backfill), and then performs incremental tailing on `fortigate.log` using `active.inode + active.offset` recorded in the checkpoint (for near-real-time ingestion of new logs). Rotated files are read as whole files (`.gz` is read line by line after gzip decompression with `source.offset=null`; non-`.gz` rotated files record per-line offsets), while the active file is continuously tailed by byte offset; during runtime, the main loop periodically rescans the rotated list and uses the `completed(path|inode|size|mtime)` dedup ledger to avoid duplicate backfill, while handling active-file rotation switch and truncation recovery through `inode` changes and file size/offset state. The responsibility boundary of this processing model is: **ingest identifies and consumes the active/rotated input set, while an external component is responsible for generating rotated log files**.

- **Active log**
  - `/data/fortigate-runtime/input/fortigate.log`
- **Rotated logs**
  - `/data/fortigate-runtime/input/fortigate.log-YYYYMMDD-HHMMSS`
  - `/data/fortigate-runtime/input/fortigate.log-YYYYMMDD-HHMMSS.gz`

### Line Format

Each log line consists of two parts:  
*Input sample (raw)*: demonstrates that the raw log contains directly extractable network semantics + asset profiling semantics (interface, policy, action, device vendor/type/OS/MAC)

1. **Syslog header** - 4-token dimension
2. **FortiGate key-value payload** - 43-token dimension

### Input raw log field list (43 FortiGate KV fields + 4 syslog header subfields)

**Example (real sample):**
```text
Feb 21 15:45:27 _gateway date=2026-02-21 time=15:45:26 devname="DAHUA_FORTIGATE" devid="FG100ETK20014183" logid="0001000014" type="traffic" subtype="local" level="notice" vd="root" eventtime=1771685127249713472 tz="+0100" srcip=192.168.16.41 srcname="es-73847E56DA65" srcport=48689 srcintf="LACP" srcintfrole="lan" dstip=255.255.255.255 dstport=48689 dstintf="unknown0" dstintfrole="undefined" sessionid=1211202700 proto=17 action="deny" policyid=0 policytype="local-in-policy" service="udp/48689" dstcountry="Reserved" srccountry="Reserved" trandisp="noop" app="udp/48689" duration=0 sentbyte=0 rcvdbyte=0 sentpkt=0 appcat="unscanned" srchwvendor="Samsung" devtype="Phone" srcfamily="Galaxy" osname="Android" srcswversion="16" mastersrcmac="78:66:9d:a3:4f:51" srcmac="78:66:9d:a3:4f:51" srcserver=0
```
Input field analysis
| Field Name     | Sample Value          | Purpose                                                   |
| -------------- | --------------------- | --------------------------------------------------------- |
| `syslog_month` | `Feb`                 | Syslog header time (month)                                |
| `syslog_day`   | `21`                  | Syslog header time (day)                                  |
| `syslog_time`  | `15:45:27`            | Syslog receive time (second-level)                        |
| `host`         | `_gateway`            | Syslog sender hostname                                    |
| `date`         | `2026-02-21`          | FortiGate event date (business time)                      |
| `time`         | `15:45:26`            | FortiGate event time (business time)                      |
| `devname`      | `DAHUA_FORTIGATE`     | Firewall device name                                      |
| `devid`        | `FG100ETK20014183`    | Firewall unique device ID                                 |
| `logid`        | `0001000014`          | FortiGate log type ID                                     |
| `type`         | `traffic`             | Log primary category (traffic)                            |
| `subtype`      | `local`               | Log subtype (local-plane traffic)                         |
| `level`        | `notice`              | Event level                                               |
| `vd`           | `root`                | VDOM name                                                 |
| `eventtime`    | `1771685127249713472` | High-precision native event timestamp                     |
| `tz`           | `+0100`               | Time zone                                                 |
| `srcip`        | `192.168.16.41`       | Source IP                                                 |
| `srcname`      | `es-73847E56DA65`     | Source name / endpoint identifier                         |
| `srcport`      | `48689`               | Source port                                               |
| `srcintf`      | `LACP`                | Source interface                                          |
| `srcintfrole`  | `lan`                 | Source interface role                                     |
| `dstip`        | `255.255.255.255`     | Destination IP (broadcast address)                        |
| `dstport`      | `48689`               | Destination port                                          |
| `dstintf`      | `unknown0`            | Destination interface (local-plane / special target clue) |
| `dstintfrole`  | `undefined`           | Destination interface role                                |
| `sessionid`    | `1211202700`          | Session ID (correlation key)                              |
| `proto`        | `17`                  | Protocol number (UDP)                                     |
| `action`       | `deny`                | Action result (deny)                                      |
| `policyid`     | `0`                   | Policy ID                                                 |
| `policytype`   | `local-in-policy`     | Matched policy type (local-plane)                         |
| `service`      | `udp/48689`           | Service / port label                                      |
| `dstcountry`   | `Reserved`            | Destination country (reserved address space)              |
| `srccountry`   | `Reserved`            | Source country (reserved address space)                   |
| `trandisp`     | `noop`                | Transport / processing status information                 |
| `app`          | `udp/48689`           | Application identification result (port-level)            |
| `duration`     | `0`                   | Session duration                                          |
| `sentbyte`     | `0`                   | Sent bytes                                                |
| `rcvdbyte`     | `0`                   | Received bytes                                            |
| `sentpkt`      | `0`                   | Sent packets                                              |
| `appcat`       | `unscanned`           | Application category status                               |
| `srchwvendor`  | `Samsung`             | Source hardware vendor (asset profile)                    |
| `devtype`      | `Phone`               | Device type (asset profile)                               |
| `srcfamily`    | `Galaxy`              | Device family (asset profile)                             |
| `osname`       | `Android`             | OS name (asset profile)                                   |
| `srcswversion` | `16`                  | OS/software version (asset profile)                       |
| `mastersrcmac` | `78:66:9d:a3:4f:51`   | Master source MAC (device identity normalization clue)    |
| `srcmac`       | `78:66:9d:a3:4f:51`   | Source MAC (device identity normalization clue)           |
| `srcserver`    | `0`                   | Device role hint (endpoint / non-server)                  |

### 2.1.2 Ingest Pod Processing Pipeline (`edge/fortigate-ingest`)

The responsibility of `edge/fortigate-ingest` is not “simple log forwarding,” but to convert FortiGate raw syslog text (`/data/fortigate-runtime/input/fortigate.log` and rotated files `fortigate.log-YYYYMMDD-HHMMSS[.gz]`) into a structured fact event stream (JSONL) that is auditable, replayable, and directly usable for aggregation analytics. The main loop processing order is fixed as **rotated first (historical backfill) → active next (near-real-time tailing)**: rotated files are sorted by filename timestamp and scanned sequentially to avoid missing historical logs after startup/restart; the active file is continuously tailed based on byte offset to balance real-time ingestion and recoverability. Outputs are written as hourly partitioned files `events-YYYYMMDD-HH.jsonl` (with separate DLQ/metrics JSONL files), facilitating unified downstream batch/stream consumption.

When processing a single log line, the pipeline first splits the **syslog header** and the **FortiGate `key=value` payload**, then performs field parsing and type normalization (numeric fields converted to `int`, missing fields retained as `null`), and generates a structured event including: normalized `event_ts` (prefer `date+time+tz`), preserved raw time-semantic fields (such as `eventtime`/`tz`), derived statistics (such as `bytes_total` / `pkts_total`), a normalized device key (`src_device_key`, for asset-level aggregation/anomaly correlation), and `kv_subset` for trace-back and schema extension. Successfully parsed events are written to `events-*.jsonl`; failed lines are written to DLQ (with `reason/raw/source`), ensuring that the conversion chain from “raw text → structured event” has fault tolerance and troubleshooting capability.

The key reliability design of this component is the **checkpoint + inode/offset + completed deduplication mechanism**. `checkpoint.json` stores three categories of state: `active` (the current active file `path/inode/offset/last_event_ts_seen`), `completed` (records of fully processed rotated files, using `path|inode|size|mtime` as a unique key to prevent duplicate historical backfill), and `counters` (cumulative counters such as `lines/bytes/events/dlq/parse_fail/write_fail/checkpoint_fail`). After a rotated file is completed, `mark_completed()` is called to persist the ledger entry; when tailing the active file, ingest resumes from the checkpoint `inode+offset`, and resets/re-scans offsets when detecting **inode change (rotation switch)** or **file truncation (`size < offset`)**, preventing out-of-range reads, duplicates, and misses. The checkpoint is persisted atomically via temporary file write + `fsync` + `os.replace`; each event is enriched with `ingest_ts` (UTC) and `source.path/inode/offset` (`offset=null` for `.gz` in most cases), enabling precise audit, replay localization, and idempotent reprocessing.

### 2.1.3 Output Sample (Parsed JSONL) Field List (62 top-level fields + 3 `source` subfields)
**Output sample (parsed)**: demonstrates that ingest has stably converted text logs into an analyzable schema (time normalization, derived fields, device key, source audit metadata)

```text
{"schema_version":1,"event_id":"d811b6b7c362dd6367f3736a19bc9ade","host":"_gateway","event_ts":"2026-01-15T16:49:21+01:00","type":"traffic","subtype":"forward","level":"notice","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","vd":"root","action":"deny","policyid":0,"policytype":"policy","sessionid":1066028432,"proto":17,"service":"udp/3702","srcip":"192.168.1.133","srcport":3702,"srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":3702,"dstintf":"LAN2","dstintfrole":"lan","sentbyte":0,"rcvdbyte":0,"sentpkt":0,"rcvdpkt":null,"bytes_total":0,"pkts_total":0,"parse_status":"ok","logid":"0000000013","eventtime":"1768492161732986577","tz":"+0100","logdesc":null,"user":null,"ui":null,"method":null,"status":null,"reason":null,"msg":null,"trandisp":"noop","app":null,"appcat":"unscanned","duration":0,"srcname":null,"srccountry":"Reserved","dstcountry":"Reserved","osname":null,"srcswversion":null,"srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":0,"srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P","srchwmodel":null,"src_device_key":"b4:4c:3b:c1:29:c1","kv_subset":{"date":"2026-01-15","time":"16:49:21","tz":"+0100","eventtime":"1768492161732986577","logid":"0000000013","type":"traffic","subtype":"forward","level":"notice","vd":"root","action":"deny","policyid":"0","policytype":"policy","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","sessionid":"1066028432","proto":"17","service":"udp/3702","srcip":"192.168.1.133","srcport":"3702","srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":"3702","dstintf":"LAN2","dstintfrole":"lan","trandisp":"noop","duration":"0","sentbyte":"0","rcvdbyte":"0","sentpkt":"0","appcat":"unscanned","dstcountry":"Reserved","srccountry":"Reserved","srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":"0","srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P"},"ingest_ts":"2026-02-16T19:59:59.808411+00:00","source":{"path":"/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz","inode":6160578,"offset":null}}
```

| Field Name       | Sample Value                                                     | Purpose                                                                |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `source.path`    | `/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz` | Source file path (rotated file localization)                           |
| `source.inode`   | `6160578`                                                        | File inode (file identity)                                             |
| `source.offset`  | `null`                                                           | Offset (commonly null for compressed files)                            |
| `schema_version` | `1`                                                              | Output schema version                                                  |
| `event_id`       | `d811b6b7c362dd6367f3736a19bc9ade`                               | Unique event ID (deduplication / idempotency)                          |
| `host`           | `_gateway`                                                       | Preserved syslog host                                                  |
| `event_ts`       | `2026-01-15T16:49:21+01:00`                                      | Normalized event time (primary field for downstream windowing/sorting) |
| `type`           | `traffic`                                                        | Log primary category                                                   |
| `subtype`        | `forward`                                                        | Log subtype (forwarded traffic)                                        |
| `level`          | `notice`                                                         | Event level                                                            |
| `devname`        | `DAHUA_FORTIGATE`                                                | Firewall device name                                                   |
| `devid`          | `FG100ETK20014183`                                               | Firewall device ID                                                     |
| `vd`             | `root`                                                           | VDOM                                                                   |
| `action`         | `deny`                                                           | Action result                                                          |
| `policyid`       | `0`                                                              | Policy ID                                                              |
| `policytype`     | `policy`                                                         | Policy type (regular forwarding policy)                                |
| `sessionid`      | `1066028432`                                                     | Session correlation key                                                |
| `proto`          | `17`                                                             | Protocol number (UDP)                                                  |
| `service`        | `udp/3702`                                                       | Service / port label                                                   |
| `srcip`          | `192.168.1.133`                                                  | Source IP                                                              |
| `srcport`        | `3702`                                                           | Source port                                                            |
| `srcintf`        | `fortilink`                                                      | Source interface                                                       |
| `srcintfrole`    | `lan`                                                            | Source interface role                                                  |
| `dstip`          | `192.168.2.108`                                                  | Destination IP                                                         |
| `dstport`        | `3702`                                                           | Destination port                                                       |
| `dstintf`        | `LAN2`                                                           | Destination interface                                                  |
| `dstintfrole`    | `lan`                                                            | Destination interface role                                             |
| `sentbyte`       | `0`                                                              | Sent bytes                                                             |
| `rcvdbyte`       | `0`                                                              | Received bytes                                                         |
| `sentpkt`        | `0`                                                              | Sent packets                                                           |
| `rcvdpkt`        | `null`                                                           | Received packets (nullable)                                            |
| `bytes_total`    | `0`                                                              | Derived total bytes (aggregation-friendly)                             |
| `pkts_total`     | `0`                                                              | Derived total packets (aggregation-friendly)                           |
| `parse_status`   | `ok`                                                             | Parsing status                                                         |
| `logid`          | `0000000013`                                                     | FortiGate log ID                                                       |
| `eventtime`      | `1768492161732986577`                                            | Native high-precision event time                                       |
| `tz`             | `+0100`                                                          | Time zone                                                              |
| `logdesc`        | `null`                                                           | Native log description (nullable)                                      |
| `user`           | `null`                                                           | User field (nullable)                                                  |
| `ui`             | `null`                                                           | UI/entry field (nullable)                                              |
| `method`         | `null`                                                           | Method/action field (nullable)                                         |
| `status`         | `null`                                                           | Status field (nullable)                                                |
| `reason`         | `null`                                                           | Reason field (nullable)                                                |
| `msg`            | `null`                                                           | Text message field (nullable)                                          |
| `trandisp`       | `noop`                                                           | Transport/processing status information                                |
| `app`            | `null`                                                           | Application identification (nullable)                                  |
| `appcat`         | `unscanned`                                                      | Application category status                                            |
| `duration`       | `0`                                                              | Session duration                                                       |
| `srcname`        | `null`                                                           | Source endpoint name (nullable)                                        |
| `srccountry`     | `Reserved`                                                       | Source country/address-space classification                            |
| `dstcountry`     | `Reserved`                                                       | Destination country/address-space classification                       |
| `osname`         | `null`                                                           | OS name (nullable)                                                     |
| `srcswversion`   | `null`                                                           | Software/OS version (nullable)                                         |
| `srcmac`         | `b4:4c:3b:c1:29:c1`                                              | Source MAC                                                             |
| `mastersrcmac`   | `b4:4c:3b:c1:29:c1`                                              | Master source MAC                                                      |
| `srcserver`      | `0`                                                              | Device role hint                                                       |
| `srchwvendor`    | `Dahua`                                                          | Hardware vendor (asset profile)                                        |
| `devtype`        | `IP Camera`                                                      | Device type (asset profile)                                            |
| `srcfamily`      | `IP Camera`                                                      | Device family (asset profile)                                          |
| `srchwversion`   | `DHI-VTO4202FB-P`                                                | Hardware model/version (asset profile)                                 |
| `srchwmodel`     | `null`                                                           | Hardware model field (nullable)                                        |
| `src_device_key` | `b4:4c:3b:c1:29:c1`                                              | Normalized device key (core asset-baseline key)                        |
| `kv_subset`      | `{...}`                                                          | Raw KV subset snapshot (trace-back / validation / schema extension)    |
| `ingest_ts`      | `2026-02-16T19:59:59.808411+00:00`                               | Ingest output timestamp                                                |
| `source`         | `{"path":"...","inode":6160578,"offset":null}`                   | Input source metadata (audit / replay localization)                    |

### 2.1.4 Throughput Snapshot (March 3, 2026)

The following baseline was sampled on **March 3, 2026 (CET)** for current topic/partition capacity planning.

- Sampling window (edge local sample script): `60s`
- Sampling window (Kafka end-offset delta): `15s`
- Data path: `fortigate.log` write -> edge node input
- Data path: `edge-forwarder` -> `netops.facts.raw.v1`
- Data path: `core-correlator` -> `netops.alerts.v1`

| Metric | Value | Notes |
| --- | ---: | --- |
| FortiGate active log write rate | `4,621.58 B/s` | 60s sample (`277,312 bytes / 60s`) |
| Parsed JSONL output write rate | `37,421.04 B/s` | 60s sample (`2,245,401 bytes / 60s`) |
| Kafka raw ingest rate (`netops.facts.raw.v1`) | `3,116.33 events/s` | 15s partition end-offset delta (`46,745 / 15s`) |
| Kafka alerts output rate (`netops.alerts.v1`) | `155.27 alerts/s` | 15s partition end-offset delta (`2,329 / 15s`) |
| Correlator consumer lag (`core-correlator-v1`) | `12,361` | Snapshot sum of 6 raw-topic partitions |

> [!NOTE]
> For partition planning, use repeated runs and keep at least P95 headroom (for example, target <60% sustained partition utilization during peak windows).

## 3. Core Components (Planned Scope and Current Implementation Boundary)

The core side (`netops-node1 / r450`) is positioned as the **Data Plane + Core Analytics** hosting node. It is responsible for receiving the structured fact event stream produced by the edge-side `edge/fortigate-ingest`, and for completing event decoupling, basic aggregation, correlation analysis, alert cluster generation, and the execution entry for subsequent intelligent augmented inference (LLM/Agent). The current architectural objective is to first establish a **stable, observable, and extensible** minimal closed loop: `ingest output -> broker/queue -> consumer/correlator -> alert context -> (optional) LLM inference queue`.

### 3.1 Core-Side Objectives at the Current Stage (README-ready)
- **Data plane ingress**: receive the fact event stream output from `r230` and establish a stable transport/consumption entry point (decoupling edge production from core consumption).
- **Minimal streaming consumption pipeline**: implement a basic consumer/correlator for window aggregation, rule triggering, and alert context construction.
- **Reserved intelligent augmentation entry**: retain an `LLM inference queue` and rate-limiting mechanism on the core side for future alert-level inference (explanation / root-cause assistance / Runbook draft generation), without blocking the main pipeline.
- **Clear layering boundary**: real-time detection and basic correlation are handled by deterministic streaming modules; LLM/Agent only processes high-value alert clusters and does not participate in per-event full-stream classification.

### 3.2 Evaluated but Not Adopted at This Stage (Flink Direction)
A **ByteDance-related Flink solution** was evaluated during the early stage of the project (validation already performed). However, under the current environment constraints (`k3s`, single core node `r450`, limited memory, no GPU, and priority on fast closed-loop delivery with low operational overhead), the conclusion is: **it is not suitable as the main core-side path at this stage**. The primary reason is its relatively high runtime resource requirements, component orchestration complexity, and operational cost, which do not match the current objective of “first establishing the data plane and the minimal analytics closed loop.” Flink-class frameworks may be re-evaluated later if event scale, stateful computation complexity, and throughput requirements increase significantly.

### 3.3 Core Technology Stack and Deployment Plan (Current Mainline)
The core side (`netops-node1 / r450`) adopts **Kafka (KRaft, single-node) + Python Consumer/Correlator + (optional) LLM inference service**, running on `k3s`. The current objective is to prioritize the `r230 -> r450` data plane and the minimal correlation-analysis closed loop, while keeping deployment complexity controllable, the pipeline observable, and the future expansion path clear under constrained resources.

**Technology Stack (Current Stage)**
- **Core Broker**: `Apache Kafka (KRaft mode, single-node)` (event ingress, producer-consumer decoupling, Topic/Consumer Group extensibility)
- **Core Consumer / Correlator**: `Python 3.11 + Kafka Client + window aggregation / rule-correlation modules` (event consumption, aggregation, anomaly cluster construction, alert context generation)
- **Inference Entry (TBD)**: `Inference Queue + resident inference service (rate-limited)` (only for explanation / root-cause assistance / Runbook draft generation on high-value alert clusters)

### 3.4 Phase-2 Current Implementation (Repository State)

Phase-2 minimal pipeline has been implemented with clear module boundaries:

- `edge/edge_forwarder`: edge-side producer (`events-*.jsonl` -> Kafka raw topic)
- `edge/edge_forwarder/infra`: edge-forwarder local infra utilities (`env` config, logging, checkpoint I/O)
- `core/correlator`: core-side consumer/correlator (raw topic -> alert topic)
- `core/infra`: core-side shared helpers for correlator path
- `core/benchmark`: load-test and throughput probe utilities
- `core/deployments`: k3s manifests (`namespace`, `kafka`, `topic-init`, `correlator`)
- `core/docker`: core app image build entry
- `edge/edge_forwarder/deployments`: edge-forwarder deployment manifest
- `edge/edge_forwarder/docker`: edge-forwarder image build entry

Current dataflow:

`fortigate-ingest (/data/fortigate-runtime/output/parsed/events-*.jsonl)`
`-> edge-forwarder (r230)`
`-> netops.facts.raw.v1`
`-> core-correlator (r450)`
`-> netops.alerts.v1`
`-> core-alerts-sink (r450, /data/netops-runtime/alerts/*.jsonl)`

DLQ channel is reserved as `netops.dlq.v1` for malformed/replay-failed records.

### 3.5 Phase-2 Deployment Procedure (k3s)

```bash
kubectl apply -f core/deployments/00-namespace.yaml
kubectl apply -f core/deployments/10-kafka-kraft.yaml
kubectl delete job -n netops-core netops-kafka-topic-init --ignore-not-found
kubectl apply -f core/deployments/20-topic-init-job.yaml
kubectl apply -f core/deployments/40-core-correlator.yaml
kubectl apply -f edge/deployments/00-edge-namespace.yaml
kubectl apply -f edge/edge_forwarder/deployments/30-edge-forwarder.yaml
```

Recommended operation model: use one terminal/session on core node for `core/*`,
and a separate terminal/session on edge node for `edge/*` release tasks.

Edge-side one-shot release entries:

```bash
./edge/fortigate-ingest/scripts/deploy_ingest.sh
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh
```

### 3.6 Throughput Measurement and Pressure Testing

Use `core/benchmark` scripts for partition sizing and throughput baselining:

```bash
python -m core.benchmark.kafka_load_producer \
  --bootstrap-servers netops-kafka.netops-core.svc.cluster.local:9092 \
  --topic netops.facts.raw.v1 \
  --messages 200000 \
  --payload-bytes 1024 \
  --batch-size 1000 \
  --workers 4
```

```bash
python -m core.benchmark.kafka_topic_probe \
  --bootstrap-servers netops-kafka.netops-core.svc.cluster.local:9092 \
  --topic netops.facts.raw.v1 \
  --group-id benchmark-probe-v1 \
  --duration-sec 60
```

Edge producer runtime rate (r230) can be observed directly from forwarder logs (`eps`, `mbps`, cumulative counters):

```bash
kubectl logs -n edge deploy/edge-forwarder --tail=200 -f
```

Correlator quality-gate/throughput stats can be observed from periodic stats logs:

```bash
kubectl logs -n netops-core deploy/core-correlator --tail=200 -f
```

## X.0 Potential Required Resources and Support
This section describes the resources and support required to advance the project from the current stage (`r230 -> r450` data plane and core analytics capability construction) to **core streaming analytics + alert-level LLM-augmented inference (CPU/GPU)**. Resource request priorities are focused on **memory expansion** and **GPU (core-side AI inference acceleration)**,

if such support can be obtained. Mais je ne retiens pas mon souffle XD

### X.1 Current Hardware Baseline (Already Available)

- **netops-node2 / r230 (Edge Side)**
  - CPU: `Intel Xeon E3-1220 v5` (4C/4T)
  - Memory: `~8 GB`
  - Role: `Edge Ingestion` (with `edge/fortigate-ingest` already deployed and running)
  - Disk: `1TB SSD` (sufficient for current ingest input/output and replay file storage)

- **netops-node1 / r450 (Core Side)**
  - CPU: `Intel Xeon Silver 4310` (12C/24T)
  - Memory: `~16 GB` (`HMA82GR7DJR8N-XN | DDR4 ECC RDIMM`)
  - GPU: None (only Matrox management display controller, not for AI inference)
  - Role: `Core Data Plane / Core Analytics` (future host for broker, correlator, and alert-level LLM-augmented inference)
  - Disk: `2TB SSD` (sufficient for broker data, event cache, and analytics artifact storage)

> The current primary bottlenecks on the core side are not CPU, but **insufficient memory capacity (~16GB)** and the **absence of an inference-capable GPU**.

### X.2 P0 (Highest Priority) Resource Request: Core-Side Memory Expansion + GPU

For `r450` (`netops-node1`) to host `broker + correlator + queue + resident LLM service (rate-limited queue mode)`, the P0 resource request priority is **memory expansion + inference GPU**. The current core-side memory (~16GB) is insufficient to stably support concurrent operation of the core data plane and alert-level LLM-augmented inference. The requested memory expansion is **3×16GB (48GB)** of matching specification.

For GPU resources, the target is **1 GPU suitable for local inference (or a server with such a GPU)** to support a single resident model + rate-limited queue. Suggested examples include **NVIDIA A2 16GB** or **NVIDIA L4 24GB** (or equivalent). Any future upgrade to higher VRAM or multi-GPU should be decided based on actual Agent concurrency and inference load validation results.

### X.3 P1 Resource Request: Edge-Side `r230` Memory Expansion (Stability)

`r230` (`netops-node2`) currently has ~8GB memory, which is sufficient for the current `fortigate-ingest`; however, if additional device log sources, increased historical backfill volume, and pre-forwarding components are introduced later, memory expansion is recommended to improve edge-side stability and buffering headroom. The memory specification for this node should be **DDR4 ECC UDIMM (compatible with R230 / Xeon E3-1220 v5)**, with a recommended configuration of **2×16GB (32GB)** and at least **2×8GB (16GB)**.

> [!IMPORTANT]
> Its memory specification is not compatible with the **DDR4 ECC RDIMM** used by `r450` and cannot be mixed.

### X.4 P1 Resource Request: R&D and Training Support (AI / Agent / AIOps)

In addition to hardware, school-side R&D / faculty support is recommended to support implementation of the `Core Analytics + Multiple Agent + LLM` stage, including: **local LLM inference and deployment (CPU/GPU, quantized models, rate-limited queues)**, **LLM application engineering (Prompting, structured output, Tool Calling, RAG)**, **Multiple Agent orchestration and boundary design (responsibility split, fallback handling, observability)**, and **AIOps analytics methods and evaluation (evidence chains, alert consolidation, Runbook quality evaluation)**. Stage-based access to campus GPU servers or private model platforms is also recommended.
