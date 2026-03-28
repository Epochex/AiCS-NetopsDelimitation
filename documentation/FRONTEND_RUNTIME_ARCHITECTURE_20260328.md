# Frontend Runtime Architecture 2026-03-28

本文件用于说明当前前端 runtime console 的交互架构、`fallback -> live` 的真实含义、2026-03-28 这轮故障的根因，以及更适合长期稳定运行的演进方案。

- 最后更新：2026-03-28 15:20 UTC
- 关联状态入口：[PROJECT_STATE.md](./PROJECT_STATE.md)
- 关联问题日志：[ISSUES_LOG.md](./ISSUES_LOG.md)

## 1. `fallback` 到底指什么

当前项目里至少有两种不同语义的 `fallback`，这次问题里最容易混淆的也是这里。

### 1.1 UI demo fallback

这是前端本地内置的静态 snapshot，来源是：

- `frontend/src/data/runtimeModel.ts`

它的作用不是表示“真实线上最后状态”，而是：

- 在网关不可用时，保证页面还能起一个完整的、语义自洽的控制台
- 让前端开发、组件拆分、视觉验证不被 live runtime 是否健康完全卡死

在 `useRuntimeSnapshot` 里，它一开始就会被放进 React state 作为初始值：

- `frontend/src/hooks/useRuntimeSnapshot.ts`

这就是“先 fallback，再 live 覆盖”的前半句。

### 1.2 Runtime last-known-good fallback

这是 2026-03-28 新补上的保护语义。

它不是一个单独文件，而是一种策略：

- 如果 live snapshot 返回了 `200`
- 但缺少 `timeline` / `stageTelemetry`
- 或者 SSE 一直不发首包

那么前端不再无条件接受它，而是继续保留“最后一个被验证为可用的 snapshot”。

也就是说：

- 旧逻辑里的 `fallback` 更接近“本地演示模型”
- 新逻辑里的 `fallback / degraded` 更接近“last known good runtime view”

### 1.3 这次事故里的关键误区

这次真正的问题不是“fallback 机制存在”，而是：

1. 前端把“HTTP 200”误当成“runtime 数据可信”
2. `fallback` 最初只是 demo snapshot，不是严格意义上的 runtime last-known-good
3. live 服务进程又恰好返回了结构不完整的 snapshot

于是就出现了用户视角上的怪现象：

- 刷新后先看到一份完整、像是正常的生命周期界面
- 几秒后被一份“返回成功但结构坏掉”的 live 数据覆盖
- 页面没有白屏，但语义已经崩了

## 2. 当前前后端交互架构是什么

### 2.1 浏览器到数据源的主路径

当前架构是一个“浏览器 + React 薄状态层 + FastAPI 薄网关 + runtime 文件投影视图”的方案。

核心路径如下：

1. 浏览器打开前端页面
2. React 应用先以内置 fallback snapshot 起页
3. 前端向 `GET /api/runtime/snapshot` 拉一次完整 `RuntimeSnapshot`
4. 前端再通过 `GET /api/runtime/stream` 建立 `SSE`
5. FastAPI 网关每秒轮询 runtime 文件，必要时推送：
   - `snapshot`
   - `delta`
   - `heartbeat`
6. 前端根据 snapshot/delta 更新 lifecycle、cluster watch、evidence drawer、topology 等区块

### 2.2 开发态架构

开发态是双端口：

1. 浏览器访问 `:5173`
2. `Vite` 托管前端
3. `Vite` 把 `/api` 代理到 `:8026`
4. `FastAPI` 网关从 `/data/netops-runtime` 和仓库里的 deployment 配置构造 `RuntimeSnapshot`

对应实现：

- `frontend/vite.config.ts`
- `frontend/gateway/app/main.py`
- `frontend/gateway/app/runtime_reader.py`

### 2.3 当前 host 部署态架构

当前 review / shared host 的运行形态是：

1. 浏览器访问公网入口 `:2088`
2. 外层还有一层 `Caddy`
3. `Caddy` 再转给 `nginx :2026`
4. `nginx` 直接回前端静态资源
5. `nginx` 把 `/api/*` 反代到 `uvicorn/FastAPI :8026`

