import type { EditFileEntry, EditPlanResponse, EditRisk, EditTestEntry, ValidationCommand } from "../productApi";

interface Props {
  plan: EditPlanResponse;
}

export function EditPlanView({ plan }: Props) {
  return (
    <div className="edit-plan-grid">
      <section className="product-panel edit-plan-summary">
        <h2>Plan</h2>
        <p>{plan.summary}</p>
        {plan.warnings.length > 0 ? (
          <ul className="compact-list">
            {plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        ) : null}
      </section>
      <EntryPanel title="Files To Edit" entries={plan.files_likely_to_edit} />
      <EntryPanel title="Files To Read" entries={plan.files_to_read_only} />
      <TestPanel entries={plan.related_tests} />
      <RiskPanel risks={plan.risks} />
      <CommandPanel commands={plan.validation_commands} />
    </div>
  );
}

function EntryPanel({ title, entries }: { title: string; entries: EditFileEntry[] }) {
  return (
    <section className="product-panel">
      <h2>{title}</h2>
      {entries.length === 0 ? <p className="product-muted">None</p> : null}
      <ul className="entry-list">
        {entries.map((entry) => (
          <li key={entry.file}>
            <strong>{entry.file}</strong>
            <span>{entry.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TestPanel({ entries }: { entries: EditTestEntry[] }) {
  return (
    <section className="product-panel">
      <h2>Related Tests</h2>
      {entries.length === 0 ? <p className="product-muted">None</p> : null}
      <ul className="entry-list">
        {entries.map((entry) => (
          <li key={entry.file}>
            <strong>{entry.file}</strong>
            <span>{entry.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RiskPanel({ risks }: { risks: EditRisk[] }) {
  return (
    <section className="product-panel">
      <h2>Risks</h2>
      {risks.length === 0 ? <p className="product-muted">None</p> : null}
      <ul className="entry-list">
        {risks.map((risk) => (
          <li key={`${risk.title}-${risk.level}`}>
            <strong>{risk.title} · {risk.level}</strong>
            <span>{risk.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CommandPanel({ commands }: { commands: ValidationCommand[] }) {
  return (
    <section className="product-panel">
      <h2>Validation</h2>
      <ul className="entry-list command-list">
        {commands.map((command) => (
          <li key={command.command}>
            <code>{command.command}</code>
            <span>{command.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
