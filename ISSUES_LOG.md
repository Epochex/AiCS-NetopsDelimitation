# NetOps Issues Log

本文件用于持续记录项目运行过程中遇到的问题、原因分析、处理过程与回归验证结果。

## 记录规范
- 日期：使用绝对日期（YYYY-MM-DD）。
- 状态：`Open` / `Mitigated` / `Resolved`。
- 必填项：现象、影响范围、根因、处理过程、验证结果、后续动作。

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
