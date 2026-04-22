from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt

from core.aiops_agent.alert_reasoning_runtime.incident_window import build_incident_window_index


OUTPUT_PNG = Path("/data/Netops-causality-remediation/documentation/images/adaptive_windowing_explainer.png")


def _alert(alert_id: str, *, ts: datetime, device: str, scenario: str) -> dict:
    return {
        "alert_id": alert_id,
        "rule_id": "annotated_fault_v1",
        "severity": "warning",
        "alert_ts": ts.isoformat(),
        "dimensions": {
            "src_device_key": device,
            "fault_scenario": scenario,
        },
        "metrics": {
            "label_value": scenario,
            "annotation_confidence": 1.0,
        },
        "event_excerpt": {
            "src_device_key": device,
            "service": "lcore-telemetry",
        },
        "topology_context": {
            "src_device_key": device,
            "service": "lcore-telemetry",
            "path_signature": "shape-a|hop_core=2|hop_server=4|path_up=1",
            "hop_to_server": "4",
            "hop_to_core": "2",
            "downstream_dependents": "8",
            "path_up": "1",
        },
        "device_profile": {
            "src_device_key": device,
            "device_name": device,
            "device_role": "core_router",
        },
    }


def _sample_alerts() -> list[dict]:
    base = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)
    return [
        _alert("a1", ts=base + timedelta(seconds=0), device="CORE-R2", scenario="transient_fault"),
        _alert("a2", ts=base + timedelta(seconds=60), device="CORE-R3", scenario="transient_fault"),
        _alert("a3", ts=base + timedelta(seconds=120), device="CORE-R4", scenario="induced_fault"),
        _alert("a4", ts=base + timedelta(seconds=470), device="CORE-R5", scenario="transient_fault"),
        _alert("a5", ts=base + timedelta(seconds=530), device="CORE-R6", scenario="transient_fault"),
        _alert("a6", ts=base + timedelta(seconds=1200), device="CORE-R7", scenario="transient_fault"),
    ]


def main() -> None:
    alerts = _sample_alerts()
    base_ts = datetime.fromisoformat(str(alerts[0]["alert_ts"]).replace("Z", "+00:00"))
    configs = [
        ("fixed 5m buckets", {"window_sec": 300, "window_mode": "fixed", "max_window_sec": 300}),
        ("session gap 10m", {"window_sec": 600, "window_mode": "session", "max_window_sec": 900}),
        ("adaptive gap", {"window_sec": 600, "window_mode": "adaptive", "max_window_sec": 900}),
    ]
    colors = ["#9ecae1", "#fdae6b", "#a1d99b", "#fdd0a2"]

    fig, axes = plt.subplots(len(configs), 1, figsize=(11, 5.8), sharex=True)
    for axis, (title, kwargs) in zip(axes, configs):
        windows, _ = build_incident_window_index(alerts, **kwargs)
        for idx, window in enumerate(windows):
            start = _minutes_since(base_ts, str(window.get("window_start") or ""))
            end = _minutes_since(base_ts, str(window.get("window_end") or ""))
            axis.axvspan(start, max(end, start + 0.05), color=colors[idx % len(colors)], alpha=0.55)
            axis.text(
                (start + max(end, start + 0.05)) / 2.0,
                0.82,
                f"W{idx + 1}",
                ha="center",
                va="center",
                fontsize=9,
                color="#1f1f1f",
            )
        for alert in alerts:
            minute = _minutes_since(base_ts, str(alert.get("alert_ts") or ""))
            scenario = str((alert.get("dimensions") or {}).get("fault_scenario") or "")
            axis.plot(
                minute,
                0.45,
                marker="o" if scenario == "induced_fault" else "s",
                color="#111111",
                markersize=6,
            )
            axis.text(minute, 0.2, str(alert.get("alert_id") or ""), ha="center", va="center", fontsize=8)

        summary = f"{len(windows)} windows"
        if kwargs["window_mode"] == "adaptive":
            gaps = sorted({int(window.get("group_idle_gap_sec") or 0) for window in windows})
            summary += f", learned gaps {gaps}s"
        axis.set_title(f"{title}: {summary}", loc="left", fontsize=11)
        axis.set_ylim(0.0, 1.0)
        axis.set_yticks([])
        axis.grid(axis="x", alpha=0.2)

    axes[-1].set_xlabel("Minutes from first alert")
    axes[-1].set_xlim(-0.5, 22.0)
    fig.suptitle("Fixed buckets, session windows, and adaptive session windows on one alert burst", y=0.98, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PNG, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _minutes_since(base_ts: datetime, raw_ts: str) -> float:
    ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
    return (ts - base_ts).total_seconds() / 60.0


if __name__ == "__main__":
    main()
