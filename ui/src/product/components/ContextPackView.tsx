import type { ContextItem, ContextPackResponse } from "../productApi";

interface Props {
  pack: ContextPackResponse;
}

export function ContextPackView({ pack }: Props) {
  return (
    <section className="product-panel">
      <div className="product-panel-heading">
        <h2>Context</h2>
        <span>{pack.estimated_tokens.toLocaleString()} tokens</span>
      </div>
      <div className="context-list">
        {pack.items.map((item, index) => (
          <ContextItemRow key={`${item.title}-${index}`} item={item} />
        ))}
      </div>
    </section>
  );
}

function ContextItemRow({ item }: { item: ContextItem }) {
  return (
    <article className="context-item">
      <div>
        <strong>{item.title}</strong>
        <span>{item.kind} · {item.file_path || "workspace"}</span>
      </div>
      <div className="context-item-score">{item.score.toFixed(2)}</div>
      {item.body ? <pre>{item.body}</pre> : null}
    </article>
  );
}
