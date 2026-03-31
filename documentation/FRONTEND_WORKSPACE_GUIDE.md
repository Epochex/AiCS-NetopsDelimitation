# Frontend Workspace Guide / Frontend 工作区指南

This note replaces the old `frontend/README*.md`.

这份文档接管原来的 `frontend/README*.md`，把前端工作区说明统一收口到 `documentation/`。

## Why `frontend/` Exists Separately / 为什么 `frontend/` 要单独存在

The separation is deliberate:

- `core/` stays focused on deterministic pipeline logic and bounded AIOps modules
- `edge/` stays focused on ingest and forwarding
- `frontend/` evolves on its own dependency graph, build pipeline, and interaction cadence

这种拆分是有意为之：

- `core/` 只承载确定性链路和 bounded AIOps 模块
- `edge/` 只承载接入和转发
- `frontend/` 单独维护自己的依赖、构建链和交互节奏

## Current Frontend Scope / 当前前端范围

The frontend is a process-centric runtime console, not a generic admin dashboard.

Major UI surfaces map back to real backend concepts:

- global runtime overview
- pipeline topology
- runtime chain
- evidence drawer
- cluster pre-trigger watch

## Commands / 常用命令

```bash
PATH=/data/.local/node/bin:$PATH npm install
python3 -m pip install --target /data/.local/netops-console-py -r frontend/gateway/requirements.txt

PATH=/data/.local/node/bin:$PATH npm run dev
PATH=/data/.local/node/bin:$PATH npm run dev:gateway
PATH=/data/.local/node/bin:$PATH npm run build
```

Local defaults / 本地默认端口：

- UI: `:5173`
- FastAPI gateway: `:8026`
- Vite proxies `/api`

## Runtime Shape / 运行时形态

- `GET /api/runtime/snapshot`
- `GET /api/runtime/stream`
- gateway reads `/data/netops-runtime` and deployment env controls from the repo

The detailed architecture note stays here:

- [Frontend runtime architecture](./FRONTEND_RUNTIME_ARCHITECTURE_20260328.md)
- [Frontend runtime architecture CN](./FRONTEND_RUNTIME_ARCHITECTURE_20260328_CN.md)
- [Frontend runtime architecture EN](./FRONTEND_RUNTIME_ARCHITECTURE_20260328_EN.md)

## Deployment Shape / 部署形态

Default recommendation / 当前默认推荐：

- local Vite dev server
- local FastAPI thin gateway
- no need to prioritize k3s packaging first

Shareable host setup / 共享环境建议：

- static frontend assets served by `nginx`
- FastAPI gateway on internal `:8026`
- same-origin deployment preferred over cross-origin plumbing

## Stack / 技术栈

- `React + Vite + TypeScript`
- `ECharts`
- `React Flow`
- `FastAPI + SSE`
- `nginx + systemd`
- `PyYAML`
- optional `Docker + k3s Deployment`
