# Edge Components

This directory contains edge-node components and deployment automation only.

## Module Layout

- `edge/deployments`: edge namespace and edge-scoped manifests
- `edge/fortigate-ingest`: FortiGate ingest pipeline
- `edge/edge_forwarder`: parsed JSONL -> Kafka raw topic forwarder

## Deploy Baseline

```bash
kubectl apply -f edge/deployments/00-edge-namespace.yaml
kubectl apply -f edge/fortigate-ingest/ingest_pod.yaml
kubectl apply -f edge/edge_forwarder/deployments/30-edge-forwarder.yaml
```

## Edge Release Scripts

```bash
./edge/fortigate-ingest/scripts/deploy_ingest.sh
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh
```
