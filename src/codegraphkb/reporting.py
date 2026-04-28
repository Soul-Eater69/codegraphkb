"""Generate a GRAPH_REPORT.md after indexing — useful for humans + LLMs."""
from __future__ import annotations

from datetime import datetime, timezone

from codegraphkb.core.store import GraphStore


def generate_report(store: GraphStore) -> str:
    files = store.file_count()
    languages = store.file_languages()
    symbols = store.symbol_count()
    edges = store.edge_count()
    last_indexed = store.get_meta("last_indexed_at") or datetime.now(timezone.utc).isoformat()

    high_degree_rows = store._conn.execute("""
        SELECT s.qualified_name, s.kind,
               (SELECT COUNT(*) FROM edges e WHERE e.dst_qname = s.qualified_name) AS callers,
               (SELECT COUNT(*) FROM edges e WHERE e.src_qname = s.qualified_name) AS callees
        FROM symbols s
        ORDER BY (callers + callees) DESC
        LIMIT 10
    """).fetchall()
    routes = store._conn.execute(
        "SELECT name FROM symbols WHERE kind='route' ORDER BY name LIMIT 25"
    ).fetchall()

    lines = [
        "# Graph Report",
        "",
        f"_Generated: {last_indexed}_",
        "",
        "## Repo Summary",
        f"- Files indexed: **{files}**",
        f"- Symbols: **{symbols}**",
        f"- Edges: **{edges}**",
        f"- Languages: " + ", ".join(f"`{k}` ({v})" for k, v in sorted(languages.items())),
        "",
        "## High-Degree Symbols",
    ]
    if high_degree_rows:
        lines.append("| Symbol | Kind | Callers | Callees |")
        lines.append("|---|---|---|---|")
        for r in high_degree_rows:
            lines.append(f"| `{r['qualified_name']}` | {r['kind']} | {r['callers']} | {r['callees']} |")
    else:
        lines.append("_(none)_")

    if routes:
        lines.extend(["", "## API Endpoints"])
        for r in routes:
            lines.append(f"- `{r['name']}`")

    lines.extend([
        "",
        "## Suggested Questions",
        "- How does the request flow work end-to-end?",
        "- Which files would I edit to add a new endpoint?",
        "- What breaks if I change the most-called function?",
    ])
    return "\n".join(lines) + "\n"
