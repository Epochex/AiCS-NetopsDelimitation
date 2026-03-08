# Automatic Scripts

This directory stores one-shot automation scripts for core node components only.

## Scripts

### `release_core_app.sh`

Builds `netops-core-app`, imports the image on local core node runtime, updates
`core-correlator` image, and waits for rollout.

#### Usage

```bash
cd /data/Netops-causality-remediation
./core/automatic_scripts/release_core_app.sh
```

#### Optional arguments

```bash
# release with explicit tag to both deployments
./core/automatic_scripts/release_core_app.sh v20260303 all

# release only edge-forwarder
./core/automatic_scripts/release_core_app.sh v20260303 edge

# release only core deployments (core-correlator + core-alerts-sink)
./core/automatic_scripts/release_core_app.sh v20260303 core
```

#### Environment variables

```bash
EDGE_HOST=192.168.1.23 EDGE_USER=root ./core/automatic_scripts/release_core_app.sh
```

#### What it does

1. `docker build` from `core/docker/Dockerfile.app`
2. `docker save` to tarball under `/tmp`
3. `k3s ctr images import` on local node (`r450`)
4. `scp` tarball to edge node (`r230`)
5. remote `k3s ctr images import` on edge node
6. `kubectl set image` for target deployment(s)
   - `edge`: `edge-forwarder`
   - `core`: `core-correlator`, `core-alerts-sink`
7. `kubectl rollout status` wait until ready

## Notes

- Ensure `docker`, `kubectl`, and `k3s` are available on the core node.
- Edge forwarder release is handled separately by `edge/edge_forwarder/scripts/deploy_edge_forwarder.sh`.
- For reproducibility, always keep deployment env values in YAML and avoid long-term drift from ad-hoc `kubectl set env`.
