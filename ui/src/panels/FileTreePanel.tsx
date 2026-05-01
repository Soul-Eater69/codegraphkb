import type { FileTreeNode } from "../types/graph";

interface FileTreePanelProps {
  tree: FileTreeNode | null;
  loading: boolean;
  error: string | null;
  onSelectFile: (path: string) => void;
}

export function FileTreePanel({ tree, loading, error, onSelectFile }: FileTreePanelProps) {
  return (
    <section className="panel">
      <h3>File Tree</h3>
      {loading ? <p className="muted">Loading tree...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !error && tree ? <div className="tree-root">{renderNode(tree, onSelectFile)}</div> : null}
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
