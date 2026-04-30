import forceAtlas2 from "graphology-layout-forceatlas2";
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
  return { recommendedMs: 8000, isLarge: true };
}

export function createLayoutController(
  graph: SigmaGraph,
  onRunning: (running: boolean) => void,
): LayoutController {
  let running = false;
  let timer: number | null = null;
  let stopTimer: number | null = null;

  const stepIterations = graph.order > 3000 ? 3 : graph.order > 500 ? 8 : 14;
  const settings = forceAtlas2.inferSettings(graph);

  const stop = () => {
    if (!running) {
      return;
    }
    running = false;
    onRunning(false);
    if (timer != null) {
      window.clearInterval(timer);
      timer = null;
    }
    if (stopTimer != null) {
      window.clearTimeout(stopTimer);
      stopTimer = null;
    }
    try {
      noverlap.assign(graph, { maxIterations: 140, settings: { ratio: 1.1 } });
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

    const { recommendedMs } = layoutStateFor(graph);
    timer = window.setInterval(() => {
      try {
        forceAtlas2.assign(graph, {
          iterations: stepIterations,
          settings,
        });
      } catch {
        stop();
      }
    }, 100);

    stopTimer = window.setTimeout(() => {
      stop();
    }, recommendedMs);
  };

  return {
    start,
    stop,
    toggle: () => {
      if (running) {
        stop();
      } else {
        start();
      }
    },
    isRunning: () => running,
    cleanup: stop,
  };
}
