import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2LayoutSupervisor from "graphology-layout-forceatlas2/worker";
import noverlap from "graphology-layout-noverlap";
import type { SigmaGraph } from "./adapter";

export interface LayoutController {
  start: () => void;
  stop: () => void;
  toggle: () => void;
  isRunning: () => boolean;
  cleanup: () => void;
}

export interface LayoutState {
  recommendedMs: number;
  isLarge: boolean;
}

export function layoutStateFor(graph: SigmaGraph): LayoutState {
  const n = graph.order;
  if (n < 500) {
    return { recommendedMs: 10000, isLarge: false };
  }
  if (n <= 3000) {
    return { recommendedMs: 18000, isLarge: false };
  }
  return { recommendedMs: 7000, isLarge: true };
}

export function createLayoutController(
  graph: SigmaGraph,
  onRunning: (running: boolean) => void,
): LayoutController {
  let running = false;
  let stopTimer: number | null = null;

  const settings = forceAtlas2.inferSettings(graph);
  const worker = new FA2LayoutSupervisor(graph, {
    settings: {
      ...settings,
      gravity: graph.order > 2500 ? 0.35 : 0.5,
      slowDown: graph.order > 2500 ? 8 : 5.5,
      scalingRatio: graph.order > 2500 ? 6 : 4.5,
      barnesHutOptimize: true,
    },
  });

  const stop = () => {
    if (!running) {
      return;
    }
    running = false;
    worker.stop();
    onRunning(false);
    if (stopTimer != null) {
      window.clearTimeout(stopTimer);
      stopTimer = null;
    }
    try {
      noverlap.assign(graph, { maxIterations: 140, settings: { ratio: 1.12 } });
    } catch {
      // no-op
    }
  };

  const start = () => {
    if (running) {
      return;
    }
    running = true;
    onRunning(true);
    worker.start();
    const { recommendedMs } = layoutStateFor(graph);
    stopTimer = window.setTimeout(() => {
      stop();
    }, recommendedMs);
  };

  return {
    start,
    stop,
    toggle() {
      if (running) {
        stop();
      } else {
        start();
      }
    },
    isRunning: () => running,
    cleanup() {
      stop();
      worker.kill();
    },
  };
}
