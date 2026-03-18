"""Generate a standalone HTML graph visualization of the paper citation network."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.fetcher.models import Paper


def _short_title(title: str, max_len: int = 40) -> str:
    name = re.sub(r"\s+", " ", title).strip()
    if len(name) > max_len:
        name = name[:max_len].rsplit(" ", 1)[0] + "…"
    return name


def export_graph_html(
    papers: list[Paper],
    out_path: str,
) -> str:
    """Write an interactive HTML graph and return the file path."""
    lookup = {p.id: p for p in papers}

    nodes = []
    edges = []
    seen_edges: set[tuple[str, str]] = set()

    for p in papers:
        nodes.append({
            "id": p.id,
            "label": _short_title(p.title),
            "title": p.title,
            "year": p.year,
            "cited": p.cited_by_count,
            "topic": p.topic or "other",
            "authors": ", ".join(p.authors[:3]),
            "abstract": (p.abstract[:200] + "…") if len(p.abstract) > 200 else p.abstract,
        })
        for ref_id in p.references:
            if ref_id in lookup and (p.id, ref_id) not in seen_edges:
                edges.append({"from": p.id, "to": ref_id})
                seen_edges.add((p.id, ref_id))

    # Assign colors by topic
    topics = sorted({n["topic"] for n in nodes})
    palette = [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
        "#86bcb6", "#8cd17d", "#b6992d", "#499894", "#d37295",
    ]
    topic_color = {t: palette[i % len(palette)] for i, t in enumerate(topics)}

    for n in nodes:
        n["color"] = topic_color[n["topic"]]

    html = _TEMPLATE.replace("__NODES__", json.dumps(nodes, ensure_ascii=False))
    html = html.replace("__EDGES__", json.dumps(edges, ensure_ascii=False))
    html = html.replace("__TOPICS__", json.dumps(
        [{"topic": t, "color": topic_color[t]} for t in topics],
        ensure_ascii=False,
    ))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Paper Copilot — Citation Graph</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1a1a2e; color: #eee; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; }
canvas { display: block; }
#info {
  position: fixed; top: 16px; right: 16px; width: 340px;
  background: rgba(30,30,50,0.95); border-radius: 12px; padding: 20px;
  display: none; box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  max-height: 80vh; overflow-y: auto; z-index: 10;
}
#info h2 { font-size: 15px; margin-bottom: 8px; line-height: 1.4; }
#info p { font-size: 12px; color: #aaa; margin-bottom: 6px; line-height: 1.5; }
#legend {
  position: fixed; bottom: 16px; left: 16px;
  background: rgba(30,30,50,0.9); border-radius: 8px; padding: 12px 16px;
  font-size: 12px; z-index: 10;
}
#legend .item { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
#legend .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
#title-bar {
  position: fixed; top: 16px; left: 16px;
  font-size: 18px; font-weight: bold; opacity: 0.7; z-index: 10;
}
</style>
</head>
<body>

<div id="title-bar">Paper Copilot — Citation Graph</div>
<canvas id="c"></canvas>
<div id="info">
  <h2 id="info-title"></h2>
  <p id="info-authors"></p>
  <p id="info-meta"></p>
  <p id="info-abstract"></p>
</div>
<div id="legend"></div>

<script>
// Data
const nodes = __NODES__;
const edges = __EDGES__;
const topics = __TOPICS__;

// Legend
const legend = document.getElementById('legend');
topics.forEach(t => {
  const item = document.createElement('div');
  item.className = 'item';
  item.innerHTML = '<span class="dot" style="background:' + t.color + '"></span>' + t.topic;
  legend.appendChild(item);
});

// Canvas setup (Retina support)
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const dpr = window.devicePixelRatio || 1;
let W = window.innerWidth, H = window.innerHeight;
canvas.width = W * dpr; canvas.height = H * dpr;
canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
ctx.scale(dpr, dpr);
window.addEventListener('resize', () => {
  W = window.innerWidth; H = window.innerHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);
});

// Build index
const idxMap = {};
nodes.forEach((n, i) => { idxMap[n.id] = i; });

// Initialize positions randomly
const cx = W / 2, cy = H / 2;
nodes.forEach(n => {
  n.x = cx + (Math.random() - 0.5) * 400;
  n.y = cy + (Math.random() - 0.5) * 400;
  n.vx = 0; n.vy = 0;
});

// Compute node radius based on citation count
const minC = Math.min(...nodes.map(n => n.cited));
const maxC = Math.max(...nodes.map(n => n.cited));
const nodeR = (n) => 5 + (maxC > minC ? ((n.cited - minC) / (maxC - minC)) * 15 : 5);

// Resolve edge indices
const links = edges.map(e => ({ s: idxMap[e.from], t: idxMap[e.to] })).filter(e => e.s !== undefined && e.t !== undefined);

// Force simulation
function simulate() {
  const alpha = 0.3;
  const repulsion = 3000;
  const linkDist = 150;
  const linkStrength = 0.01;
  const centerStrength = 0.005;
  const damping = 0.85;

  // Repulsion (all pairs)
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      let dx = nodes[j].x - nodes[i].x;
      let dy = nodes[j].y - nodes[i].y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) d2 = 1;
      let f = repulsion / d2;
      let fx = dx / Math.sqrt(d2) * f;
      let fy = dy / Math.sqrt(d2) * f;
      nodes[i].vx -= fx * alpha;
      nodes[i].vy -= fy * alpha;
      nodes[j].vx += fx * alpha;
      nodes[j].vy += fy * alpha;
    }
  }

  // Link attraction
  for (const link of links) {
    const a = nodes[link.s], b = nodes[link.t];
    let dx = b.x - a.x;
    let dy = b.y - a.y;
    let d = Math.sqrt(dx * dx + dy * dy) || 1;
    let f = (d - linkDist) * linkStrength * alpha;
    let fx = dx / d * f;
    let fy = dy / d * f;
    a.vx += fx; a.vy += fy;
    b.vx -= fx; b.vy -= fy;
  }

  // Center gravity
  for (const n of nodes) {
    n.vx += (cx - n.x) * centerStrength * alpha;
    n.vy += (cy - n.y) * centerStrength * alpha;
  }

  // Update positions
  for (const n of nodes) {
    n.vx *= damping; n.vy *= damping;
    n.x += n.vx; n.y += n.vy;
  }
}

// Camera (pan & zoom)
let camX = 0, camY = 0, zoom = 1;

function screenToWorld(sx, sy) {
  return [(sx - W/2) / zoom + cx - camX, (sy - H/2) / zoom + cy - camY];
}

// Drawing
function draw() {
  ctx.clearRect(0, 0, W, H);
  ctx.save();
  ctx.translate(W/2, H/2);
  ctx.scale(zoom, zoom);
  ctx.translate(-cx + camX, -cy + camY);

  // Edges
  ctx.strokeStyle = 'rgba(140,180,255,0.5)';
  ctx.lineWidth = 1.5;
  for (const link of links) {
    const a = nodes[link.s], b = nodes[link.t];
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();

    // Arrowhead
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    const rr = nodeR(b) + 3;
    const ax = b.x - Math.cos(angle) * rr;
    const ay = b.y - Math.sin(angle) * rr;
    ctx.save();
    ctx.translate(ax, ay);
    ctx.rotate(angle);
    ctx.fillStyle = 'rgba(140,180,255,0.6)';
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-8, -4);
    ctx.lineTo(-8, 4);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // Nodes
  for (const n of nodes) {
    const r = nodeR(n);

    // Highlight hovered
    if (n === hovered) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, r + 4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.15)';
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = n.color;
    ctx.fill();
    ctx.strokeStyle = '#222';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Label
    ctx.fillStyle = '#ccc';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.fillText(n.label, n.x + r + 4, n.y + 3);
  }

  ctx.restore();
}

// Interaction
let hovered = null;
let dragging = null;
let dragOffX = 0, dragOffY = 0;
let isPanning = false;
let panStartX = 0, panStartY = 0, camStartX = 0, camStartY = 0;

function findNode(mx, my) {
  const [wx, wy] = screenToWorld(mx, my);
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const r = nodeR(n);
    const dx = wx - n.x, dy = wy - n.y;
    if (dx * dx + dy * dy <= (r + 4) * (r + 4)) return n;
  }
  return null;
}

canvas.addEventListener('mousedown', e => {
  const n = findNode(e.clientX, e.clientY);
  if (n) {
    dragging = n;
    const [wx, wy] = screenToWorld(e.clientX, e.clientY);
    dragOffX = n.x - wx;
    dragOffY = n.y - wy;
  } else {
    isPanning = true;
    panStartX = e.clientX;
    panStartY = e.clientY;
    camStartX = camX;
    camStartY = camY;
  }
});

canvas.addEventListener('mousemove', e => {
  if (dragging) {
    const [wx, wy] = screenToWorld(e.clientX, e.clientY);
    dragging.x = wx + dragOffX;
    dragging.y = wy + dragOffY;
    dragging.vx = 0; dragging.vy = 0;
  } else if (isPanning) {
    camX = camStartX + (e.clientX - panStartX) / zoom;
    camY = camStartY + (e.clientY - panStartY) / zoom;
  } else {
    hovered = findNode(e.clientX, e.clientY);
    canvas.style.cursor = hovered ? 'pointer' : 'grab';
  }
});

canvas.addEventListener('mouseup', () => {
  if (dragging) {
    // Show info
    const n = dragging;
    document.getElementById('info').style.display = 'block';
    document.getElementById('info-title').textContent = n.title;
    document.getElementById('info-authors').textContent = n.authors;
    document.getElementById('info-meta').textContent = 'Year: ' + n.year + ' | Cited by: ' + n.cited + ' | Topic: ' + n.topic;
    document.getElementById('info-abstract').textContent = n.abstract;
  }
  dragging = null;
  isPanning = false;
});

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.9 : 1.1;
  zoom = Math.max(0.1, Math.min(5, zoom * factor));
}, { passive: false });

canvas.addEventListener('click', e => {
  const n = findNode(e.clientX, e.clientY);
  if (n) {
    document.getElementById('info').style.display = 'block';
    document.getElementById('info-title').textContent = n.title;
    document.getElementById('info-authors').textContent = n.authors;
    document.getElementById('info-meta').textContent = 'Year: ' + n.year + ' | Cited by: ' + n.cited + ' | Topic: ' + n.topic;
    document.getElementById('info-abstract').textContent = n.abstract;
  } else {
    document.getElementById('info').style.display = 'none';
  }
});

// Animation loop
function loop() {
  simulate();
  draw();
  requestAnimationFrame(loop);
}
loop();
</script>
</body>
</html>
"""
