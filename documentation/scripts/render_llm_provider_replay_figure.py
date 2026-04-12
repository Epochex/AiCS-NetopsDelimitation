from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_SUMMARY = Path("/data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.json")
DEFAULT_EVENTS = Path("/data/netops-runtime/LCORE-D/work/llm-provider-replay-events.jsonl")
DEFAULT_OUTPUT = Path("/data/netops-runtime/LCORE-D/work/llm-provider-replay-summary.png")
HTML_PATH = Path("/tmp/netops_llm_provider_replay_figure.html")
WIDTH = 1700
HEIGHT = 560


def _load_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _cumulative_series(events: list[dict[str, Any]], max_points: int = 180) -> dict[str, list[float]]:
    total = len(events)
    if total == 0:
        return {"x": [0], "invoke_all": [0], "gated": [0]}
    stride = max(total // max_points, 1)
    xs: list[float] = [0]
    invoke_all: list[float] = [0]
    gated: list[float] = [0]
    gated_count = 0
    for idx, event in enumerate(events, start=1):
        if event.get("should_invoke_llm"):
            gated_count += 1
        if idx % stride == 0 or idx == total:
            xs.append(idx)
            invoke_all.append(idx)
            gated.append(gated_count)
    return {"x": xs, "invoke_all": invoke_all, "gated": gated}


def render_html(summary: dict[str, Any], events: list[dict[str, Any]]) -> str:
    payload = {
        "summary": summary,
        "series": _cumulative_series(events),
        "width": WIDTH,
        "height": HEIGHT,
    }
    payload_json = json.dumps(payload, ensure_ascii=True)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: {WIDTH}px;
      height: {HEIGHT}px;
      overflow: hidden;
      background: white;
    }}
    canvas {{
      display: block;
      width: {WIDTH}px;
      height: {HEIGHT}px;
    }}
  </style>
</head>
<body>
<canvas id="figure" width="{WIDTH}" height="{HEIGHT}"></canvas>
<script>
const data = {payload_json};
const ctx = document.getElementById('figure').getContext('2d');

function line(x1, y1, x2, y2, color = '#111', width = 1, dash = []) {{
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
}}

function rect(x, y, w, h, fill, stroke = null) {{
  ctx.save();
  ctx.fillStyle = fill;
  ctx.fillRect(x, y, w, h);
  if (stroke) {{
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, w, h);
  }}
  ctx.restore();
}}

function text(value, x, y, opts = {{}}) {{
  ctx.save();
  const size = opts.size || 16;
  const weight = opts.weight || 'normal';
  const family = opts.family || 'Times New Roman, Times, serif';
  ctx.font = `${{weight}} ${{size}}px ${{family}}`;
  ctx.fillStyle = opts.color || '#111';
  ctx.textAlign = opts.align || 'left';
  ctx.textBaseline = opts.baseline || 'alphabetic';
  if (opts.rotate) {{
    ctx.translate(x, y);
    ctx.rotate(opts.rotate);
    ctx.fillText(value, 0, 0);
  }} else {{
    ctx.fillText(value, x, y);
  }}
  ctx.restore();
}}

function xScale(value, min, max, left, right) {{
  return left + (value - min) / Math.max(max - min, 1) * (right - left);
}}

function yScale(value, min, max, top, bottom) {{
  return bottom - (value - min) / Math.max(max - min, 1) * (bottom - top);
}}

function drawAxes(left, top, right, bottom, yTicks, yMin, yMax, yLabel) {{
  line(left, top, left, bottom, '#111', 1.2);
  line(left, bottom, right, bottom, '#111', 1.2);
  line(left, top, right, top, '#111', 0.9);
  line(right, top, right, bottom, '#111', 0.9);
  for (const tick of yTicks) {{
    const y = yScale(tick, yMin, yMax, top, bottom);
    line(left, y, right, y, '#9a9a9a', 0.9, [2, 4]);
    text(String(tick), left - 8, y + 5, {{size: 14, align: 'right'}});
  }}
  text(yLabel, left - 42, (top + bottom) / 2, {{size: 18, rotate: -Math.PI / 2, align: 'center'}});
}}

function marker(x, y, color, shape = 'circle') {{
  ctx.save();
  ctx.fillStyle = 'white';
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  if (shape === 'diamond') {{
    ctx.moveTo(x, y - 6);
    ctx.lineTo(x + 7, y);
    ctx.lineTo(x, y + 6);
    ctx.lineTo(x - 7, y);
    ctx.closePath();
  }} else {{
    ctx.arc(x, y, 5, 0, Math.PI * 2);
  }}
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}}

