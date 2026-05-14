import { useState } from "react";
import { createGithubProject } from "../productApi";

interface Props {
  onCreated: (projectId: string) => void;
}

export function GithubImportForm({ onCreated }: Props) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await createGithubProject(url, name || undefined);
      onCreated(result.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="product-form" onSubmit={(event) => void submit(event)}>
      <h2>GitHub URL</h2>
      <label>
        <span>Repository URL</span>
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://github.com/owner/repo" required />
      </label>
      <label>
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional" />
      </label>
      {error ? <p className="product-error-text">{error}</p> : null}
      <button type="submit" disabled={submitting}>{submitting ? "Importing" : "Import"}</button>
    </form>
  );
}
