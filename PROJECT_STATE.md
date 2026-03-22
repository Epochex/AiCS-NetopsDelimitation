# NetOps Project State

本文件用于给“新会话 AI / 新协作者 / 未来自己”提供一个稳定的项目总览入口。

- 最后更新：2026-03-22
- 主分支基线：`main`
- 当前开发分支：`core-dev`
- 配套问题日志：[ISSUES_LOG.md](/data/Netops-causality-remediation/ISSUES_LOG.md)

## 1. 项目目标

本项目当前的真实目标不是“做一个聊天式 AIOps demo”，而是做一条可落地的 NetOps / NSM 最小闭环：

1. `FortiGate -> edge ingest -> Kafka raw`
2. `core correlator -> alerts topic`
3. `alerts -> JSONL / ClickHouse`
4. `AIOps slow path -> suggestions`

当前阶段的重点是：

- 保证 end-edge-core 链路真实可观测
- 保证告警不是 mock，而是来自真实 FortiGate 数据
- 在此基础上把 AIOps 的证据链慢慢“做厚”

## 2. 当前架构

### 2.1 运行链路

1. `FortiGate`
   - 通过 syslog 把原始日志发往 edge 节点 `192.168.1.23`

2. `edge/fortigate-ingest`
   - 读取 `/data/fortigate-runtime/input/fortigate.log*`
   - 解析 FortiGate syslog
   - 输出到 `/data/fortigate-runtime/output/parsed/events-*.jsonl`

3. `edge-forwarder`
   - 读取 parsed JSONL
   - 转发到 Kafka `netops.facts.raw.v1`

4. `core-correlator`
   - 消费 raw topic
   - 运行质量门和规则
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
   - 文件名按“当前处理时间”分桶

### 2.2 组件职责

- Kafka：实时事件总线
- JSONL：可直接审计、可离线回放的文件证据层
- ClickHouse：alert 历史分析库，不是 raw 主存储
- AIOps Agent：慢路径，不应承担实时主判定职责

## 3. 当前代码状态

### 3.1 已在当前仓库 `core-dev` 落地的内容

- AIOps slow path 模块化骨架已落地：
  - `core/aiops_agent/app_config.py`
  - `core/aiops_agent/service.py`
  - `core/aiops_agent/evidence_bundle.py`
  - `core/aiops_agent/inference_queue.py`
  - `core/aiops_agent/inference_schema.py`
  - `core/aiops_agent/inference_worker.py`
  - `core/aiops_agent/providers.py`
  - `core/aiops_agent/suggestion_engine.py`
- replay 验证脚本已落地：
  - `core/benchmark/aiops_replay_validation.py`
- runtime 时间语义审计脚本已落地：
  - `core/benchmark/runtime_timestamp_audit.py`
- live runtime 检查脚本已落地：
  - `core/benchmark/live_runtime_check.py`
- core alert enrichment 已接到规则产物：
  - `topology_context`
  - `device_profile`
  - `change_context`

### 3.2 当前仓库的关键 commit

- `b12c30b` `Document core timestamp audit findings`
- `f026a6b` `Disable lossy edge forwarder filters`
- `c5a5e3f` `Prepare core alert enrichment and live runtime check`

注意：

- `c5a5e3f` 当前仍只在本地 `core-dev`，尚未 push 到 `origin/core-dev`

## 4. 当前运行态事实

### 4.1 core 运行态与仓库代码不一致

当前 `netops-core` namespace 运行中的 4 个 deployment：

- `core-correlator`
- `core-alerts-sink`
- `core-alerts-store`
- `core-aiops-agent`

都在跑镜像：

- `netops-core-app:v20260308-aiopsdb`

已经确认：

- 运行中的 `core-aiops-agent` 容器内只有一个老版 `main.py`
- 不包含当前仓库里的：
  - `service.py`
  - `app_config.py`
  - `evidence_bundle.py`
  - `providers.py`
- 因此线上运行态还不是当前仓库这版 AIOps pipeline

### 4.2 edge 运行态发现

来自 192.168.1.23 同 workspace 的定点调查结果：

1. `edge-forwarder` 已切换到无损转发态
   - `FORWARDER_FILTER_DROP_LOCAL_DENY=false`
   - `FORWARDER_FILTER_DROP_BROADCAST_MDNS_NBNS=false`
   - rollout 后连续扫描日志为 `dropped=0`
   - Kafka 尾部已确认 `traffic/local/deny` 事件正常转发

2. edge 当前仍处于 replay/backfill 态
   - `events-20260322-18.jsonl` 的 `ingest_ts` 在 2026-03-22
   - 但 `event_ts` 主要在 2026-03-18
   - `source.path` 主要来自旧 rotated 文件：
     - `fortigate.log-20260319-000017.gz`

3. replay/backfill 的直接原因
   - ingest 主循环先处理 rotated，再处理 active
   - `.gz` rotated 文件未被记入 completed checkpoint
   - 因而 edge 仍在追旧 gzip backlog

4. 字段保真结论
   - forwarder 没发现字段级裁剪
   - 原字段丢失点在 edge parser
   - 23 节点上已做 edge-only 修复：
     - 保留 `crscore/craction/crlevel`
     - 合成 `device_profile`

