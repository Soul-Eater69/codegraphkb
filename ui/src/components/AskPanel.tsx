interface AskPanelProps {
  onOpen: () => void;
}

export function AskPanel({ onOpen }: AskPanelProps) {
  return (
    <div className="ask-panel">
      <h3>Ask CodeGraphKB</h3>
      <p className="muted">
        Context generation from graph selections arrives in UI-3/UI-5. This button keeps the workflow visible now.
      </p>
      <button type="button" onClick={onOpen}>
        Open Ask Placeholder
      </button>
    </div>
  );
}
