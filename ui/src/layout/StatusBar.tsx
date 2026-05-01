import type { SummaryResponse } from "../types/graph";

interface StatusBarProps {
  summary: SummaryResponse | null;
  nodeCount: number;
  edgeCount: number;
}

export function StatusBar({ summary, nodeCount, edgeCount }: StatusBarProps) {
  return (
    <div className="status-bar">
      <span>{summary?.files ?? 0} files</span>
      <span>{summary?.symbols ?? 0} symbols</span>
      <span>{summary?.processes ?? 0} processes</span>
      <span>{nodeCount} scene nodes</span>
      <span>{edgeCount} scene edges</span>
    </div>
  );
}