重要说明：

- 上述 parser 修复目前是 23 节点运行态结果
- 本仓库当前工作区 **尚未确认已合入这部分 edge parser 代码**
- 如果要长期保存，必须把 23 节点的 parser 改动合并回仓库

## 5. 当前验证结论

### 5.1 core replay 验证

真实 alert 历史 replay 结果：

- 扫描 `337` 个小时文件
- 总计 `44,733` 条 alert
- 使用旧参数 `300s/3/300s` 时 cluster trigger 为 `0`
- 调整到 `600s/3/300s` 后 pipeline 输出 `12,751`

结论：

- 旧的 cluster window 对现网节奏无效
- `AIOPS_CLUSTER_WINDOW_SEC=600` 更符合当前真实数据

### 5.2 runtime 时间语义验证

报告路径：

- `/data/netops-runtime/observability/aiops-replay-validation-20260322.json`
- `/data/netops-runtime/observability/aiops-replay-validation-20260322-window600.json`
- `/data/netops-runtime/observability/live-runtime-check-20260322-185410.json`

当前 live runtime 关键事实：

- Kafka `raw` 末尾 payload 时间约在 `2026-03-16/17`
- Kafka `alerts` 末尾 payload 时间约在 `2026-03-16`
- Kafka `suggestions` 末尾 payload 时间在 `2026-03-22`
- `history_backlog_suspected=true`

这说明：

- 系统当前确实在处理旧事件流
- 不是 `alerts-sink` 坏了
- 而是 edge/core 一直在消费历史时间戳数据

### 5.3 最近 alert 的字段厚度

最近 1000 条 alert 的出现率：

- `service = 1.0`
- `src_device_key = 1.0`
- `topology_context = 0.0`
- `device_profile = 0.0`
- `change_context = 0.0`

含义：

- core 规则产物当前还没有接到这些厚证据
- 即使 repo 已准备好 enrichment，也要等：
  1. edge 真把字段送来
  2. core 用新镜像重新部署

## 6. 当前最重要的问题

1. edge 仍在 replay/backfill，系统不是真实时态
2. 运行中的 core 镜像不是当前仓库版本
3. 23 节点上的 parser 修复还没有明确并回当前仓库
4. 运行中的 `core-aiops-agent` 是旧版逻辑，并持续报 ClickHouse context 查询错误

详细问题请看：

- [ISSUES_LOG.md](/data/Netops-causality-remediation/ISSUES_LOG.md)

## 7. 推荐的下一步顺序

### 7.1 不建议做的事

- 不要“把所有运行中的东西全部清空”
- 不要先 PR 到 `main`
- 不要在 core 和 edge 都还没对齐时就开始做前端结论展示

### 7.2 建议做的事

1. 先把 23 节点上的 edge parser 修复合并回仓库
2. 再决定是否做 edge backlog 定点重置
   - 只允许定点清理 checkpoint / parsed backlog
   - 必须先做证据留档
3. 然后在 core 节点本地直接执行 core 镜像对齐部署
4. 部署完成后立刻运行 live runtime 检查脚本

## 8. 部署事实

### 8.1 没有 CI/CD 时，是否必须 push 才能部署

不是。

当前项目没有 CI/CD 的前提下：

- 如果你就在能访问 `docker + kubectl + k3s` 的本地 core 节点上
- 那么可以直接本地 build / save / import / rollout
- **不需要先 push 才能部署**

push 的价值是：

- 让其他机器同步你的代码
- 让远端保存一份分支历史
- 方便跨机器协作

### 8.2 本地 core 部署入口

使用：

- `./core/automatic_scripts/release_core_app.sh`

它会：

1. `docker build`
2. `docker save`
3. `k3s ctr images import`
4. `kubectl set image`
5. `kubectl rollout status`
6. 在运行中 pod 里做模块导入检查

因此，core 对齐部署完全可以在本地直接完成。

## 9. 推荐诊断命令

### 9.1 core 运行态

```bash
kubectl get deploy -n netops-core -o wide
kubectl get pods -n netops-core -o wide
kubectl logs -n netops-core deploy/core-aiops-agent --tail=120
python3 -m core.benchmark.live_runtime_check
```

### 9.2 edge 运行态

```bash
kubectl get deploy,pod -n edge -o wide
kubectl logs -n edge deploy/edge-forwarder --tail=120
kubectl logs -n edge deploy/fortigate-ingest --tail=120
cat /data/fortigate-runtime/work/checkpoint.json
cat /data/netops-runtime/forwarder/checkpoint.json
```

## 10. 给新会话 AI 的最短提示

如果你是一个没有上下文的新会话 AI，请先读：

1. [PROJECT_STATE.md](/data/Netops-causality-remediation/PROJECT_STATE.md)
2. [ISSUES_LOG.md](/data/Netops-causality-remediation/ISSUES_LOG.md)
3. [core/README.md](/data/Netops-causality-remediation/core/README.md)
4. [edge/README.md](/data/Netops-causality-remediation/edge/README.md)

然后先确认三件事再动手：

1. edge 当前是否仍在 replay/backfill
2. 运行中的 core 镜像是否已经对齐到当前 `core-dev`
3. 23 节点上的 edge parser 修复是否已经合并回仓库
