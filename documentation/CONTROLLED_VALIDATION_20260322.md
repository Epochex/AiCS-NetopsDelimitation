# Controlled Validation 2026-03-22

本文件记录 2026-03-22 这轮“core 对齐部署 + edge backlog 定点重置 + 两次受控阈值验证”的完整过程，供新会话 AI 或后续排障直接接手。

## 1. 目标

本轮验证要回答 3 个问题：

1. 当前仓库里的 core 代码是否真的已经跑在 `netops-core` 里
2. edge replay/backfill 是否能被最短路径切回实时态
3. edge parser 新补出的 `crscore/craction/crlevel` 与 `device_profile`，是否真的能进入 core enriched alert

## 2. 基线事实

### 2.1 core 对齐部署前后的关键事实

- 使用脚本：
  - `./core/automatic_scripts/release_core_app.sh v20260322-corealign-$(git rev-parse --short HEAD)`
- 发布结果：
  - `netops-core-app:v20260322-corealign-54f5ecf`
- 覆盖 deployment：
  - `core-correlator`
  - `core-alerts-sink`
  - `core-alerts-store`
  - `core-aiops-agent`

部署后确认：

- `core-aiops-agent` 容器内已有：
  - `app_config.py`
  - `service.py`
  - `evidence_bundle.py`
  - `providers.py`
- 旧版 `ClickHouse context TypeError` 消失

### 2.2 edge replay/backfill 的实锤

重置前明确确认：

- `events-20260322-18.jsonl` 的 `ingest_ts` 在 2026-03-22
- 但其 `event_ts` 主要在 2026-03-17 / 2026-03-18
- `source.path` 指向旧 rotated 文件：
  - `/data/fortigate-runtime/input/fortigate.log-20260319-000017.gz`

checkpoint 关键事实：

- `fortigate.log-20260319-000017.gz` 未在 `completed` 中
- `fortigate.log-20260321-000026` 也未在 `completed` 中
- `active.offset` 远小于当前 active `fortigate.log` 文件大小

## 3. 第一轮受控阈值验证

### 3.1 原因

默认线上阈值为：

- `RULE_DENY_THRESHOLD=200`
- `RULE_BYTES_THRESHOLD=100000000`
- `RULE_ALERT_COOLDOWN_SEC=300`

在当时 replay 到的流量窗口里，这个阈值太高，短时间没有新 alert，无法直接证明 enriched alert 路径是否真的生效。

### 3.2 操作

- 记录 alert topic 基线 offset
- 临时将：
  - `RULE_DENY_THRESHOLD=30`
- rollout `core-correlator`
- 观察新 alert
- 验证完成后恢复为 `200`

### 3.3 结果

成功得到新 alert，并确认 alert 已包含：

- `topology_context`
- `device_profile`
- `change_context`

说明：

- core enrichment 代码路径是通的
- 问题不在“代码没部署”，而在 replay 与默认阈值的组合让新 alert 难以自然出现

## 4. Edge Backlog 定点重置

### 4.1 原则

本轮没有粗暴删除历史文件，而是只修正 parser checkpoint，使其从“继续回放 backlog”切到“从现在开始实时 tail”。

### 4.2 实际步骤

1. 停止 parser
- `kubectl scale -n edge deployment/fortigate-ingest --replicas=0`

2. 创建临时 helper pod
- 挂载同一 hostPath：
  - `/data/fortigate-runtime`

3. 备份原 checkpoint
- 备份文件：
  - `/data/fortigate-runtime/work/checkpoint.pre-realtime-reset-20260322T200250Z.json`

4. 修改 checkpoint
- 新增 `completed`：
  - `/data/fortigate-runtime/input/fortigate.log-20260319-000017.gz`
  - `/data/fortigate-runtime/input/fortigate.log-20260321-000026`
- 设置 active：
  - `inode=6161315`
  - `offset=729152332`
  - `last_event_ts_seen=null`

5. 删除 helper pod，恢复 parser
- `kubectl scale -n edge deployment/fortigate-ingest --replicas=1`

### 4.3 重置后直接证据

`fortigate-ingest` heartbeat：

- `2026-03-22T20:04:35Z`
  - `offset=729267310`
  - `size=729267310`
  - `lag_bytes=0`
  - `last_event_ts_seen=2026-03-22T21:04:34+01:00`

最新 parsed 样本：

- `source.path=/data/fortigate-runtime/input/fortigate.log`
- `event_ts=2026-03-22T21:04:47+01:00`
- `ingest_ts=2026-03-22T20:04:49+00:00`

这说明：

- parser 已不再追旧 rotated backlog
- edge 已重新进入实时 tail

## 5. 第二轮受控阈值验证（实时 raw）

### 5.1 先确认实时 raw 已存在 rich 字段

在当前时间窗口，Kafka `netops.facts.raw.v1` 已直接看到：

- `source_path=/data/fortigate-runtime/input/fortigate.log`
- `event_ts` 接近当前时间
- 存在带：
  - `crscore=30`
  - `device_profile={"srcmac":"d4:43:0e:1a:c5:88","src_device_key":"d4:43:0e:1a:c5:88"}`
  的实时 raw

### 5.2 为什么 `30` 还不够

实时 raw 的短窗口里，`deny` 峰值虽然能到 `38/60s`，但 rollout 重启后窗口重建，需要更保守地确保立刻能触发当前时间 alert。

因此第二轮临时使用：

- `RULE_DENY_THRESHOLD=5`

### 5.3 结果样本

成功得到当前时间 alert：

- `alert_id=d4a9761262c5c8781e6dc1e6477a97efe8f6cc43`
- `alert_ts=2026-03-22T20:07:59+00:00`
- `source_event_id=578912762fac6b71cb9553bec3c7af45`

关键字段：

- `topology_context`
  - `service="Dahua SDK"`
  - `srcip="192.168.1.20"`
  - `dstip="192.168.30.35"`
  - `srcintf="fortilink"`
  - `dstintf="LACP"`

- `device_profile`
  - `srcmac="d4:43:0e:1a:c5:88"`
  - `src_device_key="d4:43:0e:1a:c5:88"`
  - `known_services=["Dahua SDK"]`

- `change_context`
  - `suspected_change=true`
  - `score=30`
  - `action="131072"`
  - `level="high"`
  - `change_refs=["crscore:30","craction:131072","crlevel:high"]`

之后已立即恢复线上值：

- `RULE_DENY_THRESHOLD=200`

## 6. 当前结论

这轮验证已经闭环证明了 3 件事：

1. core 新代码已经真正跑在集群里
2. edge backlog 已被最短路径切回实时态
3. edge 新字段能够进入实时 raw，并进一步进入 core enriched alert

## 7. 当前残留限制

1. `live_runtime_check` 里的 `recent_alert_presence` 仍按“最新 alert_ts 文件”采样，在 replay / 人工阈值验证场景下会低估新字段出现率
2. `suggestions` 当前仍主要反映较早的 cluster 结果；这不代表 core enrichment 失效
3. 这轮为了验证“当前时间 alert”，临时把阈值降到了 `5`，已经恢复，但这个过程必须在文档中留痕，不能当作常态配置

## 8. 下一步建议

1. 把 `documentation/` 正式纳入 git 跟踪并提交
2. 修正 `live_runtime_check` 的 alert 取样逻辑
3. 在自然阈值 `200` 下继续观察一段时间：
   - raw 是否持续保持当前时间
   - alert 是否自然触发
   - aiops suggestion 是否重新回到当前时间
