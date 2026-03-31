# 前端运行时架构 2026-03-28

这是一份带日期的架构说明，保留的是 `2026-03-28` 当时前端运行台的交互模型和问题背景。
如果你想确认今天这个工作区实际挂载到了哪些 runtime 数据、当前仓库怎么描述系统边界，请优先看 [README_CN.md](../README_CN.md) 和 [PROJECT_STATE_CN.md](./PROJECT_STATE_CN.md)。

## 运行时模型

当前控制台采用的是薄网关形态：

1. 浏览器加载前端页面
2. UI 可以先用一份本地 fallback snapshot 起页
3. 前端请求 `GET /api/runtime/snapshot`
4. 前端再通过 `GET /api/runtime/stream` 建立 `SSE`
5. 网关读取运行时文件和部署控制参数
6. 网关组装出前端消费的 `RuntimeSnapshot`

当前这层投影主要依赖：

- `/data/netops-runtime/alerts/*.jsonl`
- `/data/netops-runtime/aiops/*.jsonl`
- `core/` 和 `edge/` 下的 deployment 清单

对应实现入口主要是：

- `frontend/gateway/app/main.py`
- `frontend/gateway/app/runtime_reader.py`

## 为什么是薄网关

当前运行台的目的，是把真实链路讲清楚，而不是再造一个分析后端。
在这个阶段，薄网关有三个实际优势：

- 前端看到的字段可以直接追溯到运行时产物
- UI 迭代不会反过来拖着核心数据面重构
- 当前更新是单向的，`SSE` 已经足够，没有必要为此先引入更重的交互基础设施

## 当前部署形态

### 本地开发

- 前端运行在 `:5173`
- 网关运行在 `:8026`
- 通过 Vite 代理 `/api`

### 宿主机共享环境

- 外部流量先进入 `nginx :2026`
- `/api/*` 反代到 `uvicorn/FastAPI :8026`
- 运行时文件仍在宿主机本地

这也是当前更符合实际的部署方式，因为网关本身是只读的，而且紧贴运行时卷。

## 为什么运行台仍然保持只读

当前网关做的是运行时状态投影，不是事实源，也不具备基础设施写能力。
这条边界非常重要。投影层在局部退化时依然可以为操作员提供价值；而真正可写的控制面则必须具备审批、回滚、审计和失败处理机制。当前前端和网关都还没有承担这类责任。

## 相关文档

- [项目状态](./PROJECT_STATE_CN.md)
- [根 README](../README_CN.md)
- [Frontend 工作区指南](./FRONTEND_WORKSPACE_GUIDE.md)
