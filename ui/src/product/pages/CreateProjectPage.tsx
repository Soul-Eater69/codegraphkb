import { GithubImportForm } from "../components/GithubImportForm";
import { UploadZipForm } from "../components/UploadZipForm";

interface Props {
  onBack: () => void;
  onCreated: (projectId: string) => void;
}

export function CreateProjectPage({ onBack, onCreated }: Props) {
  return (
    <main className="product-page">
      <div className="product-page-heading">
        <div>
          <h1>New Project</h1>
          <p>GitHub URL or ZIP archive</p>
        </div>
        <button type="button" onClick={onBack}>Projects</button>
      </div>
      <div className="create-project-grid">
        <GithubImportForm onCreated={onCreated} />
        <UploadZipForm onCreated={onCreated} />
      </div>
    </main>
  );
}
