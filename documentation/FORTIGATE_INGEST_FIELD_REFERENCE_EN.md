# FortiGate Ingest Field Reference

This note is now a short landing page for the FortiGate ingest-side contract.
The full raw-input and parsed-output tables live in dedicated documents:

- [FortiGate input field analysis](./FORTIGATE_INPUT_FIELD_ANALYSIS.md)
- [FortiGate parsed JSONL output sample](./FORTIGATE_PARSED_OUTPUT_SAMPLE.md)

Use this page when you only need the contract boundary:

| Concern | Representative fields | Why it matters |
| --- | --- | --- |
| Replay and provenance | `source.path`, `source.inode`, `source.offset`, `ingest_ts` | safe resume, audit, replay |
| Stable identity | `event_id`, `src_device_key`, `sessionid` | deduplication, grouping, correlation |
| Normalized time | `event_ts`, `eventtime`, `tz` | deterministic downstream windows |
| Network semantics | `srcip`, `srcport`, `dstip`, `dstport`, `proto`, `service` | rule evaluation and localization |
| Decision context | `action`, `policyid`, `policytype`, `level`, `subtype` | enforcement outcome and traffic class |
| Asset hints | `srcmac`, `mastersrcmac`, `srchwvendor`, `devtype`, `srcfamily`, `srcswversion` | device profiling and attribution |
| Trace-back payload | `parse_status`, `kv_subset` | schema validation and parser audit |

For system-level context, start from [PROJECT_STATE_EN.md](./PROJECT_STATE_EN.md).
