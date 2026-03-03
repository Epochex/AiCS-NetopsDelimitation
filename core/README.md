# Core Phase-2 Minimal Implementation

This directory contains the minimal, deployable phase-2 stack for the core node.

## Module Layout

- `core/infra`: shared config, logging, checkpoint helpers
- `core/edge_forwarder`: reads edge JSONL events and forwards to Kafka raw topic
- `core/correlator`: consumes raw topic and emits alert topic using deterministic rules
- `core/deployments`: k3s manifests for KRaft Kafka + forwarder + correlator
- `core/docker`: container build file for forwarder/correlator

## Data Plane Topics

- `netops.facts.raw.v1`: edge fact events
- `netops.alerts.v1`: correlator alerts
- `netops.dlq.v1`: reserved for malformed records / replay failures

## Build

```bash
docker build -t netops-core-app:0.1 -f core/docker/Dockerfile.app .
```

## Deploy Order

```bash
kubectl apply -f core/deployments/00-namespace.yaml
kubectl apply -f core/deployments/10-kafka-kraft.yaml
kubectl apply -f core/deployments/20-topic-init-job.yaml
kubectl apply -f core/deployments/30-edge-forwarder.yaml
kubectl apply -f core/deployments/40-core-correlator.yaml
```
