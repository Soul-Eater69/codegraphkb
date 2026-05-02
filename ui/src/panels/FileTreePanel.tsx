import { useMemo, useState } from "react";
import type { FileTreeNode } from "../types/graph";

interface FileTreePanelProps {
  tree: FileTreeNode | null;
  loading: boolean;
  error: string | null;
  onSelectFile: (path: string) => void;
}

export function FileTreePanel({ tree, loading, error, onSelectFile }: FileTreePanelProps) {
  const [query, setQuery] = useState("");
  const filteredTree = useMemo(() => filterTree(tree, query), [tree, query]);

  return (
    <section className="panel">
      <h3>File Tree</h3>
      <input
        className="panel-search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search files..."
      />
      {loading ? <p className="muted">Loading tree...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !error && filteredTree ? <div className="tree-root">{renderNode(filteredTree, onSelectFile)}</div> : null}
    </section>
  );
}

function renderNode(node: FileTreeNode, onSelectFile: (path: string) => void, depth = 0): JSX.Element {
  if (node.type === "file") {
    return (
      <button type="button" className="tree-file" style={{ paddingLeft: `${8 + depth * 12}px` }} onClick={() => onSelectFile(node.path)}>
        <span>{node.name}</span>
        <small>{node.symbol_count ?? 0}</small>
      </button>
    );
  }

  return (
    <details open={depth < 1} className="tree-folder">
      <summary>
        <span>{node.name}</span>
        <small>{node.file_count ?? 0}</small>
      </summary>
      <div>
        {(node.children ?? []).map((child) => (
          <div key={`${child.type}:${child.path}`}>{renderNode(child, onSelectFile, depth + 1)}</div>
        ))}
      </div>
    </details>
  );
}

function filterTree(node: FileTreeNode | null, query: string): FileTreeNode | null {
  if (!node) {
    return null;
  }
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return node;
  }
  if (node.type === "file") {
    return node.name.toLowerCase().includes(needle) || node.path.toLowerCase().includes(needle) ? node : null;
  }
  const children = (node.children ?? [])
    .map((child) => filterTree(child, needle))
    .filter((child): child is FileTreeNode => child != null);
  if (children.length > 0 || node.name.toLowerCase().includes(needle) || node.path.toLowerCase().includes(needle)) {
    return { ...node, children };
  }
  return null;
}
