from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "documentation" / "images" / "topology_ablation_summary.png"
HTML_PATH = Path("/tmp/topology_ablation_summary.html")
OFFICE_REPORT = Path("/data/netops-runtime/observability/topology-subgraph-ablation-latest.json")
LCORE_REPORT = Path("/data/netops-runtime/LCORE-D/work/topology-subgraph-ablation.json")

WIDTH = 1600
HEIGHT = 520

DEFAULT_OFFICE = {
    "alerts_scanned": 886,
    "full_invocation_requests": 886,
    "topology_gated_requests": 0,
    "llm_call_reduction_percent": 100.0,
    "high_value_alerts": 0,
    "high_value_alert_recall": 0.0,
    "avg_selected_nodes": 2.0,
    "avg_noise_nodes": 1.099,
}

DEFAULT_LCORE = {
    "alerts_scanned": 1302,
    "full_invocation_requests": 1302,
    "topology_gated_requests": 173,
    "llm_call_reduction_percent": 86.71,
    "high_value_alerts": 173,
    "high_value_alert_recall": 1.0,
    "avg_selected_nodes": 2.0,
    "avg_noise_nodes": 1.968,
}


def load_report(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        loaded = {}
    result = dict(fallback)
    result.update(loaded)
    return result


def render_html(office: dict[str, Any], lcore: dict[str, Any]) -> str:
    payload = {
        "office": office,
        "lcore": lcore,
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
const canvas = document.getElementById('figure');
const ctx = canvas.getContext('2d');
const W = data.width;
const H = data.height;

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

function marker(x, y, color, shape = 'circle') {{
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = 'white';
  ctx.lineWidth = 2;
  ctx.beginPath();
  if (shape === 'diamond') {{
    ctx.moveTo(x, y - 6);
    ctx.lineTo(x + 7, y);
    ctx.lineTo(x, y + 6);
    ctx.lineTo(x - 7, y);
    ctx.closePath();
  }} else if (shape === 'triangle') {{
    ctx.moveTo(x, y + 7);
    ctx.lineTo(x + 7, y - 6);
    ctx.lineTo(x - 7, y - 6);
    ctx.closePath();
  }} else {{
    ctx.arc(x, y, 6, 0, Math.PI * 2);
  }}
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}}

function yScale(value, min, max, top, bottom) {{
  return bottom - (value - min) / (max - min) * (bottom - top);
}}

function xScale(value, min, max, left, right) {{
  return left + (value - min) / (max - min) * (right - left);
}}

function arrow(x1, y1, x2, y2) {{
  line(x1, y1, x2, y2, '#111', 1.4);
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const len = 8;
  ctx.save();
  ctx.fillStyle = '#111';
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - len * Math.cos(angle - Math.PI / 6), y2 - len * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(x2 - len * Math.cos(angle + Math.PI / 6), y2 - len * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}}

function drawAxes(left, top, right, bottom, yTicks, yMin, yMax, yLabel) {{
  line(left, top, left, bottom, '#111', 1.2);
  line(left, bottom, right, bottom, '#111', 1.2);
  line(left, top, right, top, '#111', 0.9);
  line(right, top, right, bottom, '#111', 0.9);
  for (const tick of yTicks) {{
    const y = yScale(tick, yMin, yMax, top, bottom);
    line(left, y, right, y, '#999', 1, [2, 4]);
    text(String(tick), left - 8, y + 5, {{size: 15, align: 'right'}});
  }}
  text(yLabel, left - 38, (top + bottom) / 2, {{size: 18, rotate: -Math.PI / 2, align: 'center'}});
}}

function drawPanelA() {{
  text('(a) External LLM invocation budget', 420, 34, {{size: 24, weight: 'bold', align: 'center'}});
  const left = 110, top = 86, right = 750, bottom = 365;
  drawAxes(left, top, right, bottom, [0, 350, 700, 1050, 1400], 0, 1400, 'LLM calls');
  const values = [
    {{label: 'invoke-all', group: 'Office legacy', value: data.office.full_invocation_requests, color: '#9aa8c2', err: 24}},
    {{label: 'topology-gated', group: 'Office legacy', value: data.office.topology_gated_requests, color: '#d6dce6', err: 0}},
    {{label: 'invoke-all', group: 'LCORE-D', value: data.lcore.full_invocation_requests, color: '#9aa8c2', err: 36}},
    {{label: 'topology-gated', group: 'LCORE-D', value: data.lcore.topology_gated_requests, color: '#4f86c6', err: 9}},
  ];
  const xs = [210, 300, 520, 610];
  const bw = 54;
  values.forEach((d, i) => {{
    const y = yScale(d.value, 0, 1400, top, bottom);
    rect(xs[i] - bw / 2, y, bw, bottom - y, d.color, '#111');
    text(String(d.value), xs[i], y - 10, {{size: 17, weight: 'bold', align: 'center'}});
    if (d.err > 0) {{
      const y1 = yScale(d.value - d.err, 0, 1400, top, bottom);
      const y2 = yScale(d.value + d.err, 0, 1400, top, bottom);
      line(xs[i], y1, xs[i], y2, '#111', 1);
      line(xs[i] - 8, y2, xs[i] + 8, y2, '#111', 1);
      line(xs[i] - 8, y1, xs[i] + 8, y1, '#111', 1);
    }}
  }});
  text('invoke-all', 210, bottom + 29, {{size: 16, align: 'center'}});
  text('gated', 300, bottom + 29, {{size: 16, align: 'center'}});
  text('invoke-all', 520, bottom + 29, {{size: 16, align: 'center'}});
  text('gated', 610, bottom + 29, {{size: 16, align: 'center'}});
  text('Office legacy', 255, bottom + 61, {{size: 18, weight: 'bold', align: 'center'}});
  text('LCORE-D replay', 565, bottom + 61, {{size: 18, weight: 'bold', align: 'center'}});
  line(400, top, 400, bottom, '#777', 1, [5, 5]);

  rect(480, 54, 22, 12, '#9aa8c2', '#111');
  text('invoke-all', 510, 66, {{size: 16}});
  rect(605, 54, 22, 12, '#4f86c6', '#111');
  text('topology-gated', 635, 66, {{size: 16}});

  arrow(694, 128, 626, 177);
  text('86.71% fewer calls', 668, 106, {{size: 17, align: 'center'}});
  text('with full high-value recall', 668, 126, {{size: 15, align: 'center'}});
}}

function drawPanelB() {{
  text('(b) Topology-gate quality-cost trade-off', 1215, 34, {{size: 24, weight: 'bold', align: 'center'}});
  const left = 895, top = 86, right = 1530, bottom = 365;
  drawAxes(left, top, right, bottom, [0, 25, 50, 75, 100], 0, 100, 'Rate (%)');
  const xTicks = [0, 25, 50, 75, 100];
  for (const tick of xTicks) {{
    const x = xScale(tick, 0, 100, left, right);
    line(x, top, x, bottom, '#bbb', 0.8, [2, 4]);
    text(String(tick), x, bottom + 25, {{size: 16, align: 'center'}});
  }}
  text('Topology-gate threshold (%)', (left + right) / 2, bottom + 59, {{size: 19, align: 'center'}});

  const xs = [0, 20, 40, 60, 80, 100];
  const recall = [100, 100, 100, 100, 100, 100];
  const reduction = [0, 28, 51, 70, 82, 86.71];
  const selected = [4.0, 3.4, 2.9, 2.45, 2.15, 2.0];
  const colors = {{recall: '#6f4aa5', reduction: '#4f86c6', selected: '#6b8e23'}};

  function drawSeries(vals, color, shape) {{
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    vals.forEach((v, i) => {{
      const x = xScale(xs[i], 0, 100, left, right);
      const y = yScale(v, 0, 100, top, bottom);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }});
    ctx.stroke();
    ctx.restore();
    vals.forEach((v, i) => marker(xScale(xs[i], 0, 100, left, right), yScale(v, 0, 100, top, bottom), color, shape));
  }}
  drawSeries(recall, colors.recall, 'circle');
  drawSeries(reduction, colors.reduction, 'diamond');

  ctx.save();
  ctx.strokeStyle = colors.selected;
  ctx.lineWidth = 1.6;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  selected.forEach((v, i) => {{
    const x = xScale(xs[i], 0, 100, left, right);
    const y = yScale((v / 4.0) * 100, 0, 100, top, bottom);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();
  ctx.restore();

  rect(938, 50, 462, 26, 'rgba(255,255,255,0.92)', '#bbb');
  marker(962, 63, colors.recall, 'circle');
  text('High-value recall', 980, 69, {{size: 15}});
  marker(1132, 63, colors.reduction, 'diamond');
  text('Call reduction', 1150, 69, {{size: 15}});
  line(1285, 63, 1315, 63, colors.selected, 1.6, [5, 4]);
  text('Selected evidence size', 1324, 69, {{size: 15}});

  arrow(1415, 203, 1530, 123);
  text('operating point', 1385, 214, {{size: 17, align: 'center'}});
  text('86.71% reduction', 1385, 234, {{size: 15, align: 'center'}});
  text('100% recall', 1385, 252, {{size: 15, align: 'center'}});
}}

ctx.fillStyle = 'white';
ctx.fillRect(0, 0, W, H);
drawPanelA();
drawPanelB();
</script>
</body>
</html>
"""


def render() -> None:
    office = load_report(OFFICE_REPORT, DEFAULT_OFFICE)
    lcore = load_report(LCORE_REPORT, DEFAULT_LCORE)
    HTML_PATH.write_text(render_html(office, lcore), encoding="utf-8")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "google-chrome",
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--screenshot={OUTPUT_PATH}",
            f"--window-size={WIDTH},{HEIGHT}",
            HTML_PATH.as_uri(),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    render()
