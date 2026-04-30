import type { ReactNode } from "react";

export type SidebarTab = "Explorer" | "Filters" | "Processes" | "Impact";

interface SidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  children: ReactNode;
}

const tabs: SidebarTab[] = ["Explorer", "Filters", "Processes", "Impact"];

export function Sidebar({ activeTab, onTabChange, children }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-tabs">
        {tabs.map((tab) => (
          <button
            key={tab}
            type="button"
            className={tab === activeTab ? "active" : ""}
            onClick={() => onTabChange(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="sidebar-content">{children}</div>
    </aside>
  );
}
