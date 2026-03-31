# FortiGate 接入字段参考

这份文档现在只保留 FortiGate ingest 契约的入口说明。
完整的原始输入表和 parsed 输出表已经拆到独立文档里：

- [FortiGate 原始输入字段分析](./FORTIGATE_INPUT_FIELD_ANALYSIS.md)
- [FortiGate parsed JSONL 输出样例](./FORTIGATE_PARSED_OUTPUT_SAMPLE.md)

如果你现在只需要先理解“这层契约到底在保什么”，看下面这张边界表就够了：

| 关注点 | 代表字段 | 为什么重要 |
| --- | --- | --- |
| 回放与来源 | `source.path`, `source.inode`, `source.offset`, `ingest_ts` | 安全续跑、审计定位、回放验证 |
| 稳定身份 | `event_id`, `src_device_key`, `sessionid` | 去重、设备聚合、后续关联 |
| 标准化时间 | `event_ts`, `eventtime`, `tz` | 给下游窗口规则提供确定性的事件时间契约 |
| 网络语义 | `srcip`, `srcport`, `dstip`, `dstport`, `proto`, `service` | 规则判断和 incident 定位依赖的流量形状 |
| 判定上下文 | `action`, `policyid`, `policytype`, `level`, `subtype` | 保留策略动作结果和流量类型 |
| 资产线索 | `srcmac`, `mastersrcmac`, `srchwvendor`, `devtype`, `srcfamily`, `srcswversion` | 设备画像、归因和定位 |
| 回溯载荷 | `parse_status`, `kv_subset` | schema 校验、parser 审计和后续演进 |

系统级上下文请继续看 [PROJECT_STATE_CN.md](./PROJECT_STATE_CN.md)。
