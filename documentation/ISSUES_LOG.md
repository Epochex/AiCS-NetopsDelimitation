# NetOps Issues Log

本文件用于持续记录项目运行过程中遇到的问题、原因分析、处理过程与回归验证结果。

## 记录规范
- 日期：使用绝对日期（YYYY-MM-DD）。
- 状态：`Open` / `Mitigated` / `Resolved`。
- 必填项：现象、影响范围、根因、处理过程、验证结果、后续动作。

---

## Issue-2026-03-22-001：edge replay/backfill 导致 raw 长期停留在历史时间，且 core 需要受控验证才能证明 enrichment 生效
- 日期：2026-03-22
- 状态：Resolved
- 影响范围：`edge/fortigate-ingest`、`edge-forwarder`、`core-correlator`、`core-aiops-agent` 的联调判断。

### 现象
- `suggestions` 文件持续以当前处理时间写入，但 `raw/alerts` payload 时间长期停留在历史日期。
- `live_runtime_check` 一度显示：
  - `latest_raw_payload_age_sec` 很大
  - `latest_alert_event_age_sec` 很大
- edge 侧 parsed 文件如 `events-20260322-18.jsonl` 的文件名和 `ingest_ts` 在 2026-03-22，但实际 `event_ts` 主要仍在 2026-03-17/18。
- edge parser 修复已经把 `crscore/craction/crlevel` 和 `device_profile` 送入 raw，但默认阈值下 correlator 没有产出新 alert，导致不能直接证明 enriched alert 是否真正写出。

### 根因
1. edge parser 主循环先处理 rotated 文件，再处理 active 文件。
2. `fortigate.log-20260319-000017.gz` 与 `fortigate.log-20260321-000026` 没有被记入 checkpoint `completed`，因此 parser 一直追旧 backlog。
3. `fortigate-ingest` 的 active offset 远落后于当前 `fortigate.log` 文件末尾，即使 rotated backlog 结束，也仍会继续回放当前 active 文件的历史部分。
4. core 默认线上阈值较高：
   - `RULE_DENY_THRESHOLD=200`
   - `RULE_BYTES_THRESHOLD=100000000`
   - `RULE_ALERT_COOLDOWN_SEC=300`
   在实时流量下短窗口内自然不一定触发新 alert。

### 处理过程
1. 先完成 core 运行态对齐
- 通过 `core/automatic_scripts/release_core_app.sh` 发布：
  - `netops-core-app:v20260322-corealign-54f5ecf`
- 确认以下 deployment 已切到新镜像：
  - `core-correlator`
  - `core-alerts-sink`
  - `core-alerts-store`
  - `core-aiops-agent`
- 确认 `core-aiops-agent` 容器内存在：
  - `service.py`
  - `app_config.py`
  - `evidence_bundle.py`
  - `providers.py`

2. 做第一轮受控阈值验证
- 临时把 `RULE_DENY_THRESHOLD` 从 `200` 下调到 `30`
- 证明 replay 阶段的 rich raw 可以产出 enriched alert
- 结束后恢复回 `200`

3. 定点重置 edge backlog
- `kubectl scale -n edge deployment/fortigate-ingest --replicas=0`
- 创建临时 helper pod，挂载 `/data/fortigate-runtime`
- 备份 checkpoint：
  - `/data/fortigate-runtime/work/checkpoint.pre-realtime-reset-20260322T200250Z.json`
- 将以下文件补记为 `completed`：
  - `fortigate.log-20260319-000017.gz`
  - `fortigate.log-20260321-000026`
- 把 active inode / offset 直接推到当时 `fortigate.log` 文件末尾
- 再将 `fortigate-ingest` 拉回 `1`

4. 做第二轮“实时 raw”受控验证
- backlog 重置后确认：
  - 最新 parsed 的 `source.path=/data/fortigate-runtime/input/fortigate.log`
  - Kafka raw `payload_ts` 已接近当前时间
- 为了得到“当前时间 alert”样本，短时把 `RULE_DENY_THRESHOLD` 下调到 `5`
- 成功产生当前时间 alert：
  - `alert_id=d4a9761262c5c8781e6dc1e6477a97efe8f6cc43`
  - `alert_ts=2026-03-22T20:07:59+00:00`
  - `source_event_id=578912762fac6b71cb9553bec3c7af45`
