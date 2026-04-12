# 早稻田 GPU 推理服务接入说明

本文档描述当前分支如何把早稻田共享 GPU 集群接成 NetOps 的外部大模型推理服务。核心原则是：core 节点不承载大模型，只负责确定性告警、拓扑门控、证据组装和结果投影；GPU 集群只作为被门控后的外部推理服务。

## 当前闭环

真实执行链路如下：

```text
LCORE 告警
-> evidence bundle
-> topology-aware subgraph
-> LLM 调用门控
-> should_invoke_llm=false: 本地模板兜底
-> should_invoke_llm=true: 通过 SSH 隧道调用早稻田 GPU 推理网关
-> 结构化建议
-> runtime / 前端投影
```

已落地的关键保护是：即使 `AIOPS_PROVIDER=gpu_http`，只要 `llm_invocation_gate.should_invoke_llm=false`，core 也不会访问 GPU 端点，而是直接返回模板结果，并在结果中记录 `external_provider_skipped=true`。

## SSH 连接

建议在 r450core 或你的本地机器写入 SSH 配置：

```sshconfig
Host waseda-gpu
  HostName 127.0.0.1
  Port 2223
  User cezheng
  ProxyJump colazhang-japan
```

然后建立隧道：

```bash
ops/waseda_gpu/open_core_tunnel.sh
```

默认映射为：

```text
r450core:127.0.0.1:18080 -> waseda-gpu:127.0.0.1:18080
```

core 侧 provider endpoint 使用：

```text
http://127.0.0.1:18080/infer
```

## 模型文件搬运

GPU 节点没有公网时，不在 GPU 节点直接下载模型。推荐流程是：

```text
本地或跳板机下载模型
-> rsync/scp 传到 GPU 节点
-> GPU 节点离线加载模型
```

推荐目录：

```text
/home/cezheng/models
/home/cezheng/netops-llm
```

如果确认 `/data` 或 `/mnt` 对当前用户可写且空间更稳定，再迁移到共享数据盘。

## A6000 选择策略

共享集群不能真正“硬抢占”GPU，除非有调度系统权限。当前实现是软保留：

- 优先选择 RTX A6000。
- 默认至少选择 1 张卡。
- 优先选择低计算占用、空闲显存最多的卡。
- 写入软锁文件，记录 NetOps 服务占用意图。
- 真正占用由 vLLM/SGLang 推理进程保持。

查看选择结果：

```bash
python3 ops/waseda_gpu/select_a6000_gpu.py --count 1 --emit json
```

启动快速模型服务：

```bash
MODEL_PATH=/home/cezheng/models/GLM-4.7-Flash \
SERVED_MODEL_NAME=glm-fast \
GPU_COUNT=1 \
MAX_MODEL_LEN=32768 \
GPU_MEMORY_UTILIZATION=0.82 \
ops/waseda_gpu/start_fast_model_service.sh
```

如果 1 张 A6000 不够，再改成：

```bash
GPU_COUNT=2
TENSOR_PARALLEL_SIZE=2
```

不建议一开始长期占用 4 张 A6000。4 张更适合离线批量评测窗口，而不是常驻实时服务。

## NetOps 推理网关

vLLM 暴露的是 OpenAI 兼容接口，core 当前使用的是 NetOps evidence contract。因此 GPU 节点上还需要启动一个轻量网关：

```bash
OPENAI_BASE_URL=http://127.0.0.1:8000/v1 \
OPENAI_MODEL=glm-fast \
NETOPS_GATEWAY_PORT=18080 \
ops/waseda_gpu/start_gateway.sh
```

健康检查：

```bash
curl http://127.0.0.1:18080/healthz
```

## core 配置

隧道稳定后，core-aiops-agent 可以配置：

```text
AIOPS_PROVIDER=gpu_http
AIOPS_PROVIDER_ENDPOINT_URL=http://127.0.0.1:18080/infer
AIOPS_PROVIDER_MODEL=glm-fast
AIOPS_PROVIDER_TIMEOUT_SEC=90
AIOPS_PROVIDER_MAX_PARALLELISM=1
AIOPS_PROVIDER_COMPUTE_TARGET=external_gpu_service
```

由于 core provider 已经有硬门控，低价值或可能自愈告警不会访问 GPU。

## 回放评测

先做 dry-run，确认门控和指标落盘：

```bash
python3 -m core.benchmark.topology_gated_llm_replay \
  --dry-run \
  --alert-dir /data/netops-runtime/LCORE-D/work/alerts-sample \
  --output-json /data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.json \
  --output-jsonl /data/netops-runtime/LCORE-D/work/llm-provider-replay-events.jsonl
```

接入 GPU 后：

```bash
python3 -m core.benchmark.topology_gated_llm_replay \
  --provider gpu_http \
  --endpoint-url http://127.0.0.1:18080/infer \
  --model glm-fast \
  --timeout-sec 90 \
  --alert-dir /data/netops-runtime/LCORE-D/work/alerts-sample \
  --output-json /data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.json \
  --output-jsonl /data/netops-runtime/LCORE-D/work/llm-provider-replay-events.jsonl
```

生成论文风格图：

```bash
python3 documentation/scripts/render_llm_provider_replay_figure.py \
  --summary-json /data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.json \
  --events-jsonl /data/netops-runtime/LCORE-D/work/llm-provider-replay-events.jsonl \
  --output-png /data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.png
```

当前 dry-run 结果：

```text
LCORE-D alerts: 1302
invoke-all planned calls: 1302
topology-gated planned calls: 173
template-only skips: 1129
planned call reduction: 86.71%
high-value recall: 100%
response schema valid rate: 100%
```

注意：dry-run 结果只验证门控、协议和结构化输出，不代表真实模型质量。真实 GPU 接入后，需要重新记录延迟、超时率、结构化输出成功率和故障定位质量。
