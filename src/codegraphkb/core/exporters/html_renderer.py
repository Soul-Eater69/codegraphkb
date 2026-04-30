"""Static HTML renderer for graph payloads."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_graph_html(
    graph: dict[str, Any],
    *,
    out: Path,
    title: str = "CodeGraphKB Graph",
    views: dict[str, dict[str, Any]] | None = None,
    default_view: str | None = None,
) -> Path:
    """Render a self-contained interactive HTML graph."""
    vis_js = _load_vis_bundle()
    views_payload: dict[str, dict[str, Any]]
    if views:
        views_payload = views
    else:
        view_name = graph.get("metadata", {}).get("view", "full")
        views_payload = {view_name: graph}
    if default_view is None:
        default_view = next(iter(views_payload.keys()))

    payload_json = json.dumps(
        {"default_view": default_view, "views": views_payload},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape_html(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f1117;
      --panel: #161a22;
      --border: #2a3242;
      --text: #e8edf5;
      --muted: #9aa7bd;
      --accent: #4f8cff;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
      display: grid;
      grid-template-rows: auto 1fr;
      height: 100vh;
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr 1fr auto;
      gap: 8px;
      padding: 10px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }}
    input, select, button {{
      background: #0f1320;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 8px;
      font-size: 13px;
      letter-spacing: 0;
    }}
    button {{
      cursor: pointer;
    }}
    .main {{
      display: grid;
      grid-template-columns: 1fr 340px;
      min-height: 0;
    }}
    #network {{
      width: 100%;
      height: 100%;
      background: #0b0f18;
    }}
    .side {{
      border-left: 1px solid var(--border);
      background: var(--panel);
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 0;
    }}
    .stats {{
      padding: 10px;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
      color: var(--muted);
    }}
    .details {{
      padding: 10px;
      overflow: auto;
      white-space: pre-wrap;
      font-size: 12px;
      line-height: 1.45;
    }}
    @media (max-width: 960px) {{
      .toolbar {{
        grid-template-columns: 1fr 1fr;
      }}
      .main {{
        grid-template-columns: 1fr;
        grid-template-rows: 1fr auto;
      }}
      .side {{
        border-left: 0;
        border-top: 1px solid var(--border);
      }}
    }}
  </style>
</head>
<body>
  <div class="toolbar">
    <input id="search" type="text" placeholder="Search node by name..." />
    <select id="kindFilter"><option value="">All node kinds</option></select>
    <select id="edgeFilter"><option value="">All edge types</option></select>
    <select id="viewSelect"></select>
    <button id="resetBtn" type="button">Reset</button>
  </div>
  <div class="main">
    <div id="network"></div>
    <aside class="side">
      <div class="stats" id="stats"></div>
      <div class="details" id="details">Click a node or edge to inspect metadata.</div>
    </aside>
  </div>

  <script>{vis_js}</script>
  <script id="graph-data" type="application/json">{payload_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("graph-data").textContent);
    const viewSelect = document.getElementById("viewSelect");
    const searchInput = document.getElementById("search");
    const kindFilter = document.getElementById("kindFilter");
    const edgeFilter = document.getElementById("edgeFilter");
    const resetBtn = document.getElementById("resetBtn");
    const statsEl = document.getElementById("stats");
    const detailsEl = document.getElementById("details");
    const container = document.getElementById("network");

    let currentView = payload.default_view;
    let active = payload.views[currentView];
    let nodeMap = new Map();
    let edgeMap = new Map();
    let network;
    let allNodeIds = [];

    function pretty(obj) {{
      return JSON.stringify(obj, null, 2);
    }}

    function colorFor(kind) {{
      const palette = {{
        file: "#5f9bff", folder: "#64c7cc", function: "#8dd17e", method: "#8dd17e",
        class: "#f6b26b", interface: "#f6b26b", route: "#ff8ec7", test_block: "#e4d96f",
        model: "#c69bff", api_consumer: "#ffb16a", process: "#ff6f91", symbol: "#9aa7bd"
      }};
      return palette[kind] || "#9aa7bd";
    }}

    function buildData() {{
      nodeMap = new Map((active.nodes || []).map(n => [n.id, n]));
      edgeMap = new Map((active.edges || []).map(e => [e.id, e]));
      allNodeIds = Array.from(nodeMap.keys());

      const nodes = [];
      for (const n of nodeMap.values()) {{
        nodes.push({{
          id: n.id,
          label: n.label || n.id,
          title: n.id,
          color: {{
            background: colorFor(n.kind),
            border: "#1f2a3d",
            highlight: {{ background: "#ffd166", border: "#ffe6a7" }}
          }},
          shape: n.kind === "process" ? "box" : "dot",
          size: n.kind === "process" ? 18 : 14,
          font: {{ color: "#e8edf5", size: 13 }},
        }});
      }}

      const edges = [];
      for (const e of edgeMap.values()) {{
        edges.push({{
          id: e.id,
          from: e.source,
          to: e.target,
          label: e.type || "",
          arrows: "to",
          color: {{ color: "#596780", highlight: "#8cc0ff" }},
          font: {{ align: "middle", color: "#9fb0cc", size: 11 }},
          smooth: true,
        }});
      }}
      return {{ nodes, edges }};
    }}

    function refreshFilters() {{
      const kinds = new Set((active.nodes || []).map(n => n.kind).filter(Boolean));
      kindFilter.innerHTML = '<option value="">All node kinds</option>';
      [...kinds].sort().forEach(k => {{
        const opt = document.createElement("option");
        opt.value = k;
        opt.textContent = k;
        kindFilter.appendChild(opt);
      }});

      const edgeTypes = new Set((active.edges || []).map(e => e.type).filter(Boolean));
      edgeFilter.innerHTML = '<option value="">All edge types</option>';
      [...edgeTypes].sort().forEach(t => {{
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = t;
        edgeFilter.appendChild(opt);
      }});
    }}

    function refreshStats() {{
      const m = active.metadata || {{}};
      statsEl.textContent = `view=${{m.view || currentView}}  nodes=${{(active.nodes || []).length}}  edges=${{(active.edges || []).length}}`;
    }}

    function render() {{
      const data = buildData();
      if (!network) {{
        network = new vis.Network(
          container,
          {{
            nodes: new vis.DataSet(data.nodes),
            edges: new vis.DataSet(data.edges),
          }},
          {{
            interaction: {{ hover: true, navigationButtons: true, keyboard: true }},
            physics: {{ stabilization: false, barnesHut: {{ springLength: 110 }} }},
            edges: {{ selectionWidth: 2.5 }},
          }},
        );

        network.on("click", params => {{
          if (params.nodes.length) {{
            const id = params.nodes[0];
            const node = nodeMap.get(id);
            detailsEl.textContent = pretty({{ type: "node", ...node }});
            highlightNeighbors(id);
          }} else if (params.edges.length) {{
            const id = params.edges[0];
            const edge = edgeMap.get(id);
            detailsEl.textContent = pretty({{ type: "edge", ...edge }});
          }}
        }});
      }} else {{
        network.setData({{
          nodes: new vis.DataSet(data.nodes),
          edges: new vis.DataSet(data.edges),
        }});
      }}
      refreshFilters();
      refreshStats();
      applyFilters();
    }}

    function applyFilters() {{
      const q = searchInput.value.trim().toLowerCase();
      const kind = kindFilter.value;
      const edgeType = edgeFilter.value;
      const visibleNodes = new Set();

      for (const n of nodeMap.values()) {{
        const byText = !q || (String(n.label || "").toLowerCase().includes(q) || String(n.id || "").toLowerCase().includes(q));
        const byKind = !kind || n.kind === kind;
        if (byText && byKind) visibleNodes.add(n.id);
      }}

      const edgeUpdates = [];
      for (const e of edgeMap.values()) {{
        const byType = !edgeType || e.type === edgeType;
        const visible = byType && visibleNodes.has(e.source) && visibleNodes.has(e.target);
        edgeUpdates.push({{ id: e.id, hidden: !visible }});
      }}

      const nodeUpdates = allNodeIds.map(id => ({{ id, hidden: !visibleNodes.has(id) }}));
      network.body.data.nodes.update(nodeUpdates);
      network.body.data.edges.update(edgeUpdates);
    }}

    function highlightNeighbors(nodeId) {{
      const connected = new Set(network.getConnectedNodes(nodeId));
      connected.add(nodeId);
      const updates = allNodeIds.map(id => {{
        if (connected.has(id)) {{
          return {{ id, opacity: 1 }};
        }}
        return {{ id, opacity: 0.25 }};
      }});
      network.body.data.nodes.update(updates);
    }}

    function clearHighlight() {{
      const updates = allNodeIds.map(id => ({{ id, opacity: 1 }}));
      network.body.data.nodes.update(updates);
    }}

    function loadView(name) {{
      currentView = name;
      active = payload.views[currentView] || active;
      render();
      clearHighlight();
    }}

    for (const name of Object.keys(payload.views)) {{
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === currentView) opt.selected = true;
      viewSelect.appendChild(opt);
    }}

    searchInput.addEventListener("input", applyFilters);
    kindFilter.addEventListener("change", applyFilters);
    edgeFilter.addEventListener("change", applyFilters);
    viewSelect.addEventListener("change", e => loadView(e.target.value));
    resetBtn.addEventListener("click", () => {{
      searchInput.value = "";
      kindFilter.value = "";
      edgeFilter.value = "";
      detailsEl.textContent = "Click a node or edge to inspect metadata.";
      clearHighlight();
      applyFilters();
      network.fit({{ animation: true }});
    }});

    render();
    network.fit({{ animation: true }});
  </script>
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _load_vis_bundle() -> str:
    asset_path = Path(__file__).resolve().parents[2] / "assets" / "vis-network.min.js"
    return asset_path.read_text(encoding="utf-8")


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