- 该 alert 明确包含：
  - `topology_context`
  - `device_profile`
  - `change_context`
- 验证后再次恢复：
  - `RULE_DENY_THRESHOLD=200`

### 验证结果
1. edge 已回到实时态
- `fortigate-ingest` heartbeat：
  - `lag_bytes=0` 或接近 `0`
  - `last_event_ts_seen` 已回到当前时间
- 最新 parsed 样本：
  - `source.path=/data/fortigate-runtime/input/fortigate.log`
  - `event_ts` 与 `ingest_ts` 接近当前时间

2. raw 已回到实时
- `python3 -m core.benchmark.live_runtime_check` 在 2026-03-22 20:05 UTC 显示：
  - `latest_raw_payload_age_sec=8`

3. enriched alert 路径已被两次证明
- replay 阶段和 realtime 阶段都已得到包含：
  - `topology_context`
  - `device_profile`
  - `change_context`
  的新 alert

4. realtime 阶段已验证 `change_context` 真正接到了 edge 新字段
- 当前时间 alert 中：
  - `change_context.score=30`
  - `change_context.change_refs=["crscore:30","craction:131072","crlevel:high"]`

5. 最终 live runtime 已重新收敛到当前时间窗口
- `python3 -m core.benchmark.live_runtime_check` 在 2026-03-22 20:11 UTC 显示：
  - `history_backlog_suspected=false`
  - `latest_raw_payload_age_sec=5`
  - `latest_alert_event_age_sec=206`
  - `alerts` 最新文件已变成 `alerts-20260322-20.jsonl`
- 最近 1000 条 alert 的字段出现率也已不再为 0：
  - `topology_context=0.005`
  - `device_profile=0.005`
  - `change_context=0.003`

### 仍需注意
- `live_runtime_check` 当前的 `recent_alert_presence` 按“最新 alert_ts 文件”取样，在 replay / 实验阈值窗口下可能低估新字段出现率。
- `suggestions` 当前仍主要反映较早的 cluster 触发结果；这不等于 core enrichment 失效，而是 AIOps 聚类门槛尚未在当前实时流量下自然满足。

### 后续动作
1. 修正 `live_runtime_check` 的 alert 取样口径，使其更接近“最新写入”而不是“最新 alert_ts 文件名”。
2. 继续观察：
   - raw 是否持续保持当前时间
   - alerts 是否在自然阈值下持续产生
   - aiops suggestions 是否在自然阈值下持续保持当前时间

---

## Issue-2026-03-22-002：AIOps suggestion 只在 cluster 触发时产出，导致实时 alert 已恢复但 suggestion 仍停留在历史时间
- 日期：2026-03-22
- 状态：Resolved
- 影响范围：`core-aiops-agent` suggestion 产出链路与实时验证结论。

### 现象
- `raw` 与 `alerts` 已经回到当前时间窗口。
- `core-aiops-agent` 对 `netops.alerts.v1` 的 consumer lag 为 `0`。
- 但 `netops.aiops.suggestions.v1` 仍停留在历史 `2026-03-22 19:39 UTC`，没有新的 current-time suggestion。

### 根因
1. `core/aiops_agent/service.py` 当时只在 `aggregator.observe(alert)` 返回 trigger 时才继续走 evidence/request/provider/publish。
2. 这意味着当前实现本质上是“cluster-only suggestion”，而不是“每条 alert 都有基础 suggestion”。
3. 后续真实验证又暴露一个次级问题：
   - `core/aiops_agent/context_lookup.py` 假定 ClickHouse `result.first_item` 一定可直接 `int()`
   - 但运行时客户端会返回 `dict` 形态，导致日志出现 `TypeError`
   - 该错误不会阻塞 suggestion，因为异常会被兜底成 `0`，但会污染运行日志并掩盖真正状态

### 处理过程
1. 实现双路径 suggestion
- `build_alert_evidence_bundle()`
- `build_alert_inference_request()`
- `build_alert_pipeline_suggestion()`
- `TemplateProvider` 根据 `suggestion_scope` 分别处理 `alert` 与 `cluster`
- `service.py` 调整为：
  - 每条合格 alert 先发 `alert-scope` suggestion
  - 若聚合器命中，再额外发 `cluster-scope` suggestion
