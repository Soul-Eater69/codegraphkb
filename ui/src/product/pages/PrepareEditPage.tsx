import { useState } from "react";
import { EditPlanView } from "../components/EditPlanView";
import { prepareEdit, type EditPlanResponse } from "../productApi";

interface Props {
  projectId: string;
  onBack: () => void;
}

export function PrepareEditPage({ projectId, onBack }: Props) {
  const [task, setTask] = useState("");
  const [plan, setPlan] = useState<EditPlanResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      setPlan(await prepareEdit(projectId, task));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="product-page">
      <div className="product-page-heading">
        <div>
          <h1>Prepare Edit</h1>
          <p>{projectId}</p>
        </div>
        <button type="button" onClick={onBack}>Project</button>
      </div>
      <form className="product-panel product-query-form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>Task</span>
          <textarea value={task} onChange={(event) => setTask(event.target.value)} rows={4} required />
        </label>
        {error ? <p className="product-error-text">{error}</p> : null}
        <button type="submit" disabled={submitting}>{submitting ? "Preparing" : "Prepare"}</button>
      </form>
      {plan ? <EditPlanView plan={plan} /> : null}
    </main>
  );
}
