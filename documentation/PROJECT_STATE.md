# NetOps Project State

本文件给“新会话 AI / 新协作者 / 未来自己”提供一个稳定、可直接接手的项目状态入口。

- 最后更新：2026-03-22 20:10 UTC
- 当前开发分支：`core-dev`
- 配套问题日志：[ISSUES_LOG.md](./ISSUES_LOG.md)
- 本轮详细过程记录：[CONTROLLED_VALIDATION_20260322.md](./CONTROLLED_VALIDATION_20260322.md)

## 1. 当前真实目标

当前项目的主目标不是做一个“会聊天的 AIOps demo”，而是把这条真实 NetOps / NSM 链路做成稳定、可验证、可扩展的最小闭环：

1. `FortiGate -> edge ingest -> Kafka raw`
2. `core correlator -> alerts topic`
3. `alerts -> JSONL / ClickHouse`
4. `AIOps slow path -> suggestions`

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

- 核心验证脚本已落地：
  - `core/benchmark/aiops_replay_validation.py`
  - `core/benchmark/runtime_timestamp_audit.py`
  - `core/benchmark/live_runtime_check.py`

- core alert enrichment 已接进规则产物：
  - `topology_context`
  - `device_profile`
  - `change_context`

### 3.2 当前本地分支头部

- `54f5ecf` `docs: update project state and issues log`
- `292b1eb` `docs: update project state and issues log`
- `f42c761` `Prepare core alert enrichment and live runtime check`
- `3e9d187` `edge: preserve fortigate cr fields and device profile`

注意：

- 当前工作区里 `documentation/` 目录仍是未跟踪状态，需要后续手动 `git add documentation`

## 4. 当前运行态事实

### 4.1 core 运行态已与当前代码对齐

2026-03-22 已执行本地发布：

- 发布脚本：`core/automatic_scripts/release_core_app.sh`
- 运行镜像：`netops-core-app:v20260322-corealign-54f5ecf`

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

`python3 -m core.benchmark.live_runtime_check` 在 2026-03-22 20:05 UTC 的关键结果：

- `latest_raw_payload_age_sec = 8`
- `latest_alert_event_age_sec` 仍然很大
- `history_backlog_suspected = true`

这不再表示 raw 仍旧积压，而是说明：

- raw 已回到实时
- alert 当前是否“最新”，还取决于规则阈值是否触发
- `live_runtime_check` 的 `recent_alert_presence` 仍按“最新 alert_ts 文件”采样，在 replay / 人工阈值验证场景下会低估新字段出现率

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

## 6. 当前剩余问题

1. `core.benchmark.live_runtime_check` 的 `recent_alert_presence` 采样口径在 replay / 实验窗口下会误导，需要后续改成更贴近“最新写入”的视角
2. `netops.aiops.suggestions.v1` 当前仍主要是历史 suggestion；新实时 alert 未必立即形成 suggestion，因为 cluster 条件本身更严格
3. 当前 `documentation/` 仍未纳入 git 跟踪
4. 本地分支还比 `origin/core-dev` 超前 3 个 commit，后续需要整理和提交

## 7. 接下来最合理的动作

1. 把 `documentation/` 整体 `git add` 并提交
2. 补一个更准确的 runtime 验证脚本或修正 `live_runtime_check` 的 alert 采样口径
3. 基于当前实时数据继续观察：
   - raw 是否持续保持当前时间
   - core alert 是否按自然阈值触发
   - aiops suggestion 是否恢复到当前时间
4. 再考虑最小 CI：
   - `pytest`
   - `compileall`
   - `docker build` smoke check
