# FortiGate Ingest Field Reference / FortiGate 接入字段参考

This page keeps the field-by-field schema reference out of the root `README.md`.
Use it when you need to look up exact FortiGate input fields or the parsed JSONL output contract.

这份文档把逐字段 schema 说明从根 `README.md` 中拆了出来。
当你需要查 FortiGate 原始输入字段，或者解析后 JSONL 的输出契约时，优先看这里。

- [Input field analysis / 输入字段说明](#input-field-analysis--输入字段说明)
- [Output field analysis / 输出字段说明](#output-field-analysis--输出字段说明)

字段名本身保持英文，不做翻译，因为它们需要和真实日志、JSON key、ClickHouse 字段以及代码中的 schema 保持一一对应。

## Input Field Analysis / 输入字段说明

### Real Raw Sample / 原始日志样例

```text
Feb 21 15:45:27 _gateway date=2026-02-21 time=15:45:26 devname="DAHUA_FORTIGATE" devid="FG100ETK20014183" logid="0001000014" type="traffic" subtype="local" level="notice" vd="root" eventtime=1771685127249713472 tz="+0100" srcip=192.168.16.41 srcname="es-73847E56DA65" srcport=48689 srcintf="LACP" srcintfrole="lan" dstip=255.255.255.255 dstport=48689 dstintf="unknown0" dstintfrole="undefined" sessionid=1211202700 proto=17 action="deny" policyid=0 policytype="local-in-policy" service="udp/48689" dstcountry="Reserved" srccountry="Reserved" trandisp="noop" app="udp/48689" duration=0 sentbyte=0 rcvdbyte=0 sentpkt=0 appcat="unscanned" srchwvendor="Samsung" devtype="Phone" srcfamily="Galaxy" osname="Android" srcswversion="16" mastersrcmac="78:66:9d:a3:4f:51" srcmac="78:66:9d:a3:4f:51" srcserver=0
```

### Input field analysis / 输入字段逐项说明

The table below keeps the original schema keys intact. The `Purpose / 用途` column explains why each field matters in downstream parsing, correlation, and localization.

| Field Name     | Sample Value          | Purpose / 用途                                            |
| -------------- | --------------------- | --------------------------------------------------------- |
| `syslog_month` | `Feb`                 | Syslog header time (month)                                |
| `syslog_day`   | `21`                  | Syslog header time (day)                                  |
| `syslog_time`  | `15:45:27`            | Syslog receive time (second-level)                        |
| `host`         | `_gateway`            | Syslog sender hostname                                    |
| `date`         | `2026-02-21`          | FortiGate event date (business time)                      |
| `time`         | `15:45:26`            | FortiGate event time (business time)                      |
| `devname`      | `DAHUA_FORTIGATE`     | Firewall device name                                      |
| `devid`        | `FG100ETK20014183`    | Firewall unique device ID                                 |
| `logid`        | `0001000014`          | FortiGate log type ID                                     |
| `type`         | `traffic`             | Log primary category (traffic)                            |
| `subtype`      | `local`               | Log subtype (local-plane traffic)                         |
| `level`        | `notice`              | Event level                                               |
| `vd`           | `root`                | VDOM name                                                 |
| `eventtime`    | `1771685127249713472` | High-precision native event timestamp                     |
| `tz`           | `+0100`               | Time zone                                                 |
| `srcip`        | `192.168.16.41`       | Source IP                                                 |
| `srcname`      | `es-73847E56DA65`     | Source name / endpoint identifier                         |
| `srcport`      | `48689`               | Source port                                               |
| `srcintf`      | `LACP`                | Source interface                                          |
| `srcintfrole`  | `lan`                 | Source interface role                                     |
| `dstip`        | `255.255.255.255`     | Destination IP (broadcast address)                        |
| `dstport`      | `48689`               | Destination port                                          |
| `dstintf`      | `unknown0`            | Destination interface (local-plane / special target clue) |
| `dstintfrole`  | `undefined`           | Destination interface role                                |
| `sessionid`    | `1211202700`          | Session ID (correlation key)                              |
| `proto`        | `17`                  | Protocol number (UDP)                                     |
| `action`       | `deny`                | Action result (deny)                                      |
| `policyid`     | `0`                   | Policy ID                                                 |
| `policytype`   | `local-in-policy`     | Matched policy type (local-plane)                         |
| `service`      | `udp/48689`           | Service / port label                                      |
| `dstcountry`   | `Reserved`            | Destination country (reserved address space)              |
| `srccountry`   | `Reserved`            | Source country (reserved address space)                   |
| `trandisp`     | `noop`                | Transport / processing status information                 |
| `app`          | `udp/48689`           | Application identification result (port-level)            |
| `duration`     | `0`                   | Session duration                                          |
| `sentbyte`     | `0`                   | Sent bytes                                                |
| `rcvdbyte`     | `0`                   | Received bytes                                            |
| `sentpkt`      | `0`                   | Sent packets                                              |
| `appcat`       | `unscanned`           | Application category status                               |
| `srchwvendor`  | `Samsung`             | Source hardware vendor (asset profile)                    |
| `devtype`      | `Phone`               | Device type (asset profile)                               |
| `srcfamily`    | `Galaxy`              | Device family (asset profile)                             |
| `osname`       | `Android`             | OS name (asset profile)                                   |
| `srcswversion` | `16`                  | OS/software version (asset profile)                       |
| `mastersrcmac` | `78:66:9d:a3:4f:51`   | Master source MAC (device identity normalization clue)    |
| `srcmac`       | `78:66:9d:a3:4f:51`   | Source MAC (device identity normalization clue)           |
| `srcserver`    | `0`                   | Device role hint (endpoint / non-server)                  |

## Output Field Analysis / 输出字段说明

### Parsed JSONL Sample / 解析后的 JSONL 样例

```text
{"schema_version":1,"event_id":"d811b6b7c362dd6367f3736a19bc9ade","host":"_gateway","event_ts":"2026-01-15T16:49:21+01:00","type":"traffic","subtype":"forward","level":"notice","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","vd":"root","action":"deny","policyid":0,"policytype":"policy","sessionid":1066028432,"proto":17,"service":"udp/3702","srcip":"192.168.1.133","srcport":3702,"srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":3702,"dstintf":"LAN2","dstintfrole":"lan","sentbyte":0,"rcvdbyte":0,"sentpkt":0,"rcvdpkt":null,"bytes_total":0,"pkts_total":0,"parse_status":"ok","logid":"0000000013","eventtime":"1768492161732986577","tz":"+0100","logdesc":null,"user":null,"ui":null,"method":null,"status":null,"reason":null,"msg":null,"trandisp":"noop","app":null,"appcat":"unscanned","duration":0,"srcname":null,"srccountry":"Reserved","dstcountry":"Reserved","osname":null,"srcswversion":null,"srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":0,"srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P","srchwmodel":null,"src_device_key":"b4:4c:3b:c1:29:c1","kv_subset":{"date":"2026-01-15","time":"16:49:21","tz":"+0100","eventtime":"1768492161732986577","logid":"0000000013","type":"traffic","subtype":"forward","level":"notice","vd":"root","action":"deny","policyid":"0","policytype":"policy","devname":"DAHUA_FORTIGATE","devid":"FG100ETK20014183","sessionid":"1066028432","proto":"17","service":"udp/3702","srcip":"192.168.1.133","srcport":"3702","srcintf":"fortilink","srcintfrole":"lan","dstip":"192.168.2.108","dstport":"3702","dstintf":"LAN2","dstintfrole":"lan","trandisp":"noop","duration":"0","sentbyte":"0","rcvdbyte":"0","sentpkt":"0","appcat":"unscanned","dstcountry":"Reserved","srccountry":"Reserved","srcmac":"b4:4c:3b:c1:29:c1","mastersrcmac":"b4:4c:3b:c1:29:c1","srcserver":"0","srchwvendor":"Dahua","devtype":"IP Camera","srcfamily":"IP Camera","srchwversion":"DHI-VTO4202FB-P"},"ingest_ts":"2026-02-16T19:59:59.808411+00:00","source":{"path":"/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz","inode":6160578,"offset":null}}
```

### Output field analysis / 输出字段逐项说明

The parsed schema below keeps the normalized event contract intact. The `Purpose / 用途` column describes how each field is used for replay, aggregation, auditing, and device-level localization.

| Field Name       | Sample Value                                                     | Purpose / 用途                                                         |
| ---------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `source.path`    | `/data/fortigate-runtime/input/fortigate.log-20260130-000004.gz` | Source file path (rotated file localization)                           |
| `source.inode`   | `6160578`                                                        | File inode (file identity)                                             |
| `source.offset`  | `null`                                                           | Offset (commonly null for compressed files)                            |
| `schema_version` | `1`                                                              | Output schema version                                                  |
| `event_id`       | `d811b6b7c362dd6367f3736a19bc9ade`                               | Unique event ID (deduplication / idempotency)                          |
| `host`           | `_gateway`                                                       | Preserved syslog host                                                  |
| `event_ts`       | `2026-01-15T16:49:21+01:00`                                      | Normalized event time (primary field for downstream windowing/sorting) |
| `type`           | `traffic`                                                        | Log primary category                                                   |
| `subtype`        | `forward`                                                        | Log subtype (forwarded traffic)                                        |
| `level`          | `notice`                                                         | Event level                                                            |
| `devname`        | `DAHUA_FORTIGATE`                                                | Firewall device name                                                   |
| `devid`          | `FG100ETK20014183`                                               | Firewall device ID                                                     |
| `vd`             | `root`                                                           | VDOM                                                                   |
| `action`         | `deny`                                                           | Action result                                                          |
| `policyid`       | `0`                                                              | Policy ID                                                              |
| `policytype`     | `policy`                                                         | Policy type (regular forwarding policy)                                |
| `sessionid`      | `1066028432`                                                     | Session correlation key                                                |
| `proto`          | `17`                                                             | Protocol number (UDP)                                                  |
| `service`        | `udp/3702`                                                       | Service / port label                                                   |
| `srcip`          | `192.168.1.133`                                                  | Source IP                                                              |
| `srcport`        | `3702`                                                           | Source port                                                            |
| `srcintf`        | `fortilink`                                                      | Source interface                                                       |
| `srcintfrole`    | `lan`                                                            | Source interface role                                                  |
| `dstip`          | `192.168.2.108`                                                  | Destination IP                                                         |
| `dstport`        | `3702`                                                           | Destination port                                                       |
| `dstintf`        | `LAN2`                                                           | Destination interface                                                  |
| `dstintfrole`    | `lan`                                                            | Destination interface role                                             |
| `sentbyte`       | `0`                                                              | Sent bytes                                                             |
| `rcvdbyte`       | `0`                                                              | Received bytes                                                         |
| `sentpkt`        | `0`                                                              | Sent packets                                                           |
| `rcvdpkt`        | `null`                                                           | Received packets (nullable)                                            |
| `bytes_total`    | `0`                                                              | Derived total bytes (aggregation-friendly)                             |
| `pkts_total`     | `0`                                                              | Derived total packets (aggregation-friendly)                           |
| `parse_status`   | `ok`                                                             | Parsing status                                                         |
| `logid`          | `0000000013`                                                     | FortiGate log ID                                                       |
| `eventtime`      | `1768492161732986577`                                            | Native high-precision event time                                       |
| `tz`             | `+0100`                                                          | Time zone                                                              |
| `logdesc`        | `null`                                                           | Native log description (nullable)                                      |
| `user`           | `null`                                                           | User field (nullable)                                                  |
| `ui`             | `null`                                                           | UI/entry field (nullable)                                              |
| `method`         | `null`                                                           | Method/action field (nullable)                                         |
| `status`         | `null`                                                           | Status field (nullable)                                                |
| `reason`         | `null`                                                           | Reason field (nullable)                                                |
| `msg`            | `null`                                                           | Text message field (nullable)                                          |
| `trandisp`       | `noop`                                                           | Transport/processing status information                                |
| `app`            | `null`                                                           | Application identification (nullable)                                  |
| `appcat`         | `unscanned`                                                      | Application category status                                            |
| `duration`       | `0`                                                              | Session duration                                                       |
| `srcname`        | `null`                                                           | Source endpoint name (nullable)                                        |
| `srccountry`     | `Reserved`                                                       | Source country/address-space classification                            |
| `dstcountry`     | `Reserved`                                                       | Destination country/address-space classification                       |
| `osname`         | `null`                                                           | OS name (nullable)                                                     |
| `srcswversion`   | `null`                                                           | Software/OS version (nullable)                                         |
| `srcmac`         | `b4:4c:3b:c1:29:c1`                                              | Source MAC                                                             |
| `mastersrcmac`   | `b4:4c:3b:c1:29:c1`                                              | Master source MAC                                                      |
| `srcserver`      | `0`                                                              | Device role hint                                                       |
| `srchwvendor`    | `Dahua`                                                          | Hardware vendor (asset profile)                                        |
| `devtype`        | `IP Camera`                                                      | Device type (asset profile)                                            |
| `srcfamily`      | `IP Camera`                                                      | Device family (asset profile)                                          |
| `srchwversion`   | `DHI-VTO4202FB-P`                                                | Hardware model/version (asset profile)                                 |
| `srchwmodel`     | `null`                                                           | Hardware model field (nullable)                                        |
| `src_device_key` | `b4:4c:3b:c1:29:c1`                                              | Normalized device key (core asset-baseline key)                        |
| `kv_subset`      | `{...}`                                                          | Raw KV subset snapshot (trace-back / validation / schema extension)    |
| `ingest_ts`      | `2026-02-16T19:59:59.808411+00:00`                               | Ingest output timestamp                                                |
| `source`         | `{"path":"...","inode":6160578,"offset":null}`                   | Input source metadata (audit / replay localization)                    |