仓库中的已知配置：

- `frontend/deploy/nginx/netops-ops-console.conf`
- `frontend/deploy/systemd/netops-ops-console-backend.service`

这意味着当前线上实际上是“双代理 + 一个内部网关”的形态，而不是单纯的“前端静态页 + API”。

### 2.4 FastAPI 网关在做什么

当前网关不是业务主系统，只是一个 runtime projection gateway：

- 读取 `/data/netops-runtime/alerts/*.jsonl`
- 读取 `/data/netops-runtime/aiops/*.jsonl`
- 读取 observability/live runtime audit
- 读取 `core/`、`edge/` deployment 里的控制参数
- 现场拼装出一个适合前端消费的 `RuntimeSnapshot`

这件事由：

- `load_runtime_snapshot()`

完成。

流更新则由：

- `runtime_stream()`

每秒重复调用 `load_runtime_snapshot()`，再根据前后快照差异决定是否发 `delta`。

### 2.5 当前架构的优点

对当前项目阶段，这个架构并不荒唐，反而有几个明确优点：

1. 简单
   - 没有先引入 Redis、消息 fan-out、WebSocket hub、独立 projection DB 这些重基础设施

2. 同语义
   - 前端看到的字段基本都能追溯回 runtime JSONL 和 deployment config

3. 适合早期联调
   - 当系统还在确认“什么状态该被展示”时，薄网关比厚后端更利于快速迭代

4. SSE 足够
   - 当前是单向实时更新，不需要浏览器向服务端持续推控制命令
   - 所以 `SSE` 比 `WebSocket` 更省事，也更符合当前阶段

## 3. 为什么会导致现在这个问题

这次问题不是单点故障，而是三个层面的缺陷叠加。

### 3.1 第一层：前端把“成功返回”误判成“数据可信”

旧逻辑的问题是：

- `GET /api/runtime/snapshot` 只要返回 `200`
- 前端就直接 `setSnapshot(nextSnapshot)`

它不会先检查：

- 当前 active suggestion 是否有 `timeline`
- 是否有 `stageTelemetry`
- alert/suggestion 时间水位是否严重漂移

所以它并没有把“网络成功”和“语义成功”分开。

### 3.2 第二层：线上 live 服务返回了结构不完整的 snapshot

2026-03-28 的实测结果里，下面两个 live 入口都返回了坏结构：

- `http://127.0.0.1:2026/api/runtime/snapshot`
- `http://38.207.130.214:2088/api/runtime/snapshot`

当时可见的事实是：

- `latestAlertTs = 2026-03-25T23:00:40+00:00`
- `latestSuggestionTs = 2026-03-28T15:11:xx+00:00`
- `current_day_volume = 0 / 598x`
- active suggestion 的 `stageTelemetry = 0`
- active suggestion 的 `timeline = 0`

这说明 live runtime 并不是“稍微延迟”，而是：

- alert 流和 suggestion 流已经显著不同步
- 生命周期关键字段直接丢失

### 3.3 第三层：运行中的服务进程与工作区代码不一致

更关键的一点是，工作区代码本身并不坏。

同样在 2026-03-28，直接在工作区调用：

- `frontend/gateway/app/runtime_reader.py`

里的 `load_runtime_snapshot()`，拿到的是：

- `stageTelemetry = 10`
- `timeline = 5`

也就是说：

- 仓库代码已经会生成完整生命周期遥测
- 但线上 `:8026 / :2026 / :2088` 服务进程实际返回的却是空数组

这说明运行中的 live 服务很可能仍是旧代码、旧内存态，或者根本不是当前工作区这版进程。

### 3.4 第四层：公网链路还有额外的代理/传输问题

`2088` 一直转圈，不只是因为 snapshot 语义坏，还叠加了传输层问题。

2026-03-28 的远端观测结果：

1. `index-DZOEXAUS.css`
   - 20 秒超时
   - 大约卡在 `40703 / 45620` 字节

2. `index-BIwYbIry.js`
   - 20 秒超时
   - 大约卡在 `237311 / 243281` 字节

3. `/api/runtime/stream`
   - 会回 `200 OK`
   - 也能看到 `text/event-stream`
   - 但 20 秒内没有任何事件 body 被 flush 出来

