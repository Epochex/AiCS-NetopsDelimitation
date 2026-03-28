# NetOps Project State

本文件给“新会话 AI / 新协作者 / 未来自己”提供一个稳定、可直接接手的项目状态入口。

- 最后更新：2026-03-28 15:20 UTC
- 当前开发分支：`feature/frontend-demo`
- 配套问题日志：[ISSUES_LOG.md](./ISSUES_LOG.md)
- 本轮详细过程记录：[CONTROLLED_VALIDATION_20260322.md](./CONTROLLED_VALIDATION_20260322.md)
- 前端 runtime 架构与复盘：[FRONTEND_RUNTIME_ARCHITECTURE_20260328.md](./FRONTEND_RUNTIME_ARCHITECTURE_20260328.md)

## 1. 当前真实目标

当前项目的主目标不是做一个“会聊天的 AIOps demo”，而是把这条真实 NetOps / NSM 链路做成稳定、可验证、可扩展的最小闭环：

1. `FortiGate -> edge ingest -> Kafka raw`
2. `core correlator -> alerts topic`
3. `alerts -> JSONL / ClickHouse`
4. `AIOps slow path -> suggestions`

当前这个 slow path 已不是“只有 cluster 才出建议”，而是：

- 每条满足严重级别门槛的 alert 都会产出一条 `alert-scope` suggestion
- 如果同 key 告警在 AIOps 聚合器里达到 `600s / min=3 / cooldown=300s`，还会额外产出一条 `cluster-scope` suggestion

当前阶段最重要的判断标准只有两个：

- 链路是否处理真实 FortiGate 数据，而不是 mock
- 证据字段是否能从 edge 真正进入 core alert，而不是停留在 parser 或 raw 事件里

## 2. 当前架构

### 2.1 运行链路

1. `FortiGate`
   - 通过 syslog 发往 edge 节点 `192.168.1.23`

2. `edge/fortigate-ingest`
   - 读取 `/data/fortigate-runtime/input/fortigate.log*`
   - 解析 FortiGate syslog
   - 输出到 `/data/fortigate-runtime/output/parsed/events-*.jsonl`

3. `edge-forwarder`
   - 读取 parsed JSONL
   - 转发到 Kafka `netops.facts.raw.v1`

4. `core-correlator`
   - 消费 raw topic
   - 运行规则
   - 产出 Kafka `netops.alerts.v1`

5. `core-alerts-sink`
   - 把 alert 落盘到 `/data/netops-runtime/alerts/alerts-*.jsonl`
   - 文件名按 `alert.alert_ts` 分桶

6. `core-alerts-store`
   - 把 alert 写入 ClickHouse `netops.alerts`
   - 用于历史查询、统计和 AIOps 上下文检索

7. `core-aiops-agent`
   - 消费 `netops.alerts.v1`
   - 产出 Kafka `netops.aiops.suggestions.v1`
   - 同时落盘到 `/data/netops-runtime/aiops/suggestions-*.jsonl`
   - 文件名按当前处理时间分桶

### 2.2 组件职责

- Kafka：实时事件总线
- JSONL：文件证据层，便于审计和回放
- ClickHouse：alert 历史分析库，不是 raw 主存储
- AIOps Agent：慢路径，不承担实时主判定

## 3. 当前代码状态

### 3.1 已在当前仓库落地的内容

- edge 无损转发配置已在仓库中：
  - `edge/edge_forwarder/deployments/30-edge-forwarder.yaml`
  - `FORWARDER_FILTER_DROP_LOCAL_DENY=false`
  - `FORWARDER_FILTER_DROP_BROADCAST_MDNS_NBNS=false`

- edge parser 字段修复已在当前分支中：
  - 保留 `crscore/craction/crlevel`
  - 合成 `device_profile`
  - 对应远端 commit：`3e9d187`

- AIOps slow path 模块化骨架已落地：
  - `core/aiops_agent/app_config.py`
  - `core/aiops_agent/service.py`
  - `core/aiops_agent/evidence_bundle.py`
  - `core/aiops_agent/inference_queue.py`
  - `core/aiops_agent/inference_schema.py`
  - `core/aiops_agent/inference_worker.py`
  - `core/aiops_agent/providers.py`
  - `core/aiops_agent/suggestion_engine.py`