- stats 日志调整为每轮循环都可按间隔输出，不再只在旧 cluster 路径上可见

2. 增加回归测试
- `tests/core/test_aiops_agent.py`
- 当前基线：
  - `python3 -m pytest -q tests/core` -> `31 passed`
  - `python3 -m compileall -q core` -> 通过

3. 修复 ClickHouse context 兼容性
- `core/aiops_agent/context_lookup.py`
- 兼容 `result.first_item` 为 `dict` 的运行时返回

4. 两次发布与受控验证
- 首次双路径发布：
  - `netops-core-app:v20260322-aiopsdual-ca14d7e`
- 修复 ClickHouse context 后再次发布：
  - `netops-core-app:v20260322-aiopsdualfix-3a76ec4`
- 验证窗口短时使用：
  - `RULE_DENY_THRESHOLD=5`
  - `RULE_ALERT_COOLDOWN_SEC=60`
- 验证后已恢复：
  - `RULE_DENY_THRESHOLD=200`
  - `RULE_ALERT_COOLDOWN_SEC=300`

### 验证结果
1. 双路径里的新增关键路径已经在真实流量下命中
- `suggestions` 已从历史时间追到当前时间
- 最新 suggestion 明确带有：
  - `suggestion_scope=\"alert\"`
  - `cluster_size=1`
  - 当前 alert 对应的 `service / src_device_key`

2. 当前时间样本
- `2026-03-22T21:51:17.539662+00:00`
  - `service=udp/5351`
  - `src_device_key=50:9a:4c:87:29:b3`
- `2026-03-22T21:51:37.889506+00:00`
  - `service=Dahua SDK`
  - `src_device_key=d4:43:0e:1a:c5:88`
- `2026-03-22T21:55:28.139648+00:00`
  - `service=udp/48689`
  - `src_device_key=78:66:9d:a3:4f:51`

3. 最终 live runtime 收口
- `python3 -m core.benchmark.live_runtime_check`
  - `history_backlog_suspected=false`
  - `latest_raw_payload_age_sec=4`
  - `latest_alert_event_age_sec=35`
  - `suggestions` 最新 payload 时间已推进到 `2026-03-22T21:55:28.139648+00:00`

4. ClickHouse 次级问题也已闭环
- `kubectl logs -n netops-core deploy/core-aiops-agent --since=3m`
- 已不再出现先前的 `TypeError: int() argument must be ... not 'dict'`

### 仍需注意
- 这轮短时实时窗口只验证了新增的 `alert-scope` suggestion 路径。
- `cluster-scope` 路径仍保留有效，但在这次自然流量窗口里没有再次观测到新的同 key `3/600s` cluster。

### 后续动作
1. 在自然阈值下继续观察 cluster-scope 是否自然出现。
2. 继续优化 `live_runtime_check` 的采样口径。
3. 再考虑最小 CI（`pytest` / `compileall` / `docker build` smoke）。

---

## Issue-2026-03-08-001：warning 事件过多（core correlator）
- 日期：2026-03-08
- 状态：Mitigated
- 影响范围：`core-correlator` warning 告警密度过高，影响“最小闭环”稳定性评估。

### 现象
- `core-correlator` 持续输出 `deny_burst_v1` warning。
- 近 24h 告警统计中 `deny_burst_v1` 远高于其他规则，`bytes_spike_v1` 基本不触发。

### 初步假设
- 可能是 edge 噪声流量过多（本地广播/发现类 deny）进入 core。
- 也可能是 core 阈值偏敏感。

### 证据与分析
1. ingest 解析质量正常（排除“解析失败导致异常放大”）
- 2026-03-07 全日离线统计：`2,007,390` 条事件，`parse_status=ok` 全量通过。
- required 字段缺失计数为 0（`event_id/event_ts/type/subtype`）。

2. deny 噪声占比高（主要是 local/broadcast）
- 2026-03-07 deny 占比约 `72.45%`。
- Top 组合集中在：
  - `traffic/local + udp/5353 -> ff02::fb`
  - `traffic/local + udp/48689 -> 255.255.255.255`
  - `traffic/local + udp/5355 -> ff02::1:3`
  - `traffic/forward + udp/3702 -> 192.168.2.108`

