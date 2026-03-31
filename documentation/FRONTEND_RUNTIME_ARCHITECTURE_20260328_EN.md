# Frontend Runtime Architecture 2026-03-28

This is a dated architecture note and incident record from `2026-03-28`.
Use it to understand the runtime-console interaction model and that day's failure mode, not as the canonical source for today's mounted runtime timestamps or deployment facts.
For current repository and mounted-runtime wording, use [README.md](../README.md) and [PROJECT_STATE_EN.md](./PROJECT_STATE_EN.md).

## Runtime Model

The console follows a thin-gateway model:

1. the browser loads the frontend
2. the UI can start from a local fallback snapshot
3. the UI fetches `GET /api/runtime/snapshot`
4. the UI opens `GET /api/runtime/stream` over `SSE`
5. the gateway reads runtime files and deployment controls
6. the gateway emits a projected `RuntimeSnapshot` for the console

The source files for that projection are primarily:

- `/data/netops-runtime/alerts/*.jsonl`
- `/data/netops-runtime/aiops/*.jsonl`
- deployment manifests under `core/` and `edge/`

The key implementation points are:

- `frontend/gateway/app/main.py`
- `frontend/gateway/app/runtime_reader.py`

## Why A Thin Gateway

The current console is meant to explain the live chain, not to become a second analytics backend.
Using a thin projection gateway has three concrete advantages at this stage:

- frontend fields stay close to runtime artifacts
- UI iteration does not force a redesign of the core data plane
- `SSE` is enough because updates are one-way and operator actions are not yet execution commands

## Current Deployment Shapes

### Local development

- frontend on `:5173`
- gateway on `:8026`
- Vite proxies `/api` to the gateway

### Host-level shared deployment

- external traffic enters via `nginx :2026`
- `/api/*` is proxied to `uvicorn/FastAPI :8026`
- runtime files remain on the host

This is the current practical deployment shape because the gateway is read-only and close to the runtime volume.

## Why The Console Remains Read-Only

The gateway assembles runtime state; it does not own the system of record and it does not mutate infrastructure.
That distinction matters. A projection layer can tolerate partial degradation and still remain useful to operators. A write-capable control plane needs approval, rollback, audit, and failure semantics that the current console does not yet provide.

## Related Documents

- [Project state](./PROJECT_STATE_EN.md)
- [Root README](../README.md)
- [Frontend workspace guide](./FRONTEND_WORKSPACE_GUIDE.md)
