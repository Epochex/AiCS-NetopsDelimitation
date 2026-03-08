# Edge Forwarder

`edge-forwarder` runs on edge node (`r230`) and forwards parsed JSONL events to Kafka raw topic.

## Module Layout

- `edge/edge_forwarder/main.py`: forwarder runtime loop
- `edge/edge_forwarder/infra`: config/logging/checkpoint helpers
- `edge/edge_forwarder/deployments/30-edge-forwarder.yaml`: k3s deployment manifest
- `edge/edge_forwarder/docker/Dockerfile.app`: forwarder-only image build entry
- `edge/edge_forwarder/scripts/deploy_edge_forwarder.sh`: edge-only release helper

## Build

```bash
docker build -t netops-edge-forwarder:0.1 -f edge/edge_forwarder/docker/Dockerfile.app .
```

## Deploy

```bash
kubectl apply -f edge/deployments/00-edge-namespace.yaml
kubectl apply -f edge/edge_forwarder/deployments/30-edge-forwarder.yaml
```

## Release Automation

Run on edge node window:

```bash
cd /data/Netops-causality-remediation
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh
```

Optional arguments:

```bash
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh --tag v20260303
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh --skip-build --skip-import
```

## Runtime Logs

```bash
kubectl logs -n edge deploy/edge-forwarder --tail=200 -f
```

Per-scan metrics include:
- `eps`
- `mbps`
- `dropped_local_deny`
- `dropped_broadcast_mdns_nbns`
