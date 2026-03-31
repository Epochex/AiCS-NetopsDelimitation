# FortiGate Input Field Analysis / FortiGate 原始输入字段分析

This page keeps the raw-input field table out of the root README.
It documents the FortiGate-side input contract that `edge/fortigate-ingest` is designed to parse before the data becomes structured JSONL.

这份文档专门承接根 README 中移出的“原始输入字段表”。
它描述的是 `edge/fortigate-ingest` 面对的 FortiGate 原始输入契约，而不是 core 侧已经结构化后的事件对象。

## Scope / 作用边界

- This is an input-side contract note, not a live-runtime freshness claim.
- The current workspace mounts `/data/netops-runtime` but does not expose a live `/data/fortigate-runtime` volume.
- The sample below is therefore a parser-aligned representative FortiGate raw line already used in repository field docs.

- 这是一份输入契约说明，不是“当前 live runtime 新鲜度”的声明。
- 当前工作区挂载了 `/data/netops-runtime`，但没有暴露 live 的 `/data/fortigate-runtime` 卷。
- 因此下面的样例使用的是仓库里已经对齐 parser 契约的代表性 FortiGate 原始日志行。

## Real Raw Sample / 原始日志样例

```text
Feb 21 15:45:27 _gateway date=2026-02-21 time=15:45:26 devname="DAHUA_FORTIGATE" devid="FG100ETK20014183" logid="0001000014" type="traffic" subtype="local" level="notice" vd="root" eventtime=1771685127249713472 tz="+0100" srcip=192.168.16.41 srcname="es-73847E56DA65" srcport=48689 srcintf="LACP" srcintfrole="lan" dstip=255.255.255.255 dstport=48689 dstintf="unknown0" dstintfrole="undefined" sessionid=1211202700 proto=17 action="deny" policyid=0 policytype="local-in-policy" service="udp/48689" dstcountry="Reserved" srccountry="Reserved" trandisp="noop" app="udp/48689" duration=0 sentbyte=0 rcvdbyte=0 sentpkt=0 appcat="unscanned" srchwvendor="Samsung" devtype="Phone" srcfamily="Galaxy" osname="Android" srcswversion="16" mastersrcmac="78:66:9d:a3:4f:51" srcmac="78:66:9d:a3:4f:51" srcserver=0
```

## Input Field Table / 输入字段表

| Field Name | Sample Value | Purpose / 用途 |
| --- | --- | --- |
| `syslog_month` | `Feb` | Syslog header month / syslog 头部月份 |
| `syslog_day` | `21` | Syslog header day / syslog 头部日期 |
| `syslog_time` | `15:45:27` | Syslog receive time / syslog 接收时间 |
| `host` | `_gateway` | Syslog sender hostname / syslog 发送主机 |
| `date` | `2026-02-21` | FortiGate business date / FortiGate 业务日期 |
| `time` | `15:45:26` | FortiGate business time / FortiGate 业务时间 |
| `devname` | `DAHUA_FORTIGATE` | Firewall device name / 防火墙设备名 |
| `devid` | `FG100ETK20014183` | Firewall unique device ID / 防火墙唯一设备 ID |
| `logid` | `0001000014` | FortiGate log type ID / FortiGate 日志类型 ID |
| `type` | `traffic` | Primary log category / 一级日志类别 |
| `subtype` | `local` | Traffic subtype / 流量子类型 |
| `level` | `notice` | Event level / 事件级别 |
| `vd` | `root` | VDOM / 虚拟域 |
| `eventtime` | `1771685127249713472` | Native high-precision event timestamp / 原生日志高精度时间戳 |
| `tz` | `+0100` | Timezone / 时区 |
| `srcip` | `192.168.16.41` | Source IP / 源 IP |
| `srcname` | `es-73847E56DA65` | Source endpoint name / 源端点名称 |
| `srcport` | `48689` | Source port / 源端口 |
| `srcintf` | `LACP` | Source interface / 源接口 |
| `srcintfrole` | `lan` | Source interface role / 源接口角色 |
| `dstip` | `255.255.255.255` | Destination IP / 目标 IP |
| `dstport` | `48689` | Destination port / 目标端口 |
| `dstintf` | `unknown0` | Destination interface / 目标接口 |
| `dstintfrole` | `undefined` | Destination interface role / 目标接口角色 |
| `sessionid` | `1211202700` | Session correlation key / 会话关联键 |
| `proto` | `17` | Protocol number / 协议号 |
| `action` | `deny` | Enforcement result / 策略动作结果 |
| `policyid` | `0` | Policy ID / 策略 ID |
| `policytype` | `local-in-policy` | Policy type / 策略类型 |
| `service` | `udp/48689` | Service label / 服务标签 |
| `dstcountry` | `Reserved` | Destination country classification / 目标国家或地址空间分类 |
| `srccountry` | `Reserved` | Source country classification / 源国家或地址空间分类 |
| `trandisp` | `noop` | Transport/processing status / 传输或处理状态 |
| `app` | `udp/48689` | Application identification result / 应用识别结果 |
| `duration` | `0` | Session duration / 会话时长 |
| `sentbyte` | `0` | Sent bytes / 发送字节数 |
| `rcvdbyte` | `0` | Received bytes / 接收字节数 |
| `sentpkt` | `0` | Sent packets / 发送包数 |
| `appcat` | `unscanned` | Application category state / 应用分类状态 |
| `srchwvendor` | `Samsung` | Source hardware vendor / 源设备厂商 |
| `devtype` | `Phone` | Device type / 设备类型 |
| `srcfamily` | `Galaxy` | Device family / 设备家族 |
| `osname` | `Android` | Operating system name / 操作系统名称 |
| `srcswversion` | `16` | OS/software version / 软件或系统版本 |
| `mastersrcmac` | `78:66:9d:a3:4f:51` | Master source MAC / 主源 MAC |
| `srcmac` | `78:66:9d:a3:4f:51` | Source MAC / 源 MAC |
| `srcserver` | `0` | Device role hint / 设备角色线索 |

## Why This Table Matters / 为什么这张表重要

- It shows what the edge parser must normalize before the event is safe to share with the core.
- It makes clear why ingest is more than "tail a file and forward lines".
- It explains where later device profiling, replay safety, and alert localization clues originate.

- 它解释了 edge parser 在把事件交给 core 之前到底需要规范化什么。
- 它说明 ingest 不是“盯文件然后原样转发”。
- 它把后续设备画像、回放安全和 incident 定位线索的来源讲清楚了。

## Related Docs / 相关文档

- [FortiGate parsed JSONL output sample](./FORTIGATE_PARSED_OUTPUT_SAMPLE.md)
- [FortiGate ingest field reference](./FORTIGATE_INGEST_FIELD_REFERENCE.md)
