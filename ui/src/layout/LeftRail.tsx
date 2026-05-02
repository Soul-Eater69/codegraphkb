import type { ReactNode } from "react";

interface LeftRailProps {
  children: ReactNode;
}

export function LeftRail({ children }: LeftRailProps) {
  return (
    <aside className="left-rail">
      <div className="rail-spine" aria-label="Graph navigation">
        <div className="rail-logo">CG</div>
        <button type="button" className="active" title="Explorer">
          E
        </button>
        <button type="button" title="Filters">
          F
        </button>
        <button type="button" title="Processes">
          P
        </button>
        <div className="rail-spacer" />
        <button type="button" title="Settings">
          S
        </button>
      </div>
      <div className="rail-content">
        <div className="rail-tabs">
          <button type="button" className="active">
            Explorer
          </button>
          <button type="button">Filters</button>
        </div>
        {children}
      </div>
    </aside>
  );
}
