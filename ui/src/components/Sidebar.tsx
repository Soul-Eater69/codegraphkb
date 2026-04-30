import type { ReactNode } from "react";

export type SidebarTab = "Explorer" | "Filters" | "Processes" | "Impact";

interface SidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  children: ReactNode;
  collapsed?: boolean;
}

const tabs: SidebarTab[] = ["Explorer", "Filters", "Processes", "Impact"];

export function Sidebar({ activeTab, onTabChange, children, collapsed = false }: SidebarProps) {
  if (collapsed) {
    return (
      <aside className="sidebar sidebar-collapsed">
        <div className="sidebar-tabs vertical">
          {tabs.map((tab) => (
            <button key={tab} type="button" className={tab === activeTab ? "active" : ""} onClick={() => onTabChange(tab)} title={tab}>
              {tab.charAt(0)}
            </button>
          ))}
        </div>
      </aside>
    );
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-tabs">
        {tabs.map((tab) => (
          <button key={tab} type="button" className={tab === activeTab ? "active" : ""} onClick={() => onTabChange(tab)}>
            {tab}
          </button>
        ))}
      </div>
      <div className="sidebar-content">{children}</div>
    </aside>
  );
}
