# NetOps 项目状态

- 最后更新：2026-03-31 UTC
- 本文范围：当前仓库姿态、当前挂载 runtime 事实，以及现阶段交付边界

## 当前目标

仓库已经不再停留在“原始日志能不能解析”的阶段。
当前目标是把整条链路保持为稳定、可解释、可验证的系统：

1. FortiGate syslog 先变成结构化 fact events
2. structured facts 经 Kafka 进入确定性 alerting
3. alerts 同时进入审计面和热查询面
4. bounded AIOps 在 alert context 之上输出 suggestion
5. runtime console 把结果投影成操作员可读链路

这个阶段真正关心的问题是：

- 链路是否仍然锚定在真实 runtime artifact 上
- 关键 evidence 能否从 ingest 一直进入 alert 和 suggestion
- alert 能否同时从文件审计和 ClickHouse 查询
- UI 是否如实表达运行态路径，而不是暗示执行能力已经存在

## 当前数据流

当前仓库主链是：

`FortiGate -> edge/fortigate-ingest -> edge/edge_forwarder -> netops.facts.raw.v1 -> core/correlator -> netops.alerts.v1 -> alerts_sink / alerts_store / aiops_agent -> netops.aiops.suggestions.v1 -> frontend runtime gateway`

这条链路当前每一段的含义是：

- `fortigate-ingest`：把厂商文本收束成可回放 facts
- `edge_forwarder`：把 edge 文件语义和共享传输解耦
- `correlator`：保持第一轮告警判断为确定性规则路径
- `alerts_sink`：保留 emitted alert 的审计记录
- `alerts_store`：保留可查询的近期历史
- `aiops_agent`：组装 evidence 并输出 bounded suggestion
- `frontend gateway`：把 runtime artifact 投影成只读操作员界面

## 当前挂载 Runtime 事实

当前工作区可直接访问的是 `/data/netops-runtime`。
下面这些事实都来自当前挂载数据，而不是旧文档中的历史数字：

| 运行切片 | 当前事实 |
| --- | --- |
| Alert sink 覆盖范围 | `554` 个小时文件，累计 `152,481` 条 alert |
| Alert sink 时间范围 | `2026-03-04T15:09:11+00:00` 到 `2026-03-27T23:00:17+00:00` |
| Suggestion sink 覆盖范围 | `480` 个小时文件 |
| Suggestion sink 时间范围 | `2026-03-09T05:08:56.549849+00:00` 到 `2026-03-31T15:36:55.895982+00:00` |
| 最新 6 个 alert 分桶 | `504` 条 alert，覆盖 `2026-03-27T18:00:14+00:00` 到 `2026-03-27T23:00:17+00:00` |
| 最新 6 个 suggestion 分桶 | `3,703` 条 suggestion，覆盖 `2026-03-31T10:00:16.165096+00:00` 到 `2026-03-31T15:36:55.895982+00:00` |
| 最近 24 个 alert 分桶 | `warning=2067`、`critical=2`；`deny_burst_v1=2067`、`bytes_spike_v1=2` |
| 最近 24 个 suggestion 分桶 | `alert=9058`、`cluster=1353`；provider 为 `template=10411` |

必须明确说明的现实情况：

- 当前工作区没有暴露 live 的 `/data/fortigate-runtime`
- 当前挂载 suggestion sink 的时间比 alert sink 更靠后
- 最新 suggestion 批次大多仍引用 3 月 26 日的 alert context

这说明仓库已经明确证明了 alert 和 suggestion 产物链路，但不能把当前这个挂载环境写成“每一层都严格时间同步的 live snapshot”。

## 当前已经落地的部分

- replay-aware FortiGate ingest
- edge forwarding 进入 Kafka raw topic
- `netops.alerts.v1` 上的确定性告警链路
- alert JSONL 审计落盘
- ClickHouse 热告警存储
- 同时支持 `alert` 和 `cluster` scope 的 bounded suggestion path
- 只读 runtime gateway 和 operator console

## 当前明确不在交付路径里的部分

- 设备写回
- 会修改线上状态的审批流
- 生产级闭环 remediation
- 全量 raw stream 上的模型首判
- “当前前端已经是执行控制台”这种说法

## 当前约束

- 推理不能被当作零成本热路径依赖
- 当前阶段回放和审计仍比叙事润色更重要
- 前端是 runtime projection，不是 control plane
- JSONL 和 ClickHouse 必须并存，因为审计和热检索不是一回事

## 相关文档

- [Edge 运行指南](./EDGE_RUNTIME_GUIDE.md)
- [Core 运行指南](./CORE_RUNTIME_GUIDE.md)
- [Frontend 工作区指南](./FRONTEND_WORKSPACE_GUIDE.md)
- [FortiGate 接入字段参考](./FORTIGATE_INGEST_FIELD_REFERENCE_CN.md)
- [前端 runtime 架构](./FRONTEND_RUNTIME_ARCHITECTURE_20260328_CN.md)
- [受控验证记录](./CONTROLLED_VALIDATION_20260322.md)
