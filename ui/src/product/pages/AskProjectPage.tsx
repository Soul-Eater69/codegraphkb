import { useState } from "react";
import { ContextPackView } from "../components/ContextPackView";
import { askProject, type AskResponse, type ContextPackResponse } from "../productApi";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function AskProjectPage({ projectId, onBack }: Props) {
  const [question, setQuestion] = useState("");
  const [contextOnly, setContextOnly] = useState(true);
  const [result, setResult] = useState<ContextPackResponse | AskResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      setResult(await askProject(projectId, question, contextOnly));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const pack = result && "items" in result ? result : result?.context;

  return (
    <main className="product-page">
      <div className="product-page-heading">
        <div>
          <h1>Ask Project</h1>
          <p>{projectId}</p>
        </div>
        <button type="button" onClick={onBack}>Project</button>
      </div>
      <form className="product-panel product-query-form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>Question</span>
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={4} required />
        </label>
        <label className="checkbox-row">
          <input type="checkbox" checked={contextOnly} onChange={(event) => setContextOnly(event.target.checked)} />
          <span>Context only</span>
        </label>
        {error ? <p className="product-error-text">{error}</p> : null}
        <button type="submit" disabled={submitting}>{submitting ? "Asking" : "Ask"}</button>
      </form>
      {result && "answer" in result && result.answer ? (
        <section className="product-panel">
          <h2>Answer</h2>
          <p>{result.answer}</p>
        </section>
      ) : null}
      {pack ? <ContextPackView pack={pack} /> : null}
    </main>
  );
}
