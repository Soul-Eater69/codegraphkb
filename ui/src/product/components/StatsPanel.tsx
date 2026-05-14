import type { ProjectStats } from "../productApi";

interface Props {
  stats: ProjectStats | null;
}

export function StatsPanel({ stats }: Props) {
  const languages = stats?.languages ?? {};
  return (
    <section className="product-panel">
      <div className="stats-grid">
        <Metric label="Files" value={stats?.files ?? 0} />
        <Metric label="Symbols" value={stats?.symbols ?? 0} />
        <Metric label="Edges" value={stats?.edges ?? 0} />
        <Metric label="Embeddings" value={stats?.embeddings ?? 0} />
      </div>
      {Object.keys(languages).length > 0 ? (
        <div className="language-row">
          {Object.entries(languages).map(([language, count]) => (
            <span key={language}>{language}: {count}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat-cell">
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}
