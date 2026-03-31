# FortiGate Parsed Output Sample / FortiGate 解析输出样例

This page isolates the parsed-JSONL output table from the root README.
It documents the stable event contract produced by `edge/fortigate-ingest` before the data is forwarded into the shared core pipeline.

这份文档承接根 README 中移出的“parsed JSONL 输出样例表”。
它描述的是 `edge/fortigate-ingest` 产出的结构化事件契约，也就是事实事件进入共享核心链路之前的稳定输出形态。

## Scope / 作用边界

- This is a parser-output contract note, not a claim that the current workspace mounts live parsed files.
- The sample below is a repository-aligned parsed event example used to document stable field semantics.
- For current mounted runtime facts on alerts and suggestions, use the root README and project-state documents.

- 这是一份 parser 输出契约说明，不代表当前工作区挂载了 live parsed 文件。
- 下面的样例用于记录稳定字段语义，与仓库当前 parser 契约保持一致。
- 如果要看当前机器上真实挂载的 alert / suggestion 运行态，请看根 README 和项目状态文档。

## Parsed JSONL Sample / 解析后的 JSONL 样例

```json
{"schema_version":1,"event_id":"d811b6b7c362dd6367f3736a19bc9ade","host":"_gateway","event_ts":"2026-01-15T16:49:21+01:00","type":"traffic","subtype":"forward","level":"notice","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","vd":"root","action":"deny","policyid":0,"policytype":"policy","sessionid":1066028432,"proto":17,"service":"udp/3702","srcip":"192.168.1.133","srcport":3702,"srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":3702,"dstintf":"LAN2","dstintfrole":"lan","sentbyte":0,"rcvdbyte":0,"sentpkt":0,"rcvdpkt":null,"bytes_total":0,"pkts_total":0,"parse_status":"ok","logid":"0000000013","eventtime":"1768492161732986577","tz":"+0100","logdesc":null,"user":null,"ui":null,"method":null,"status":null,"reason":null,"msg":null,"trandisp":"noop","app":null,"appcat":"unscanned","duration":0,"srcname":null,"srccountry":"Reserved","dstcountry":"Reserved","osname":null,"srcswversion":null,"srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":0,"srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P","srchwmodel":null,"src_device_key":"b4:4c:3b:c1:29:c1","kv_subset":{"date":"2026-01-15","time":"16:49:21","tz":"+0100","eventtime":"1768492161732986577","logid":"0000000013","type":"traffic","subtype":"forward","level":"notice","vd":"root","action":"deny","policyid":"0","policytype":"policy","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","sessionid":"1066028432","proto":"17","service":"udp/3702","srcip":"192.168.1.133","srcport":"3702","srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":"3702","dstintf":"LAN2","dstintfrole":"lan","trandisp":"noop","duration":"0","sentbyte":"0","rcvdbyte":"0","sentpkt":"0","appcat":"unscanned","dstcountry":"Reserved","srccountry":"Reserved","srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":"0","srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P"},"ingest_ts":"2026-02-16T19:59:59.808411+00:00","source":{"path":"/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz","inode":6160578,"offset":null}}
```

## Output Field Table / 输出字段表

