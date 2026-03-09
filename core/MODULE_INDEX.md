# Core Module Index

This file is a quick map for "which folder to edit" during feature changes.

## Runtime Modules

- `core/correlator`
  - Responsibility: consume `netops.facts.raw.v1`, quality gate + rules, emit `netops.alerts.v1`.
  - Typical changes: rule logic, threshold profile loading, DLQ behavior.
- `core/alerts_sink`
  - Responsibility: consume alerts topic, persist hourly JSONL.
  - Typical changes: sink file policy, output schema, sink reliability.
- `core/alerts_store`
  - Responsibility: consume alerts topic, write structured records into ClickHouse.
  - Typical changes: table schema, insert mapping, analytics fields.
- `core/aiops_agent`
  - Responsibility: consume alerts, produce suggestion records/topic for human-in-the-loop.
  - Typical changes: prompt/template policy, recommendation logic, confidence policy.
  - Internal modules:
    - `app_config.py`: env loading + severity gate policy.
    - `cluster_aggregator.py`: alert-window clustering and cooldown trigger logic.
    - `context_lookup.py`: ClickHouse similarity lookup.
    - `suggestion_engine.py`: suggestion payload generation.
    - `output_sink.py`: JSONL sink helpers.
    - `service.py`: runtime loop + commit/publish semantics.
    - `runtime_io.py`: Kafka/ClickHouse client builders.

## Shared Infra

- `core/infra`
  - Responsibility: config parsing, logging setup, checkpoint utilities.
  - Typical changes: shared env parsing, logging format, safe checkpointing.

## Deployment

- `core/deployments/40-*` `50-*` `60-*` `70-*` `80-*`
  - Responsibility: runtime deployment manifests.
  - Rule: all image/tag/env updates must be reflected here (or set via release script).

## Release Automation

- `core/automatic_scripts/release_core_app.sh`
  - Responsibility: build/import image, rollout core deployments, post-release import checks.
  - Rule: release this script first when introducing new runtime modules.

## Benchmark and Ops

- `core/benchmark`
  - Responsibility: throughput probes and quality observation.
  - Typical changes: SLO checks, windowed quality reports, pipeline runtime watch.

## Ownership Boundary

- `core/*` contains only core-node modules.
- `edge/*` contains only edge-node modules.
- No edge runtime component should be placed under `core/`.
