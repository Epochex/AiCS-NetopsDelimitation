# NetOps Project State / 项目状态入口

This page is the compact landing note for project state.
For precise current-state wording, use the language-specific files below:

- [PROJECT_STATE_EN.md](./PROJECT_STATE_EN.md)
- [PROJECT_STATE_CN.md](./PROJECT_STATE_CN.md)

这份文档现在只作为项目状态入口页。
真正按当前口径维护的状态说明请看：

- [PROJECT_STATE_EN.md](./PROJECT_STATE_EN.md)
- [PROJECT_STATE_CN.md](./PROJECT_STATE_CN.md)

## What This Entry Is For / 这页是干什么的

Use this page when you want the shortest possible answer to:

- what the repository is currently delivering
- what runtime facts are actually mounted in this workspace
- what remains outside the delivered boundary

当你只想最快知道下面三件事时，看这页即可：

- 仓库当前到底已经交付了什么
- 当前工作区实际挂载到了哪些 runtime 事实
- 哪些能力明确还不在交付边界里

## Current One-Paragraph State / 当前一句话状态

The repository currently delivers a deterministic streaming NetOps chain:

`FortiGate -> structured fact -> deterministic alert -> audit/query persistence -> bounded suggestion -> read-only runtime console`

The workspace currently exposes `/data/netops-runtime` alert and suggestion artifacts, but not a live `/data/fortigate-runtime` volume. That means the mounted workspace is suitable for auditing alert/suggestion products and current repository posture, but it should not be described as a perfectly synchronized live snapshot across every runtime layer.

当前仓库已经交付的是这样一条确定性流式 NetOps 主链：

`FortiGate -> structured fact -> deterministic alert -> audit/query persistence -> bounded suggestion -> read-only runtime console`

当前工作区能直接访问的是 `/data/netops-runtime` 下的 alert / suggestion 产物，而不是 live 的 `/data/fortigate-runtime`。因此这个挂载环境适合审计当前 alert / suggestion 产物和仓库姿态，但不能写成“全链路每一层都严格同步的 live snapshot”。

## Related Documents / 相关文档

- [Controlled validation](./CONTROLLED_VALIDATION_20260322.md)
- [Frontend runtime architecture (dated 2026-03-28 note)](./FRONTEND_RUNTIME_ARCHITECTURE_20260328.md)
- [Edge runtime guide](./EDGE_RUNTIME_GUIDE.md)
- [Core runtime guide](./CORE_RUNTIME_GUIDE.md)
- [Frontend workspace guide](./FRONTEND_WORKSPACE_GUIDE.md)
