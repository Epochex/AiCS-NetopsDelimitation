# FortiGate Ingest Field Reference / FortiGate 接入字段参考

This page is now the landing note for the FortiGate ingest-side contract.
The full field tables were moved out of the root README and split into dedicated documents so the top-level project docs can stay architecture-focused.

这份文档现在作为 FortiGate ingest 契约的入口页。
原先塞在根 README 里的大字段表已经拆到独立文档里，避免顶层说明被大段 schema 表挤占。

## Use This Note When / 适用场景

- you need the parsing / replay / provenance boundary, but not every field row
- you want the direct links to the raw-input table and parsed-output table
- you need a short explanation of why these fields exist at all

- 你需要先理解解析 / 回放 / 来源边界，而不是马上看几十行字段表
- 你需要快速跳转到原始输入表和 parsed 输出表
- 你需要先知道这些字段为什么存在

## Split Documents / 已拆分文档

- [FortiGate input field analysis / FortiGate 原始输入字段分析](./FORTIGATE_INPUT_FIELD_ANALYSIS.md)
- [FortiGate parsed JSONL output sample / FortiGate 解析输出样例](./FORTIGATE_PARSED_OUTPUT_SAMPLE.md)

## What The Ingest Layer Must Preserve / ingest 层必须保留什么

| Concern / 关注点 | Representative fields / 代表字段 | Why it exists / 为什么必须保留 |
| --- | --- | --- |
| Replay and provenance / 回放与来源 | `source.path`, `source.inode`, `source.offset`, `ingest_ts` | safe resume, audit localization, failure recovery / 续跑、安全审计、失败恢复 |
| Stable identity / 稳定身份 | `event_id`, `src_device_key`, `sessionid` | deduplication, device grouping, later correlation / 去重、设备聚合、后续关联 |
| Normalized time / 标准化时间 | `event_ts`, `eventtime`, `tz` | sortable event-time contract for downstream windows / 为下游窗口规则提供可排序时间契约 |
| Network semantics / 网络语义 | `srcip`, `srcport`, `dstip`, `dstport`, `proto`, `service` | preserve traffic shape for deterministic rules / 保留确定性规则依赖的流量形状 |
| Decision context / 判定上下文 | `action`, `policyid`, `policytype`, `level`, `subtype` | retain enforcement outcome and traffic class / 保留策略动作结果和流量类别 |
| Asset hints / 资产线索 | `srcmac`, `mastersrcmac`, `srchwvendor`, `devtype`, `srcfamily`, `srcswversion` | later device profiling and localization / 后续设备画像与定位 |
| Trace-back payload / 回溯载荷 | `parse_status`, `kv_subset` | schema validation, parser audit, evolution buffer / schema 校验、parser 审计、演进缓冲 |

## Why This Boundary Matters / 为什么这个边界重要

`edge/fortigate-ingest` is not "file tailing plus text forwarding".
Its job is to turn FortiGate syslog into a structured fact contract that downstream correlation can trust without inheriting file-rotation chaos.

`edge/fortigate-ingest` 不是“盯住文件然后把文本转发出去”。
它的职责是把 FortiGate syslog 变成 downstream correlation 可以直接依赖的结构化事实契约，而不是把文件轮转和文本噪声一路带进核心侧。

## Related Docs / 相关文档

- [Current project state / 当前项目状态](./PROJECT_STATE.md)
- [Frontend runtime architecture / 前端 runtime 架构](./FRONTEND_RUNTIME_ARCHITECTURE_20260328.md)
