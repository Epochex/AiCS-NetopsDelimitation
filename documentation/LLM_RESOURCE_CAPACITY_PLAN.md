# LLM Resource Capacity Plan / LLM 资源容量规划

本文档定义当前仓库在现有两台节点和当前 runtime 流量下的 LLM 资源规划。范围包括节点职责、流量基线、请求类型、外部 GPU 服务分层、并发预算、超时策略、缓存与降级策略。本文档不讨论 control-plane 写路径。本文档只覆盖 alert downstream reasoning。

## 现有节点

`192.168.1.23` 是边缘节点。当前配置是 `Intel Xeon E3-1220 v5`、`4` 个 CPU 线程、`7.7 GiB` 内存、`914 GiB` 根分区、约 `669 GiB` 可用空间。该节点继续承载 `fortigate-ingest` 和 `edge_forwarder`。该节点不承载任何本地模型执行。该节点不承载 LLM 请求编排。该节点只输出结构化 fact 并转发到 `netops.facts.raw.v1`。

`192.168.1.27` 是核心节点。当前配置是 `Intel Xeon Silver 4310`、`24` 个 CPU 线程、`14 GiB` 内存、`1.8 TiB` 根分区、约 `1.7 TiB` 可用空间。该节点继续承载 Kafka consumer、`core/correlator`、`core/alerts_sink`、`core/alerts_store`、`core/aiops_agent` 和 runtime gateway。该节点负责 Evidence Pack、reasoning seed、provider routing hint 和 future orchestration。该节点不承载本地大模型。

当前节点没有 swap。当前节点不适合在核心机上同时承载 Kafka、ClickHouse 查询、前端网关和 30B+ 本地模型。当前节点也不适合在边缘机上做任何长上下文推理。

## 当前流量基线

当前挂载 runtime 中有 `201003` 条 alert，范围是 `2026-03-04T15:09:11+00:00` 到 `2026-04-02T16:23:04+00:00`。按这段时间计算，平均约 `6918.9` alerts/day，约 `288.29` alerts/hour，约 `0.0801` alerts/second。

当前挂载 runtime 中有 `222023` 条 suggestion，范围是 `2026-03-09T05:08:56.549849+00:00` 到 `2026-04-05T18:03:18.303384+00:00`。按这段时间计算，平均约 `8062.5` suggestions/day，约 `335.94` suggestions/hour，约 `0.0933` suggestions/second。

当前最近分桶里，alert 以 `deny_burst_v1|warning` 为主。最近分桶里 suggestion 仍以 alert-scope 为主，cluster-scope 占比低。当前流量形态适合先做“少量高价值 alert downstream reasoning”，不适合默认对每条 suggestion 触发长链多阶段 LLM。

因此当前默认预算采用以下原则：

- 默认只对已成立 alert 或 cluster trigger 发起 reasoning。
- 默认只对命中筛选条件的对象发起 LLM 调用。
- 默认只做 `max_parallelism=1`。
- 默认保留 `template provider` 作为主路径 fallback。

## 请求类型

后续 GPU 服务只接收结构化请求。输入来自 `Evidence Pack V2`、`reasoning_runtime_seed` 和阶段视图。请求按功能拆成四类。

`triage_compact`

- 用途：短摘要、轻量 evidence read、快速 hypothesis seed
- 输入：`direct_evidence` + 选中的 `supporting_evidence`
- 目标输入规模：`1k` 到 `2.5k` tokens
- 目标输出规模：`200` 到 `500` tokens
- 适合模型：小模型或远端轻量模型

`hypothesis_critique`

- 用途：比较候选假设、检查反证、输出 unresolved questions
- 输入：`direct_evidence` + `supporting_evidence` + `contradictory_evidence` + `freshness`
- 目标输入规模：`2.5k` 到 `4k` tokens
- 目标输出规模：`400` 到 `900` tokens
- 适合模型：中等模型或强模型

`runbook_draft`

- 用途：基于 evidence pack 和 runbook candidates 输出结构化 `RunbookPlan`
- 输入：`direct_evidence` + `supporting_evidence` + `missing_evidence` + runbook retrieval result
- 目标输入规模：`3k` 到 `5k` tokens
- 目标输出规模：`600` 到 `1400` tokens
- 适合模型：中等模型

`runbook_review`

- 用途：审批边界、rollback readiness、overreach risk 审查
- 输入：`RunbookPlan` + `contradictory_evidence` + `missing_evidence` + `source_reliability`
- 目标输入规模：`2.5k` 到 `4.5k` tokens
- 目标输出规模：`300` 到 `900` tokens
- 适合模型：强模型或强规则审查器

## 外部 GPU 服务分层

当前代码已经预留 `AIOPS_PROVIDER=http|gpu_http|external_model_service`、`AIOPS_PROVIDER_ENDPOINT_URL`、`AIOPS_PROVIDER_MODEL`、`AIOPS_PROVIDER_COMPUTE_TARGET` 和 `AIOPS_PROVIDER_MAX_PARALLELISM`。当前默认目标是 `AIOPS_PROVIDER_COMPUTE_TARGET=external_gpu_service`。

建议把外部 GPU 服务拆成两个层次。

`Tier A: compact reasoning`

- 负责 `triage_compact`
- 负责 `Evidence Pack V2` 的压缩、重排、轻量候选提取
- 适合 `7B` 到 `14B` instruct 级别模型
- 建议显存：`24 GiB` 到 `48 GiB`
- 建议并发：`2` 到 `4`
- 适合 batch 小、时延要求低的请求

`Tier B: review and planning`

