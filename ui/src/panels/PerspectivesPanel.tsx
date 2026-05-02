import type { Perspective } from "../types/graph";

interface PerspectivesPanelProps {
  active: Perspective;
  onAction: (action: "full" | "repo" | "processes" | "calls" | "symbols" | "framework") => void;
}

const options: Array<{ label: string; action: "full" | "repo" | "processes" | "calls" | "symbols" | "framework"; needsTarget?: boolean }> = [
  { label: "Overview", action: "full" },
  { label: "Repo Map", action: "repo" },
  { label: "Processes", action: "processes" },
  { label: "Call Graph", action: "calls", needsTarget: true },
  { label: "Symbols", action: "symbols", needsTarget: true },
  { label: "Framework", action: "framework", needsTarget: true },
];

export function PerspectivesPanel({ active, onAction }: PerspectivesPanelProps) {
  return (
    <section className="panel">
      <h3>Perspectives</h3>
      <div className="button-grid">
        {options.map((option) => (
          <button
            key={option.action}
            type="button"
            className={active === option.action ? "active" : ""}
            onClick={() => onAction(option.action)}
            title={option.needsTarget ? "Requires selected target" : undefined}
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  );
}