3. 线上 edge-forwarder 配置漂移（核心根因）
- 实际运行配置（修复前）为：
  - image：`netops-core-app:0.1`
  - command：`python -m core.edge_forwarder.main`
  - 未包含 `FORWARDER_FILTER_DROP_LOCAL_DENY`、`FORWARDER_FILTER_DROP_BROADCAST_MDNS_NBNS`
- 结果：edge 侧抑噪过滤未生效，噪声流量直接进入 core。

4. 触发配置漂移的流程缺陷
- `core/automatic_scripts/release_core_app.sh` 存在“更新 edge-forwarder 镜像”的逻辑，导致 core 发布误改 edge 组件。

### 处理过程
1. 恢复 edge-forwarder 正确部署
- 应用：`edge/edge_forwarder/deployments/30-edge-forwarder.yaml`
- 目标配置：
  - image：`netops-edge-forwarder:0.1`
  - command：`python -m edge.edge_forwarder.main`
  - env：开启 `FORWARDER_FILTER_DROP_LOCAL_DENY=true`、`FORWARDER_FILTER_DROP_BROADCAST_MDNS_NBNS=true`

2. 解决镜像拉取失败
- 新 Pod 曾报 `ErrImagePull`（节点本地缺少 `netops-edge-forwarder:0.1`）。
- 在节点本地执行：
  - `docker build -t netops-edge-forwarder:0.1 -f edge/edge_forwarder/docker/Dockerfile.app .`
  - `docker save ...` + `k3s ctr images import ...`
- 重新滚动后，Pod 正常启动。

3. 修复发布脚本，避免再次污染 edge
- 修改 `core/automatic_scripts/release_core_app.sh`：仅发布 core（`core-correlator`、`core-alerts-sink`）。
- 修改 `core/automatic_scripts/README.md`：删除错误示例与 edge 更新描述。

### 验证结果
- edge-forwarder 新日志确认过滤生效：
  - `forwarder started ... drop_local_deny=True drop_broadcast_mdns_nbns=True`
  - `scan complete ... dropped_local_deny=xx` 持续增长。
- core 告警密度下降：
  - 近 10 分钟 `deny_burst_v1`：0
  - 近 5 分钟 `deny_burst_v1`：0

### 后续动作
- 固定 30-60 分钟观察窗口，持续记录：
  - `drop_*`、`alerts_emitted`、warning 触发率。
- 若 residual warning 仍偏高，再做阈值校准实验：
  - `RULE_DENY_THRESHOLD` / `RULE_ALERT_COOLDOWN_SEC` / `RULE_BYTES_THRESHOLD`。
- 强制流程约束：
  - core 与 edge 发布脚本分离，不允许交叉更新 deployment。

---

## 待补充
- 后续新增问题请按同一模板追加到本文件。

---

## Issue-2026-03-08-002：core-alerts-sink CrashLoop（镜像版本与代码不一致）
- 日期：2026-03-08
- 状态：Resolved
- 影响范围：`core-alerts-sink` 无法启动，告警持久化链路中断。

### 现象
- Pod 持续 `CrashLoopBackOff`。
- 日志报错：`ModuleNotFoundError: No module named 'core.alerts_sink'`。

### 根因
1. Deployment 默认镜像仍是 `netops-core-app:0.1`。
2. `imagePullPolicy: IfNotPresent` 导致节点复用本地旧镜像，不会自动拉取/替换。
3. 旧镜像不包含 `core.alerts_sink`，与当前仓库代码不一致。

### 处理过程
1. 使用 `core/automatic_scripts/release_core_app.sh` 发布新 tag 镜像（示例：`v20260308-corefix`）。
2. 脚本更新 `core-correlator`、`core-alerts-sink` deployment 并等待 rollout。
3. 脚本新增发布后导入检查：
   - `python -c "import core.correlator.main"`
   - `python -c "import core.alerts_sink.main"`

### 验证结果
- `core-alerts-sink` 恢复 `1/1 Running`。
- 启动日志正常连接 Kafka 并加入 consumer group。

### 经验教训 / 防回归措施
- 禁止长期复用静态 tag（如 `0.1`），必须使用不可变发布 tag（建议包含日期 + git short sha）。
- 发布完成后必须做“运行时模块导入检查”，不能只看 rollout ready。
- core 与 edge 发版链路必须保持分离，避免交叉污染镜像/deployment。