返回头里还能看到：

- `Via: 1.1 Caddy`
- `Server: nginx/1.18.0 (Ubuntu)`

这说明问题至少发生在：

- `Caddy -> nginx`
- 或 `nginx -> backend`
- 或 SSE / 静态资源的代理缓冲、尾包传输

而不是单纯的 React render 慢。

## 4. 当前架构是否适合这个项目

### 4.1 适合当前阶段的部分

如果问题是“如何快速把真实 NetOps runtime 语义投到一个可演示的前端控制台”，那么当前方案是合理的：

- React 本地状态足够
- `FastAPI + SSE` 足够
- 直接从 runtime 文件构造 snapshot 也足够

这套方案特别适合：

- 还在定义 lifecycle 语义
- 还在确定 compare-mode / evidence / control boundary
- 还没有大规模多用户并发

### 4.2 不适合长期稳定运行的部分

如果目标提升为“稳定的实时平台演示面 / conference 级展示面 / 面试里能讲清楚的工程闭环”，当前方案就还差几层：

1. 缺少后端侧的 snapshot 完整性约束
2. 缺少运行版本可见性
3. 缺少 last-known-good 的服务端持久语义
4. 代理链条过长，SSE 和静态资源尾包行为不可控
5. runtime projection 每次请求都现场拼装，缺少显式的 materialized view

## 5. 更适合当前情况的目标架构

### 5.1 不建议现在就做的事

不建议为了“看起来更先进”立刻改成：

- 重型 WebSocket 网关
- Redux / Zustand 全局大 store
- 独立的 BFF + Redis + fan-out 集群

这些会增加复杂度，但并不会先解决这次真正的问题。

### 5.2 更合适的演进方向

更适合当前项目的是：

`validated snapshot + last-known-good projection + single-responsibility proxy`

可以拆成下面几层。

#### A. 把 runtime projection 从“现场拼装”升级成“有版本的投影视图”

建议引入一个明确的 projection 语义，不一定要新服务，但至少要新约束：

每份 snapshot 都应包含：

- `schema_version`
- `build_sha`
- `generated_at`
- `snapshot_id`
- `latest_alert_ts`
- `latest_suggestion_ts`
- `integrity`

其中 `integrity` 至少要显式表达：

- `has_timeline`
- `has_stage_telemetry`
- `stream_skew_ms`
- `volume_skew`
- `source_freshness_sec`

这样前端就不需要自己猜“这个 live snapshot 到底能不能信”。

#### B. 网关维护 last-known-good snapshot

比起让浏览器自己兜底，更稳的方式是：

1. 网关先生成候选 snapshot
2. 做完整性校验
3. 只有通过校验才替换当前 `last_known_good`
4. `/api/runtime/snapshot` 默认返回 `last_known_good`
5. 同时附带一个 `integrity_warning` 字段，告诉前端最新 live 是否异常

这样用户看到的就是：

- “上一个可信运行态 + 明确警报”

而不是：

- “刚正常几秒，然后被坏数据覆盖”

#### C. 把 demo fallback 从默认 runtime 语义里降级

长期来看，`runtimeModel.ts` 里的静态 fallback 不应该再承担“线上页面还能不能正常显示”的职责。

更好的职责拆分是：

1. `runtimeModel.ts`
   - 只用于离线开发、story、文档模式、无 runtime 场景

2. `last_known_good snapshot`
   - 由网关或前端会话内缓存承担真实 runtime fallback

#### D. 继续保留 SSE，但把代理链压平

当前阶段不需要换 WebSocket。

更重要的是：

1. SSE 首包必须能快速 flush
2. 静态资源不能在最后几 KB 卡死
3. 最好减少成单代理

理想部署形态优先级：

1. 浏览器 -> `nginx :2026` -> `FastAPI :8026`
2. 如果必须有外层 `Caddy`，则要明确验证：
   - SSE buffering
   - gzip / chunked transfer
   - static file 尾包传输
   - timeout / idle timeout

#### E. 增加版本与部署自证能力

建议 `healthz` 或 runtime snapshot 里直接暴露：

- 当前运行中的 `build_sha`
- `startup_ts`
- `service_version`

