interface AskPanelProps {
  onOpen: () => void;
}

export function AskPanel({ onOpen }: AskPanelProps) {
  return (
    <div className="ask-panel">
      <h3>Ask CodeGraphKB</h3>
      <p className="muted">Generate a context pack from current selection and use it for edits, review, or impact checks.</p>
      <button type="button" onClick={onOpen}>
        Open Context Preview
      </button>
    </div>
  );
}
