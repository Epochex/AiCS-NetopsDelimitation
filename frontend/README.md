# Frontend

This directory is a standalone frontend workspace that sits alongside `core/`,
`edge/`, and `documentation/`.

## Why a separate top-level `frontend/`

Yes, this is the right engineering shape for the current repository stage.

- `core/` stays focused on deterministic pipeline logic and AIOps runtime modules.
- `edge/` stays focused on ingest and forwarding.
- `frontend/` can evolve on its own cadence without polluting backend module
  boundaries.
- The UI now has its own dependency graph, build pipeline, and visual language.

That keeps the repository honest: runtime processing does not get mixed with
presentation code.

## Current scope

The first implementation intentionally avoids a generic admin template.

The information architecture is inferred from the real backend pipeline already
present in the repository:

- `FortiGate -> edge ingest -> edge-forwarder -> netops.facts.raw.v1`
- `core-correlator -> netops.alerts.v1`
- `core-alerts-sink / ClickHouse`
- `core-aiops-agent -> netops.aiops.suggestions.v1`
- reserved remediation control point

Every major UI block maps back to a real backend concept, runtime state, or
control point:

- `Global Runtime Overview`: freshness, lag, backlog, closure posture
- `Event Flow / Pipeline Topology`: module and topic boundaries
- `Runtime Chain`: event lifecycle and causality
- `Evidence Drawer`: real suggestion schema, evidence bundle, confidence, and
  actions
- `Cluster Pre-Trigger Watch`: same backend cluster semantics without faking a
  natural hit

## Commands

This workspace expects the local Node toolchain prepared in `/data/.local/node`.
The thin gateway can be installed into a local Python target directory without
touching the existing backend environment.

```bash
PATH=/data/.local/node/bin:$PATH npm install
python3 -m pip install --target /data/.local/netops-console-py -r frontend/gateway/requirements.txt

PATH=/data/.local/node/bin:$PATH npm run dev
PATH=/data/.local/node/bin:$PATH npm run dev:gateway
PATH=/data/.local/node/bin:$PATH npm run build
```

Local development uses:

- frontend UI on `:5173`
- FastAPI gateway on `:8026`
- Vite proxy for `/api`, so the browser does not need CORS during normal local work

## Runtime shape

This frontend is no longer static-only.

- `GET /api/runtime/snapshot` returns a live `RuntimeSnapshot`
- `GET /api/runtime/stream` pushes the same structure over `SSE`
- the gateway reads `/data/netops-runtime` plus deployment env values from the repository

The React app keeps the old static snapshot only as a safety fallback when the
gateway is unavailable.

## Deployment recommendation

For the current iteration stage, the lowest-friction path is:

- local Vite dev server
- local FastAPI gateway
- no k3s deployment yet

Why this is the best default right now:

- UI semantics are still being tuned against real backend behavior.
- Iterating on layout, animation, and evidence mapping is much faster outside the cluster.
- The gateway is read-only and thin, so there is little value in adding cluster deployment complexity too early.

When you want a shareable or reviewable environment, the recommended production
shape is:

- build the frontend once
- expose `:2026` through `nginx`
- keep the FastAPI gateway on internal `:8026`

That gives you:

- one origin
- no production CORS problem
- static assets on a real web server
- a long-lived gateway process that can keep streaming over `SSE`

## k3s option

Yes, this console can be deployed to k3s as a `Deployment`.

Artifacts already included:

- [Dockerfile](/data/Netops-causality-remediation/frontend/Dockerfile)
- [00-namespace.yaml](/data/Netops-causality-remediation/frontend/deployments/00-namespace.yaml)
- [10-netops-ops-console.yaml](/data/Netops-causality-remediation/frontend/deployments/10-netops-ops-console.yaml)

That deployment shape is intentionally single-service:

- FastAPI serves `/api/*`
- FastAPI also serves the built frontend
- the pod mounts `/data/netops-runtime`
- the pod stays pinned to `r450`, matching the current runtime host-path reality

## Ports and CORS

Recommended shape:

- local dev: two ports, `5173` for UI and `8026` for API
- review / shared host: `2026` public via `nginx`, `8026` internal via `FastAPI`
- k3s single-service option: one port, `8026`, same origin inside the pod

CORS is therefore not the primary design.

- In local development, Vite proxies `/api` to the gateway.
- In production, the frontend and API are served from the same FastAPI process.
- Only enable CORS when you intentionally split frontend and API onto different origins.

If you do need cross-origin access later, the gateway supports
`NETOPS_CONSOLE_CORS_ORIGINS` as a comma-separated env var.

## Stack

- `React + Vite + TypeScript` for fast UI iteration
- `ECharts` for compact time-series evidence
- `React Flow` for visible pipeline topology and control boundaries
- `FastAPI + SSE` for a thin live gateway with minimal operational overhead
- `nginx + systemd` for the current host-level production shape
- `PyYAML` for reading deployment env controls directly from the repo
- `Docker + k3s Deployment` as an optional packaging layer, not the default dev loop

## Design direction

The interface is intentionally:

- process-centric, not metric-centric
- tactical, not decorative
- rectangular and dense, not soft-card admin UI
- honest about what is live, what is inferred, and what is still a control
  boundary