- AIOps 双路径建议已落地：
  - `alert-scope`：每条合格 alert 产出基础建议
  - `cluster-scope`：保留原簇触发建议，作为额外输出

- ClickHouse 上下文查询已加固：
  - `core/aiops_agent/context_lookup.py`
  - 兼容运行时 `result.first_item` 为 `dict` 的情况

- 核心验证脚本已落地：
  - `core/benchmark/aiops_replay_validation.py`
  - `core/benchmark/runtime_timestamp_audit.py`
  - `core/benchmark/live_runtime_check.py`

- core alert enrichment 已接进规则产物：
  - `topology_context`
  - `device_profile`
  - `change_context`

### 3.2 当前本地分支头部

- `3a76ec4` `Harden aiops ClickHouse context lookup`
- `ca14d7e` `Implement dual-path aiops suggestions`
- `8c47387` `docs: capture final runtime validation state`
- `3e9d187` `edge: preserve fortigate cr fields and device profile`

## 4. 当前运行态事实

### 4.1 core 运行态已与当前代码对齐

2026-03-22 已执行本地发布：

- 发布脚本：`core/automatic_scripts/release_core_app.sh`
- 运行镜像：`netops-core-app:v20260322-aiopsdualfix-3a76ec4`

当前 `netops-core` 中以下 deployment 都在跑这个 tag：

- `core-correlator`
- `core-alerts-sink`
- `core-alerts-store`
- `core-aiops-agent`

并且已确认：

- `core-aiops-agent` 容器内存在：
  - `service.py`
  - `app_config.py`
  - `evidence_bundle.py`
  - `providers.py`
- 老版本 `ClickHouse context TypeError` 不再出现

### 4.2 edge 运行态已回到实时态

2026-03-22 已完成 edge backlog 定点重置：

- 先将 `fortigate-ingest` 缩容到 `0`
- 使用临时 helper pod 挂载 `/data/fortigate-runtime`
- 备份 checkpoint：
  - `/data/fortigate-runtime/work/checkpoint.pre-realtime-reset-20260322T200250Z.json`
- 将漏掉的 rotated 文件记入 `completed`
  - `fortigate.log-20260319-000017.gz`
  - `fortigate.log-20260321-000026`
- 将 active inode / offset 提升到当时 `fortigate.log` 文件末尾
- 再将 `fortigate-ingest` 拉回 `1`

重置后已确认：

- `fortigate-ingest` heartbeat 中 `lag_bytes` 降到 `0` 或接近 `0`
- 最新 parsed 记录的 `source.path` 回到：
  - `/data/fortigate-runtime/input/fortigate.log`
- 最新 parsed / Kafka raw 的 `event_ts` 已接近当前时间

### 4.3 live runtime 当前结论

`python3 -m core.benchmark.live_runtime_check` 在 2026-03-22 21:55 UTC 的关键结果：

- `history_backlog_suspected = false`
- `latest_raw_payload_age_sec = 4`
- `latest_alert_event_age_sec = 35`
- 最新 alert 落盘文件：
  - `alerts-20260322-21.jsonl`
- 最新 suggestion 落盘文件：
  - `suggestions-20260322-21.jsonl`

最近 1000 条 alert 的字段出现率已进一步抬升：

- `topology_context = 0.024`
- `device_profile = 0.024`
- `change_context = 0.011`

含义：

- raw 已经稳定保持实时
- alert 已重新进入当前时间窗口
- 新字段已开始稳定进入近期 alert
- suggestion 也已重新回到当前时间窗口，不再卡在历史 19:39 UTC

## 5. 本轮关键验证结论

### 5.1 第一轮受控验证：证明 enrichment 路径是通的

在 replay 阶段曾临时把 `RULE_DENY_THRESHOLD` 从 `200` 下调到 `30`，成功得到新 alert，并确认 alert 中已经出现：

