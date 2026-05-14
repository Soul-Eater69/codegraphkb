import { useState } from "react";
import { uploadZipProject } from "../productApi";

interface Props {
  onCreated: (projectId: string) => void;
}

export function UploadZipForm({ onCreated }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Choose a ZIP file");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await uploadZipProject(file, name || undefined);
      onCreated(result.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="product-form" onSubmit={(event) => void submit(event)}>
      <h2>ZIP Upload</h2>
      <label>
        <span>Archive</span>
        <input type="file" accept=".zip,application/zip" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
      </label>
      <label>
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional" />
      </label>
      {error ? <p className="product-error-text">{error}</p> : null}
      <button type="submit" disabled={submitting}>{submitting ? "Uploading" : "Upload"}</button>
    </form>
  );
}
