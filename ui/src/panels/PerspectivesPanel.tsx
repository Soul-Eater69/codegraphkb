import type { GraphView, Perspective } from "../types/graph";

interface PerspectivesPanelProps {
  active: Perspective;
  onSelectView: (view: GraphView) => void;
}

const options: Array<{ label: string; view: GraphView }> = [
  { label: "Repo Map", view: "repo" },
  { label: "Symbols", view: "symbols" },
  { label: "Call Graph", view: "calls" },
  { label: "Framework", view: "framework" },
  { label: "Processes", view: "processes" },
  { label: "Full", view: "full" },
];

export function PerspectivesPanel({ active, onSelectView }: PerspectivesPanelProps) {
  return (
    <section className="panel">
      <h3>Perspectives</h3>
      <div className="button-grid">
        {options.map((option) => (
          <button
            type="button"
            key={option.view}
            className={active === option.view ? "active" : ""}
            onClick={() => onSelectView(option.view)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </section>
  );
}
