# Edge Runtime Guide / Edge 运行指南

This note replaces the old edge-side README files and keeps all edge runtime notes in `documentation/`.

这份文档接管原来 `edge/` 下面的 README 说明，把 edge 侧运行说明统一收口到 `documentation/`。

## Scope / 范围

The edge side is responsible for only four jobs:

- receive raw device logs near the source
- preserve file, rotation, and replay semantics
- emit structured fact JSONL
- forward those facts into the shared Kafka raw topic

Edge is not responsible for:

- deterministic alerting
- AIOps suggestion generation
- frontend projection
- remediation execution

edge 侧只负责四件事：

- 在近源位置接住原始设备日志
- 处理文件、轮转和回放语义
- 产出结构化 fact JSONL
- 把 fact 送进共享 Kafka raw topic

edge 侧不负责：

- 确定性告警判断
- AIOps 建议生成
- 前端运行台投影
- remediation 执行

## Runtime Components / 运行组件

| Path | Responsibility |
| --- | --- |
| `edge/fortigate-ingest` | FortiGate ingest, parser, checkpoint, replay-safe JSONL emission |
| `edge/edge_forwarder` | parsed JSONL to `netops.facts.raw.v1` forwarding |
| `edge/deployments` | edge namespace and shared deployment manifests |
| `common/infra` | shared config, logging, checkpoint helpers used by edge/core |

## Deploy Baseline / 基线部署

```bash
kubectl apply -f edge/deployments/00-edge-namespace.yaml
kubectl apply -f edge/fortigate-ingest/ingest_pod.yaml
kubectl apply -f edge/edge_forwarder/deployments/30-edge-forwarder.yaml
```

## Release Entry Points / 发布入口

```bash
./edge/fortigate-ingest/scripts/deploy_ingest.sh
./edge/edge_forwarder/scripts/deploy_edge_forwarder.sh
```

Useful runtime logs / 常用运行日志：

```bash
kubectl logs -n edge deploy/fortigate-ingest --tail=200 -f
kubectl logs -n edge deploy/edge-forwarder --tail=200 -f
```

## Forwarder Notes / Forwarder 说明

`edge-forwarder` exists to separate file semantics from transport semantics.

It:

- reads parsed JSONL from the edge runtime volume
- forwards fact events into `netops.facts.raw.v1`
- preserves event meaning rather than re-parsing vendor payload

Per-scan metrics usually include:

- `eps`
- `mbps`
- `dropped_local_deny`
- `dropped_broadcast_mdns_nbns`

## Related Docs / 相关文档

- [FortiGate input field analysis](./FORTIGATE_INPUT_FIELD_ANALYSIS.md)
- [FortiGate parsed JSONL output sample](./FORTIGATE_PARSED_OUTPUT_SAMPLE.md)
- [Current project state](./PROJECT_STATE.md)
