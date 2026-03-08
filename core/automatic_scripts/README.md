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
# release with explicit tag
./core/automatic_scripts/release_core_app.sh v20260303
```

#### What it does

1. `docker build` from `core/docker/Dockerfile.app`
2. `docker save` to tarball under `/tmp`
3. `k3s ctr images import` on local node (`r450`)
4. `kubectl set image` for `core-correlator`
5. `kubectl set image` for `core-alerts-sink`
6. `kubectl rollout status` wait until both are ready

## Notes

- Ensure `docker`, `kubectl`, and `k3s` are available on the core node.
- Edge forwarder release must use `edge/edge_forwarder/scripts/deploy_edge_forwarder.sh`.
- For reproducibility, always keep deployment env values in YAML and avoid long-term drift from ad-hoc `kubectl set env`.