否则就会再次出现这次这种情况：

- 工作区代码是新的
- 线上进程还是旧的
- 页面现象却看起来像“前端随机坏掉”

### 5.3 一个更稳的目标架构图

```text
Browser
  -> nginx public origin
    -> static dist
    -> /api/runtime/snapshot
    -> /api/runtime/stream
      -> FastAPI runtime gateway
        -> validated snapshot builder
        -> last-known-good cache
        -> integrity flags
        -> runtime files + deployment config
```

如果后面要继续升级，再演进成：

```text
runtime files / Kafka / observability
  -> runtime projection builder
    -> materialized snapshot store
      -> FastAPI/SSE gateway
        -> Browser
```

这样浏览器拿到的是“已经被后端确认过的一等公民视图”，而不是每次请求都临场拼出来的一次性结果。

## 6. 当前问题的解决思路

### 6.1 已经在仓库里做掉的部分

2026-03-28 已在前端补上的保护有：

1. 如果 live snapshot 缺 `timeline/stageTelemetry`
   - 不再直接覆盖当前可用视图

2. 如果 SSE 长时间不发首包
   - 前端会进入 `degraded/fallback`
   - 不会无限等待并假装一切正常

3. `RuntimeVisualPanels` 和 `CompareMode` 已做动态切包
   - 首屏不再强制预加载 `echarts`

这些改动的意义是：

- 先止血
- 防止“坏 live 数据直接把页面拖崩”

### 6.2 还必须在部署/服务侧处理的部分

但真正要闭环，还必须做下面几件事：

1. 确认 `:8026` 实际运行的进程是否就是当前工作区代码
2. 重启并验证 `netops-ops-console-backend.service`
3. 检查 `Caddy -> nginx -> FastAPI` 链路对：
   - SSE flush
   - static file transfer
   - gzip / chunked / buffering
   的影响
4. 给 snapshot/healthz 增加版本自证字段
5. 让网关自己维护 last-known-good，而不是只靠前端兜底

## 7. 适合复盘和面试的讲法

这部分建议以后直接照着讲，不要把重点讲歪成“React 小问题”。

### 7.1 一句话版本

这个前端不是普通 dashboard，而是一个把 runtime 文件、告警流、AIOps 建议流和控制边界投影成过程型控制台的只读 runtime console。

### 7.2 架构取舍版本

项目早期我故意选了：

- `React + Vite + 本地状态`
- `FastAPI + SSE`
- `runtime files -> thin gateway -> browser`

因为这个阶段最重要的是把真实运行语义先映射清楚，而不是过早引入重型基础设施。

### 7.3 事故复盘版本

后面出现了一次非常典型的“前端没白屏，但语义已经坏掉”的问题：

1. 页面先用 demo fallback 起页
2. live snapshot 返回 `200`
3. 但实际缺少 lifecycle 所需的 `timeline/stageTelemetry`
4. 前端旧逻辑把“请求成功”误认为“数据可信”
5. 结果几秒后把一个好页面覆盖成了坏页面

同时线上还叠加了代理链的静态资源和 SSE 传输问题，导致公网入口一直转圈。

### 7.4 最有价值的工程结论

真正应该修的不是“把图表做炫一点”，而是：

- 把 runtime snapshot 当成受完整性约束的一等数据产品
- 建 last-known-good 语义
- 给服务和快照加版本自证
- 压平代理链，保证静态资源和 SSE 的传输稳定

这类问题很适合用来说明：

- 你不仅会写页面
- 也能从系统边界、数据契约、部署链路、可观测性角度排查问题

## 8. 结论

当前架构本身不是错误架构，它适合项目早期的语义探索和快速联调。

这次问题真正暴露的是：

1. fallback 语义没有分层
2. live snapshot 缺少后端完整性约束
3. 运行中服务缺少版本自证
4. 双代理链在静态资源和 SSE 上存在传输不稳定

因此下一阶段最正确的方向不是“把前端重写成更复杂的框架”，而是把它升级成：

- 有完整性标记的 runtime projection
- 有 last-known-good 语义的薄网关
- 有版本自证能力的部署链路
- 对静态资源和 SSE 传输更稳定的单一公网入口