- `topology_context`
- `device_profile`
- `change_context`

这一步证明了：

- rich raw 可以进入 enriched alert
- core 代码路径已经生效

### 5.2 第二轮受控验证：在“实时 raw”上再次证明

edge 重置回实时后，再次做了短时阈值验证：

- 先确认当前实时 raw 中确实存在 `crscore` / `device_profile`
- 再临时把 `RULE_DENY_THRESHOLD` 降到 `5`
- 成功得到当前时间 alert：
  - `alert_id = d4a9761262c5c8781e6dc1e6477a97efe8f6cc43`
  - `alert_ts = 2026-03-22T20:07:59+00:00`
  - `source_event_id = 578912762fac6b71cb9553bec3c7af45`

该 alert 已明确包含：

- `topology_context.service = "Dahua SDK"`
- `device_profile.srcmac = "d4:43:0e:1a:c5:88"`
- `change_context.score = 30`
- `change_context.change_refs = ["crscore:30", "craction:131072", "crlevel:high"]`

之后已立刻恢复：

- `RULE_DENY_THRESHOLD=200`
- `RULE_BYTES_THRESHOLD=100000000`
- `RULE_ALERT_COOLDOWN_SEC=300`

### 5.3 第三轮受控验证：AIOps 双路径 suggestion 已在真实流量下生效

在完成 `alert-scope + cluster-scope` 双路径代码发布后，继续使用真实 FortiGate 流量做短时验证：

- 首次双路径发布：
  - `netops-core-app:v20260322-aiopsdual-ca14d7e`
- 随后修复 ClickHouse 上下文查询兼容性后再次发布：
  - `netops-core-app:v20260322-aiopsdualfix-3a76ec4`

为保证当前时间 alert 足够快地产生，本轮仍短时使用：

- `RULE_DENY_THRESHOLD=5`
- `RULE_ALERT_COOLDOWN_SEC=60`

真实结果：

- 在 `2026-03-22 21:51 UTC` 窗口内，`suggestions` 已从历史时间追到当前时间
- 最新 suggestion 明确带有：
  - `suggestion_scope="alert"`
  - `cluster_size=1`
  - 当前 alert 的 `service / src_device_key`
- 样本包括：
  - `2026-03-22T21:51:17.539662+00:00`, `service=udp/5351`, `src_device_key=50:9a:4c:87:29:b3`
  - `2026-03-22T21:51:37.889506+00:00`, `service=Dahua SDK`, `src_device_key=d4:43:0e:1a:c5:88`
  - `2026-03-22T21:55:28.139648+00:00`, `service=udp/48689`, `src_device_key=78:66:9d:a3:4f:51`

在第二次修复发布后，再次检查：

- `kubectl logs -n netops-core deploy/core-aiops-agent --since=3m`
- 已不再出现先前的 ClickHouse `TypeError`

诚实说明：

- 这次短时实时窗口已经证明 `alert-scope` suggestion 生效
- 但没有自然观察到新的 `cluster-scope` suggestion，因为这段时间内没有形成满足 `min=3 within 600s` 的同 key 告警簇

## 6. 当前剩余问题

1. `core.benchmark.live_runtime_check` 的 `recent_alert_presence` 在 replay / 实验窗口下仍可能低估字段厚度，后续可以再优化为更偏“最新写入”的取样口径
2. 当前已验证 `alert-scope` 实时 suggestion，但 `cluster-scope` 在短时自然流量下尚未再次观测到
3. 当前 confidence 仍是稳定启发式，不应当被解释成已校准 RCA 置信度
4. 最小 CI 仍未补齐，当前发布流程仍依赖人工执行脚本

## 7. 接下来最合理的动作

1. 补一个更准确的 runtime 验证脚本或修正 `live_runtime_check` 的 alert 采样口径
2. 在自然阈值下继续观察：
   - raw 是否持续保持当前时间
   - core alert 是否按自然阈值触发
   - cluster-scope suggestion 是否自然出现
3. 再考虑最小 CI：
   - `pytest`
   - `compileall`
   - `docker build` smoke check
