## NetOps Causality Remediation
[![English](https://img.shields.io/badge/Language-English-1f6feb)](./README.md) [![Simplified Chinese](https://img.shields.io/badge/Language-Simplified%20Chinese-2ea043)](./README_CN.md)

当前分支实现的是一个面向 LCORE-D 核心网络遥测的 topology-aware NetOps 推理流水线。系统将确定性告警建立与模型辅助分析显式分离：模型不能决定告警是否成立，只能在规则路径已经确认告警之后，接收边界受控的证据。

当前研究重点已经不再是办公室 FortiGate 流量。办公室 runtime 只作为历史工程链路参考。当前 active scenario 是 LCORE-D 故障定位：系统需要利用拓扑结构减少噪声证据，区分 root-candidate 与 symptom 节点，并避免把低价值或可能自愈的切片全部送入 LLM。

## 系统定义

系统由五个平面组成：

- Edge fact plane：将 LCORE-D 行数据转换为稳定的 canonical facts，包含设备身份、故障标签与拓扑上下文。
- Deterministic alert plane：在任何模型参与之前，通过质量门控和规则确认告警。
- Topology evidence plane：围绕已确认告警提取局部子图，并给节点分配 root-candidate、symptom、noise 角色。
- Bounded reasoning plane：构造结构化 evidence pack、hypothesis、review verdict、runbook draft 和 stage request。
- Runtime projection plane：将告警、建议、拓扑 gate 和评测产物投影到 operator UI。

受控执行平面不属于当前分支交付范围。Remediation 仍然是人工确认的运维指导，并保留明确的 approval 与 rollback 边界。

```mermaid
flowchart LR
  A["LCORE-D edge stream"] --> B["Canonical fact"]
  B --> C["Quality gate"]
  C --> D["Deterministic alert"]
  D --> E["Topology-aware subgraph"]
  E --> F["Evidence Pack V2"]
  F --> G["Hypothesis + review + runbook"]
  G --> H["Stage requests"]
  H --> I["Runtime console"]

  E --> J{"LLM gate"}
  J -->|"high-value fault"| K["External LLM eligible"]
  J -->|"transient / low evidence"| L["Template-only bounded path"]
```

主要对象链路为：

`canonical fact -> deterministic alert -> evidence bundle -> topology_subgraph -> Evidence Pack V2 -> HypothesisSet -> ReviewVerdict -> RunbookDraft -> ReasoningStageRequests -> runtime projection`

## LCORE Runtime Contract

edge 侧负责 fact identity 与 topology normalization。core 侧负责告警、证据组装与推理。当前 core 期望的 contract 如下：

| 字段 | 期望含义 |
| --- | --- |
| `src_device_key` | 稳定的 LCORE 设备身份，例如 `CORE-R1` 到 `CORE-R7` |
| `device_profile.device_name` | 与 `src_device_key` 一致的稳定设备身份 |
| `fault_context.scenario` | 归一化场景，例如 `healthy`、`induced_fault` 或 `transient_fault` |
| `topology_context.path_signature` | 不含本地文件路径的稳定拓扑签名 |
| `topology_context.hop_to_core` | 指向核心侧的距离类拓扑特征 |
| `topology_context.hop_to_server` | 指向服务器侧的距离类拓扑特征 |
| `topology_context.downstream_dependents` | 可用时表示局部下游依赖数量 |
| `topology_context.path_up` | 来自 LCORE 源数据的路径状态特征 |
| `topology_context.interface_type` | 存在时保留数值型接口类型特征 |
| `topology_context.srcintf` | 仅保留真实接口名；数值特征不应放入该字段 |

这个职责划分很重要：core 有 defensive guard 防止异常 fact 把链路打歪，但 identity 与 topology 的正确修复应该发生在 edge canonicalization 层。

## Topology-Aware Subgraph Extraction

topology-aware 层将 LLM-based production-network failure localization 的思想适配到本项目的 bounded NetOps 场景中。系统不会把每个告警及其全部邻近事实都送入 LLM，而是为每个已确认告警构造最小局部子图：

- Root-candidate nodes：具有直接故障证据、关键故障场景或高复发性的节点。
- Symptom nodes：拓扑上相邻或历史上相关，可能反映故障传播的节点。
- Noise nodes：弱相关节点，保留在 selected reasoning core 之外。
- LLM gate：根据场景严重度、拓扑证据、复发性和自愈可能性决定是否值得调用外部 LLM。

这使当前分支的贡献不再只是普通 post-alert summary：拓扑不仅是展示上下文，而是直接参与证据选择，并减少推理扩散。

## 实现摘要

当前已经实现的核心结构包括：

- `topology_subgraph`
- `llm_invocation_gate`
- `candidate_event_graph`
- `reasoning_runtime_seed`
- `Evidence Pack V2`
- `HypothesisSet`
- `ReviewVerdict`
- `RunbookDraft`
- `ReasoningStageRequests`

主要实现文件如下：

| 区域 | 路径 |
| --- | --- |
| 拓扑子图提取 | `core/aiops_agent/alert_reasoning_runtime/topology_subgraph.py` |
| 告警/集群 seed adapter | `core/aiops_agent/alert_reasoning_runtime/rule_based_seed_adapter.py` |
| Evidence bundle 投影 | `core/aiops_agent/evidence_bundle.py` |
| Evidence Pack V2 接入 | `core/aiops_agent/evidence_pack_v2.py` |
| Provider routing hint | `core/aiops_agent/provider_routing.py` |
| Review verdict checks | `core/aiops_agent/review_verdict.py` |
| LCORE adaptive fact conversion | `common/data_features/adaptive.py` |
| Ablation benchmark | `core/benchmark/topology_subgraph_ablation.py` |
| 前端 runtime 投影 | `frontend/gateway/app/runtime_reader.py` |

## 评测快照

当前 ablation 将 invoke-all baseline 与 topology-aware selective invocation 进行对比。baseline 假设每个已确认告警都会送入外部 LLM。topology-aware 路径只有在 subgraph gate 将告警标记为 high-value 时才调用外部 LLM。

| 数据切片 | 扫描告警数 | Invoke-all LLM 调用 | Topology-gated LLM 调用 | 调用减少 | High-value alerts | High-value recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Office legacy trace | `886` | `886` | `0` | `100.00%` | `0` | `0.00%` |
| LCORE-D Mark-1 live replay | `1302` | `1302` | `173` | `86.71%` | `173` | `100.00%` |
| LCORE-D full core-patched replay | `6700` | `6700` | `562` | `91.61%` | `562` | `100.00%` |

office trace 可以作为历史工程链路 sanity check，但在当前评测窗口中没有 high-value LCORE 故障定位标签。LCORE-D replay 才是当前研究相关的数据切片。

![Topology-aware subgraph extraction ablation](documentation/images/topology_ablation_summary.png)

图：Mark-1 live replay 的一次性 ablation 总结。Panel A 对比 invoke-all 与 topology-gated 的 LLM 请求量。Panel B 展示 efficiency-quality frontier：LCORE topology gate 从 invoke-all baseline 的 0% 调用减少，移动到 86.71% 调用减少，同时保留 100% high-value recall。更严格的 full core-patched replay 现在达到 91.61% 调用减少，同时继续保留 100% high-value recall。

当前数字还不是最终 root-cause top-1 accuracy。它是第一阶段系统结果：在 full core-patched LCORE-D replay 上，topology gate 将 LLM 调用减少 `91.61%`，同时保留 `100%` high-value alert eligibility。下一步评测需要接入 incident-window root labels，并报告 root-candidate、symptom、noise 的分类准确率。

## GPU 推理服务回放

外部推理服务路径现在已经有硬拓扑门控。如果 `llm_invocation_gate.should_invoke_llm=false`，`gpu_http` provider 会直接返回本地模板兜底，并记录 `external_provider_skipped=true`；它不会访问 GPU endpoint。如果 gate 为 true，请求可以通过早稻田 GPU 隧道进入 NetOps LLM gateway。

真实 provider 路径已经通过早稻田 GPU 集群验证。当前 runtime 在 GPU 节点的 `28000` 端口运行 OpenAI-compatible vLLM 模型服务，在 `18080` 端口运行 NetOps gateway，并通过 core 侧 SSH 隧道保持稳定调用入口：`http://127.0.0.1:18080/infer`。

当前真实回放配置：

| 层级 | Runtime 值 |
| --- | --- |
| 远端模型服务 | 早稻田 GPU 节点上的 `vLLM` |
| Mark-1 闭环使用模型 | `Qwen2.5-14B-Instruct`，服务名 `netops-fast` |
| 模型端口 | GPU 节点 `127.0.0.1:28000` |
| NetOps gateway | GPU 节点 `127.0.0.1:18080` |
| Core 调用入口 | 经 SSH 隧道访问 `http://127.0.0.1:18080/infer` |
| 执行模式 | high-value 告警真实调用外部模型；template-only 告警本地兜底 |

![Topology-gated live LLM replay summary](documentation/images/llm_provider_replay_real_full.png)

Mark-1 真实 GPU 回放扫描 `1302` 条 LCORE-D 告警。invoke-all baseline 需要 `1302` 次外部模型调用；topology-gated 路径只进行了 `173` 次真实 GPU 调用，跳过 `1129` 条 template-only 告警，外部调用减少 `86.71%`，保留 `100%` high-value alert recall，并得到 `100%` schema-valid 响应。`173` 次真实 GPU 调用中失败数为 `0`，外部模型延迟 avg `9675.38 ms`，p50 `9561.00 ms`，p95 `11321.43 ms`。

edge `run_id` 与 core topology-lineage 修复后，full core-patched LCORE-D replay 从 `169,712` 条 canonical facts 生成 `6700` 条 deterministic alerts。topology gate 将全部 `562` 条 induced-fault high-value alerts 保留给外部推理，并将 `6138` 条 transient-fault alerts 留在本地 template path。因此外部调用减少 `91.61%`，high-value recall 仍为 `100%`。

raw response capture audit 使用按 scenario 与 device 分层的 `24` 条告警样本。审计中真实 GPU 调用 `14` 次，`10` 条 transient alerts 保持本地模板路径。结果为：provider failure `0`，schema-valid `100%`，external response quality avg `1.000`，`14/14` 条外部响应为 `strong`，经过 gateway 输出边界约束后 unsafe execution-language finding 为 `0`。更严格 prompt 路径下外部延迟 avg `14720.54 ms`，p50 `14847.22 ms`，p95 `16907.45 ms`。

回放与审计产物位置：

- Summary：`/data/netops-runtime/LCORE-D/work/llm-provider-replay-real-full-summary.json`
- Per-alert replay records：`/data/netops-runtime/LCORE-D/work/llm-provider-replay-real-full-events.jsonl`
- Full core-patched gate summary：`/data/netops-runtime/LCORE-D/work/llm-provider-replay-corepatched-full-template-summary.json`
- Raw response audit summary：`/data/netops-runtime/LCORE-D/work/llm-provider-replay-corepatched-stratified-real-prompt3-summary.json`
- Raw response audit records：`/data/netops-runtime/LCORE-D/work/llm-provider-replay-corepatched-stratified-real-prompt3-events.jsonl`

raw response audit records 保存了每条抽样告警的模型建议正文和对应 evidence bundle。后续如果要主张 action usefulness，应优先基于这些记录做人工质检。

运行细节见 [`documentation/WASEDA_GPU_LLM_PROVIDER.md`](documentation/WASEDA_GPU_LLM_PROVIDER.md)。

## 模型执行计划

当前系统不应该把大模型 colocate 到 core pipeline 内部。core 节点应继续专注确定性告警、证据组装与 runtime projection。模型执行应该作为 provider，通过显式 stage request interface 接入。

推荐 provider 顺序：

- 短期：保留 template path 作为永远可用的 fallback。
- 近期：从早稻田 GPU 集群暴露 OpenAI-compatible endpoint，只将 topology-gated high-value alerts 路由过去。
- 实验层：通过 vLLM 或 SGLang 评估 GLM-4.5-Air 或其他 reasoning/coding 模型。
- 对照层：保留 hosted API model 作为质量对照、回归检查和本地模型失败时的兜底。

使用 GPU 集群的目的不是从头训练 foundation model，而是受控推理，以及可能的轻量 LoRA/SFT incident-local prompt 实验。CPU-only 或 memory-only inference 可以用于小模型，但本项目强调推理深度和长结构化上下文；对于论文级评测，GPU 集群是更现实的路径。

## 运行边界

- 告警建立必须是确定性、规则支撑的。
- LLM 推理只发生在 post-alert 且 evidence-bounded 的阶段。
- 拓扑选择发生在外部模型调用之前。
- 低价值 transient slices 可以保留在 template-only 路径。
- suggestion 不会自动写回设备。
- 未来任何执行路径都必须停在 approval 与 rollback 边界前。

## 当前状态

当前分支已经完成 topology-aware post-alert reasoning 的本地结构化链路，并且 active runtime scenario 已经从 office traffic 迁移到 LCORE-D telemetry。

已完成：

- LCORE canonical fact adaptation
- 确定性 `annotated_fault_v1` 告警
- topology-aware subgraph extraction
- LLM invocation gating
- evidence pack 与 stage request 接入
- 面向 LCORE/topology 语义的前端 runtime projection
- 用于 LLM 调用减少的 ablation benchmark
- 早稻田 GPU provider 的真实 LCORE-D replay 接线
- `template_only` topology gate 的硬跳过行为

待完成：

- 面向论文级定位准确率的 root-cause label 对齐
- 带 raw model response capture 的完整建议质量审计
- 响应校验、超时 fallback 与 trace capture 的生产化加固
- 基于完整 LCORE-D incident windows 的 rule-only 与 invoke-all baseline 对比

## Replay Identity 与循环发送

LCORE-D replay 现在有显式 `run_id`。edge streamer 会把它写入 `dataset_context.run_id`，存入 streamer checkpoint，并纳入 canonical `event_id` 的哈希。这样后续用同一份 LCORE 行数据再次 replay 时，可以被 core 识别为新的实验轮次，而不是被 duplicate gate 当作同一批历史 fact 丢弃。

循环发送是可行的，但它更适合作为系统健康检查流量，而不是直接混入论文级原始统计。它可以用于 LLM provider 接上之后验证全链路是否仍然可运行，例如 Kafka transport、core ingest、alerting、evidence assembly 和 UI freshness。用于论文评测时，每一轮 loop 都必须带独立 `run_id`，并在统计时显式分组或剔除重复 replay。

运行边界：

- 默认仍然是 one-shot replay，读到 EOF 后停止。
- edge forwarder 本身是循环扫描文件的 daemon，但只发送 byte checkpoint 之后新增的 JSONL 行。
- core consumer 持续消费 Kafka 新消息，但不会主动重放历史 offset，除非重置 consumer group。
- 如果启用 LCORE streamer loop mode，每一轮必须使用不同 `run_id`；否则重复 `event_id` 被 core 丢弃是预期行为。

## Runtime Feature 与流速记录

下表记录 r230 edge 到 r450 core 的 LCORE-D replay 活跃窗口实测流速。

| 阶段 | Runtime 对象 | 实测 feature 数量 | 实测数据量 | 实测流速 | 备注 |
| --- | --- | ---: | ---: | ---: | --- |
| LCORE-D raw CSV | 源数据行 | 每文件 `32-51` 列，7 个文件 union 后 `234` 列 | `169,712` 行，`26,670,593` bytes | offline source | 分文件列数：R1/R5/R7 为 `42`，R2 为 `32`，R3/R6 为 `51`，R4 为 `47` |
| Adaptive feature plan | `feature-plan.json` | 采样 `43` 列；`1` 个 label field，`4` 个 entity fields，`7` 个 topology fields，`3` 个 metric fields | 基于 `5,000` 行采样生成 | 每轮 replay 生成一次 | 当前 label field 是 `class`；topology fields 包括 `Hop_to_core`、`Hop_to_server`、`path_up` |
| Edge canonical fact JSONL | `events-lcore-d.jsonl` | `22` 个 top-level 字段；嵌套：topology `19`、device profile `12`、fault context `5`、full core-patched replay 中 dataset context `11` | `169,712` 行，`326,733,942` bytes | 最新完成 streamer 段 `17.12 EPS` | 新 replay 携带 `dataset_context.run_id`，因此 replay identity 被保留，但 top-level fact shape 不变 |
| Edge forwarder -> Kafka | Kafka topic `netops.facts.raw.v1` | 同 canonical fact payload：`23` 个 top-level 字段 | 累计发送 `169,886` 条，`326,276,448` bytes，`0` dropped | 活跃窗口 `17.06 EPS`，约 `0.268 Mbps` | 累计量包含早期 smoke/replay 发送 |
| Core correlator ingest | 质量门控后的 facts | 从 Kafka 消费的 canonical fact：`23` 个 top-level 字段 | 日志计数 `ingested=135,881`，`accepted=135,832`，`drop_duplicate_event_id=49` | 稳定窗口 `17.30 accepted facts/s` | 其他 drop 全为 `0`：缺字段、parse status、JSON error、DLQ |
| Deterministic alert | `annotated_fault_v1` alert | `14` 个 top-level 字段；嵌套：dimensions `2`、metrics `3`、event excerpt `31`、topology `20`、device profile `12`、change context `6` | full core-patched replay `6700` 条 alerts | live runtime 稳定窗口 `0.0396 alerts/s` | 告警路径是 deterministic post-quality-gate；LLM 不参与告警成立 |
| Runtime suggestion tail | `netops.aiops.suggestions.v1` | `24` 个 top-level 字段；嵌套：context `17`、evidence bundle `17`、inference `12`、runtime seed `7`、hypothesis set `6`、review verdict `9`、runbook draft `15`、stage requests `2` | topic latest offsets 跨历史合计 `293,458` 条 | 下游 AI 速率取决于告警产生速率与 LLM gate 策略 | 最新 tail sample 确认当前 suggestion schema 已是 24-field 版本 |
