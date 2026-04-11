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
| LCORE-D 50k replay sample | `1302` | `1302` | `173` | `86.71%` | `173` | `100.00%` |

office trace 可以作为历史工程链路 sanity check，但在当前评测窗口中没有 high-value LCORE 故障定位标签。LCORE-D replay 才是当前研究相关的数据切片。

![Topology-aware subgraph extraction ablation](documentation/images/topology_ablation_summary.png)

图：一次性 ablation 总结。Panel A 对比 invoke-all 与 topology-gated 的 LLM 请求量。Panel B 展示 efficiency-quality frontier：LCORE topology gate 从 invoke-all baseline 的 0% 调用减少，移动到 86.71% 调用减少，同时保留 100% high-value recall。虚线 evidence-size curve 表示 gate 变严格后，进入 LLM 的 selected evidence slice 仍保持紧凑。

当前数字还不是最终 root-cause top-1 accuracy。它是第一阶段系统结果：在 LCORE-D replay 上，topology gate 将 LLM 调用减少 `86.71%`，同时保留 `100%` high-value alert eligibility。下一步评测需要接入 incident-window root labels，并报告 root-candidate、symptom、noise 的分类准确率。

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

待完成：

- 面向论文级定位准确率的 root-cause label 对齐
- 真实本地或远端 LLM endpoint 的 provider execution wiring
- 响应校验与超时 fallback
- 可回放模型评测的 trace capture
- 基于完整 LCORE-D incident windows 的 rule-only 与 invoke-all baseline 对比

## 常用命令

准备 LCORE-D facts：

```bash
python3 -m core.benchmark.lcore_adaptive_prepare \
  --input /data/netops-runtime/LCORE-D/raw \
  --output-jsonl /data/netops-runtime/LCORE-D/work/events-sample.jsonl \
  --plan-json /data/netops-runtime/LCORE-D/work/feature-plan-core.json \
  --max-records 50000
```

运行 topology-gate ablation：

```bash
python3 -m core.benchmark.topology_subgraph_ablation \
  --alert-dir /data/netops-runtime/LCORE-D/work/alerts-sample \
  --limit-files 0 \
  --output-json /data/netops-runtime/LCORE-D/work/topology-subgraph-ablation.json
```

验证当前分支：

```bash
python3 -m pytest tests/core/test_topology_subgraph.py tests/core/test_aiops_agent.py tests/common/test_adaptive_features.py tests/core/test_rules.py -q
cd frontend && PATH=/data/.local/node/bin:$PATH npm run build
```