function drawPanelA() {{
  const left = 95, top = 92, right = 625, bottom = 388;
  const total = data.summary.alerts_scanned || 1;
  const maxY = data.summary.planned_invoke_all_calls || total;
  text('(a) Cumulative external-call pressure', 360, 38, {{size: 23, weight: 'bold', align: 'center'}});
  drawAxes(left, top, right, bottom, [0, 350, 700, 1050, 1400], 0, Math.max(maxY, 1400), 'LLM calls');
  for (const tick of [0, 325, 650, 975, 1302]) {{
    const x = xScale(tick, 0, total, left, right);
    line(x, top, x, bottom, '#c8c8c8', 0.7, [2, 5]);
    text(String(tick), x, bottom + 25, {{size: 14, align: 'center'}});
  }}
  text('alert stream index', (left + right) / 2, bottom + 57, {{size: 18, align: 'center'}});

  function drawSeries(values, color, shape) {{
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    values.forEach((v, i) => {{
      const x = xScale(data.series.x[i], 0, total, left, right);
      const y = yScale(v, 0, Math.max(maxY, 1400), top, bottom);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }});
    ctx.stroke();
    ctx.restore();
    for (let i = 0; i < values.length; i += Math.max(Math.floor(values.length / 8), 1)) {{
      marker(xScale(data.series.x[i], 0, total, left, right), yScale(values[i], 0, Math.max(maxY, 1400), top, bottom), color, shape);
    }}
    const last = values.length - 1;
    marker(xScale(data.series.x[last], 0, total, left, right), yScale(values[last], 0, Math.max(maxY, 1400), top, bottom), color, shape);
  }}
  drawSeries(data.series.invoke_all, '#5c677d', 'circle');
  drawSeries(data.series.gated, '#4f86c6', 'diamond');
  marker(410, 74, '#5c677d', 'circle');
  text('invoke-all', 428, 80, {{size: 15}});
  marker(515, 74, '#4f86c6', 'diamond');
  text('topology-gated', 533, 80, {{size: 15}});
}}

function drawPanelB() {{
  const left = 735, top = 92, right = 1118, bottom = 388;
  text('(b) Dispatch budget decomposition', 925, 38, {{size: 23, weight: 'bold', align: 'center'}});
  drawAxes(left, top, right, bottom, [0, 350, 700, 1050, 1400], 0, 1400, 'alerts');
  const values = [
    ['invoke-all', data.summary.planned_invoke_all_calls, '#9aa8c2'],
    ['gated-call', data.summary.planned_topology_gated_calls, '#4f86c6'],
    ['template-only', data.summary.planned_template_only_skips, '#c9d3a2'],
  ];
  const xs = [810, 925, 1040];
  values.forEach((item, i) => {{
    const y = yScale(item[1], 0, 1400, top, bottom);
    rect(xs[i] - 33, y, 66, bottom - y, item[2], '#111');
    text(String(item[1]), xs[i], y - 10, {{size: 17, weight: 'bold', align: 'center'}});
    text(item[0], xs[i], bottom + 28, {{size: 16, align: 'center'}});
  }});
  text(`${{data.summary.planned_call_reduction_percent}}% fewer external calls`, 928, bottom + 65, {{size: 18, weight: 'bold', align: 'center'}});
}}

function drawPanelC() {{
  const left = 1240, top = 92, right = 1618, bottom = 388;
  text('(c) Retention and output checks', 1430, 38, {{size: 23, weight: 'bold', align: 'center'}});
  drawAxes(left, top, right, bottom, [0, 25, 50, 75, 100], 0, 100, 'rate (%)');
  const metrics = [
    ['call reduction', data.summary.planned_call_reduction_percent, '#4f86c6'],
    ['high-value recall', (data.summary.high_value_recall || 0) * 100, '#6f4aa5'],
    ['schema valid', (data.summary.response_schema_valid_rate || 0) * 100, '#6b8e23'],
  ];
  const xs = [1300, 1430, 1560];
  ctx.save();
  ctx.strokeStyle = '#333';
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  metrics.forEach((item, i) => {{
    const x = xs[i];
    const y = yScale(item[1], 0, 100, top, bottom);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();
  ctx.restore();
  metrics.forEach((item, i) => {{
    const x = xs[i];
    const y = yScale(item[1], 0, 100, top, bottom);
    marker(x, y, item[2], i === 1 ? 'circle' : 'diamond');
    text(`${{item[1].toFixed(2)}}%`, x, y - 14, {{size: 16, weight: 'bold', align: 'center'}});
    text(item[0], x, bottom + 28, {{size: 15, align: 'center'}});
  }});
  text(`mode: ${{data.summary.mode}}`, left, bottom + 65, {{size: 16}});
  text(`external attempted: ${{data.summary.external_calls_attempted}}`, left + 170, bottom + 65, {{size: 16}});
}}

ctx.fillStyle = 'white';
ctx.fillRect(0, 0, data.width, data.height);
drawPanelA();
drawPanelB();
drawPanelC();
</script>
</body>
</html>
"""


def render(summary_path: Path, events_path: Path, output_path: Path) -> None:
    summary = _load_summary(summary_path)
    events = _load_events(events_path)
    HTML_PATH.write_text(render_html(summary, events), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "google-chrome",
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--screenshot={output_path}",
            f"--window-size={WIDTH},{HEIGHT}",
            HTML_PATH.as_uri(),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render publication-style topology-gated LLM replay figure.")
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--events-jsonl", default=str(DEFAULT_EVENTS))
    parser.add_argument("--output-png", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    render(Path(args.summary_json), Path(args.events_jsonl), Path(args.output_png))


if __name__ == "__main__":
    main()