| Field Name | Sample Value | Purpose / 用途 |
| --- | --- | --- |
| `source.path` | `/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz` | Source file path for audit and replay / 用于审计和回放定位的源文件路径 |
| `source.inode` | `6160578` | File identity / 文件身份标识 |
| `source.offset` | `null` | Offset within source file / 源文件偏移 |
| `schema_version` | `1` | Output schema version / 输出 schema 版本 |
| `event_id` | `d811b6b7c362dd6367f3736a19bc9ade` | Stable event ID for deduplication / 稳定事件 ID，用于去重 |
| `host` | `_gateway` | Preserved syslog host / 保留 syslog 主机名 |
| `event_ts` | `2026-01-15T16:49:21+01:00` | Normalized event time / 标准化事件时间 |
| `type` | `traffic` | Primary log category / 一级日志类别 |
| `subtype` | `forward` | Log subtype / 日志子类型 |
| `level` | `notice` | Event level / 事件级别 |
| `devname` | `DAHUA_FORTIGATE` | Firewall device name / 防火墙设备名 |
| `devid` | `FG100ETK20014183` | Firewall device ID / 防火墙设备 ID |
| `vd` | `root` | VDOM / 虚拟域 |
| `action` | `deny` | Enforcement result / 策略动作结果 |
| `policyid` | `0` | Policy ID / 策略 ID |
| `policytype` | `policy` | Policy type / 策略类型 |
| `sessionid` | `1066028432` | Session correlation key / 会话关联键 |
| `proto` | `17` | Protocol number / 协议号 |
| `service` | `udp/3702` | Service label / 服务标签 |
| `srcip` | `192.168.1.133` | Source IP / 源 IP |
| `srcport` | `3702` | Source port / 源端口 |
| `srcintf` | `fortilink` | Source interface / 源接口 |
| `srcintfrole` | `lan` | Source interface role / 源接口角色 |
| `dstip` | `192.168.2.108` | Destination IP / 目标 IP |
| `dstport` | `3702` | Destination port / 目标端口 |
| `dstintf` | `LAN2` | Destination interface / 目标接口 |
| `dstintfrole` | `lan` | Destination interface role / 目标接口角色 |
| `sentbyte` | `0` | Sent bytes / 发送字节数 |
| `rcvdbyte` | `0` | Received bytes / 接收字节数 |
| `sentpkt` | `0` | Sent packets / 发送包数 |
| `rcvdpkt` | `null` | Received packets / 接收包数 |
| `bytes_total` | `0` | Derived total bytes / 派生总字节数 |
| `pkts_total` | `0` | Derived total packets / 派生总包数 |
| `parse_status` | `ok` | Parse result / 解析状态 |
| `logid` | `0000000013` | FortiGate log ID / FortiGate 日志 ID |
| `eventtime` | `1768492161732986577` | Native high-precision event time / 原生日志高精度时间 |
| `tz` | `+0100` | Timezone / 时区 |
| `logdesc` | `null` | Native log description / 原生日志描述 |
| `user` | `null` | User field / 用户字段 |
| `ui` | `null` | UI or entry field / UI 或入口字段 |
| `method` | `null` | Method field / 方法字段 |
| `status` | `null` | Status field / 状态字段 |
| `reason` | `null` | Reason field / 原因字段 |
| `msg` | `null` | Message field / 文本消息字段 |
| `trandisp` | `noop` | Transport/processing status / 传输或处理状态 |
| `app` | `null` | Application identification / 应用识别 |
| `appcat` | `unscanned` | Application category state / 应用分类状态 |
| `duration` | `0` | Session duration / 会话时长 |
| `srcname` | `null` | Source endpoint name / 源端点名称 |
| `srccountry` | `Reserved` | Source country/address classification / 源国家或地址空间分类 |
| `dstcountry` | `Reserved` | Destination country/address classification / 目标国家或地址空间分类 |
| `osname` | `null` | Operating system name / 操作系统名称 |
| `srcswversion` | `null` | Software version / 软件版本 |
| `srcmac` | `b4:4c:3b:c1:29:c1` | Source MAC / 源 MAC |
| `mastersrcmac` | `b4:4c:3b:c1:29:c1` | Master source MAC / 主源 MAC |
| `srcserver` | `0` | Device role hint / 设备角色线索 |
| `srchwvendor` | `Dahua` | Hardware vendor / 设备厂商 |
| `devtype` | `IP Camera` | Device type / 设备类型 |
| `srcfamily` | `IP Camera` | Device family / 设备家族 |
| `srchwversion` | `DHI-VTO4202FB-P` | Hardware version / 硬件版本 |
| `srchwmodel` | `null` | Hardware model / 硬件型号 |
| `src_device_key` | `b4:4c:3b:c1:29:c1` | Normalized device key / 标准化设备键 |
| `kv_subset` | `{...}` | Compact raw KV snapshot / 紧凑原始 KV 快照 |
| `ingest_ts` | `2026-02-16T19:59:59.808411+00:00` | Ingest output timestamp / ingest 输出时间 |
| `source` | `{"path":"...","inode":6160578,"offset":null}` | Source metadata object / 源元数据对象 |

## Why This Table Matters / 为什么这张表重要

- It shows the exact contract that later stages depend on for replay, grouping, alerting, and localization.
- It explains why the edge layer emits facts instead of forwarding opaque text.
- It makes the jump from raw vendor log to shared core event object explicit.

- 它明确了后续回放、聚合、告警和定位依赖的真实字段契约。
- 它解释了为什么 edge 层输出的是 facts，而不是不透明文本。
- 它把“厂商原始日志”到“核心共享事件对象”的转换关系写清楚了。

## Related Docs / 相关文档

- [FortiGate input field analysis](./FORTIGATE_INPUT_FIELD_ANALYSIS.md)
- [FortiGate ingest field reference](./FORTIGATE_INGEST_FIELD_REFERENCE.md)
