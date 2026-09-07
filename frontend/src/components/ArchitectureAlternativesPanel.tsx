type ArchitectureAlternative = {
  architecture_class?: string;
  label?: string;
  execution_location?: string;
  mobility?: string;
  catalog_relationship?: string;
  tradeoffs_to_verify?: string[];
};

export type ArchitectureAlternatives = {
  desired_outcome?: string;
  unresolved_inputs?: string[];
  alternatives?: ArchitectureAlternative[];
};

export default function ArchitectureAlternativesPanel({
  projection,
}: { projection: ArchitectureAlternatives }) {
  const alternatives = Array.isArray(projection.alternatives)
    ? projection.alternatives : [];
  if (!alternatives.length) return null;
  return (
    <section
      data-testid="architecture-alternatives"
      style={{ marginBottom: 12, padding: 14, border: '1px solid #c9d8ea', borderRadius: 10 }}
    >
      <strong>Choose where this workload should run</strong>
      <p style={{ margin: '6px 0 10px', fontSize: 13 }}>
        No form factor has been assumed. These are architecture options, not verified product recommendations.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(145px,1fr))', gap: 8 }}>
        {alternatives.map((item, index) => (
          <div key={`${item.architecture_class || item.label}-${index}`} style={{ padding: 10, border: '1px solid #dbe4ef', borderRadius: 8 }}>
            <strong>{item.label || item.architecture_class || 'Option'}</strong>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              {[item.execution_location, item.mobility].filter(Boolean).join(' · ')}
            </div>
            {(item.tradeoffs_to_verify || []).length > 0 && (
              <div style={{ fontSize: 12, marginTop: 5 }}>
                Verify: {(item.tradeoffs_to_verify || []).slice(0, 2).join('; ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
