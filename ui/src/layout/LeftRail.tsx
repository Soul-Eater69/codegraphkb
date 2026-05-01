import type { ReactNode } from "react";

interface LeftRailProps {
  children: ReactNode;
}

export function LeftRail({ children }: LeftRailProps) {
  return <aside className="left-rail">{children}</aside>;
}