- 负责 `hypothesis_critique`
- 负责 `runbook_draft`
- 负责 `runbook_review`
- 适合 `14B` 到 `32B` 级别模型，或远端闭源高质量模型
- 建议显存：`48 GiB` 到 `80 GiB`
- 建议并发：`1` 到 `2`
- 适合结构化输出质量优先的请求

当前流量基线下，不建议第一阶段自建多 GPU 集群。当前更合适的路径是 1 台外部 GPU 服务机，分两个 model endpoint，核心节点通过 `provider_routing.py` 按 `request_kind` 和 `suggestion_scope` 路由。

## 推荐容量

### Foundation

- 模式：`template` 主路径，外部 GPU 只接少量实验样本
- 核心参数：`AIOPS_PROVIDER_MAX_PARALLELISM=1`
- 适合用途：把 `Evidence Pack V2`、`HypothesisSet`、`ReviewVerdict` 和 `RunbookPlan` 路打通
- 外部 GPU 最低配置：`1 x 24 GiB`

### Pilot

- 模式：alert-scope 使用 compact reasoning，cluster-scope 和 review 请求走强模型
- 核心参数：`AIOPS_PROVIDER_MAX_PARALLELISM=2`
- 入口控制：只对高优先级或 cluster trigger 发起 LLM 请求
- 外部 GPU 推荐配置：`1 x 48 GiB`
- 目标：支撑低 QPS 结构化推理和对比实验

### Extended

- 模式：alert-scope compact reasoning 常开，cluster-scope hypothesis/review 常开，runbook review 按需触发
- 核心参数：`AIOPS_PROVIDER_MAX_PARALLELISM=2`
- 必要前提：引入 request queue、cache key、timeout metrics、provider failure metrics
- 外部 GPU 推荐配置：`1 x 80 GiB` 或 `2 x 48 GiB`
- 目标：支撑 paper 中的 loop-based ablation 和更长上下文 runbook drafting

当前资源边界下，没有理由把第一阶段容量规划做成高吞吐集群。当前需求是低 QPS、强结构化、强 fallback、强审查。

## 核心机预算

`192.168.1.27` 只负责以下动作：

- 读取 alert 和 cluster trigger
- 组装 `evidence_bundle`
- 构造 `evidence_pack_v2`
- 生成 provider routing hint
- 发起远端 GPU 请求
- 接收结构化结果并投影为 suggestion

核心机不负责：

- 本地 embedding 批处理
- 本地 reranker 常驻服务
- 本地大模型推理
- 多阶段大并发 agent swarm

当前内存预算建议保留：

- `4 GiB` 给 Kafka consumer、Python runtime 和系统进程
- `2 GiB` 给 ClickHouse 查询峰值和缓存
- `2 GiB` 给 frontend gateway、build artifacts 和系统开销
- 剩余预算给 `core/aiops_agent` 的请求对象、序列化和 HTTP client

因此当前 `evidence_pack_v2` 必须控制体积。建议序列化后单包不超过 `16 KiB`。建议单次 stage payload 不超过 `32 KiB`。建议单次阶段请求目标控制在 `5k` input tokens 以内。

## 并发与排队

当前核心参数建议固定如下：

- `AIOPS_PROVIDER_MAX_PARALLELISM=1`
- `AIOPS_PROVIDER_TIMEOUT_SEC=30` 作为默认值
- `cluster-scope` 请求优先级高于 `alert-scope`
- `runbook_review` 高于 `runbook_draft`

后续若提升到 `max_parallelism=2`，应先满足以下条件：

- request queue 能观测 backlog
- provider timeout 和 error rate 可观测
- suggestion emission 能区分 template fallback 和 GPU result
- trace 中能回放 provider request/response metadata

当前不建议把 `max_parallelism` 提到 `4`。当前核心机内存和网络开销都没有必要承受这个放大。

## 缓存与降级

建议缓存键采用：

- `bundle_id + stage + provider + model`

建议缓存对象采用：

- compact reasoning result
- hypothesis critique result
- runbook draft result

建议缓存命中场景：

- 同一个 `bundle_id` 在短时间内重复刷新
- 同一个 cluster trigger 在 cooldown 内重放
- 前端重新进入相同 incident

降级路径固定如下：

- 外部 GPU 超时：回退 `template provider`
- 外部 GPU 结构化输出非法：保留 trace，回退 `template provider`
- `runbook_review` 失败：保留 `runbook_draft`，标记 `review_unavailable`
- `hypothesis_critique` 失败：保留 compact triage，不进入 review loop

## 后续扩容信号

出现以下信号时，再考虑提高 GPU 规格或并发：

- `cluster-scope` 请求显著增多
- `runbook_draft` 和 `runbook_review` 成为默认路径
- `Evidence Pack V2` 输入稳定高于 `5k` tokens
- provider timeout 超过 `3%`
- 平均排队等待时间超过 `2s`
- replay/eval 需要批量离线运行

扩容顺序建议如下：

1. 先加 cache
2. 再加 request queue
3. 再拆 compact endpoint 和 review endpoint
4. 最后才考虑更大显存或更多 GPU

## 与当前代码的对应关系

当前代码已经具备以下接口：

- `core/aiops_agent/evidence_pack_v2.py`
- `core/aiops_agent/provider_routing.py`
- `core/aiops_agent/providers.py`
- `core/aiops_agent/evidence_bundle.py`
- `core/aiops_agent/alert_reasoning_runtime/phase_context_router.py`

当前代码仍未具备以下能力：

- provider request queue metrics
- cache layer
- structured `HypothesisSet`
- structured `ReviewVerdict`
- structured `RunbookPlan`
- replay-driven batch evaluation harness

因此当前资源规划是 foundation 级规划。它围绕低 QPS、远端 GPU、结构化对象和 template fallback 组织，不围绕高吞吐推理组织。
