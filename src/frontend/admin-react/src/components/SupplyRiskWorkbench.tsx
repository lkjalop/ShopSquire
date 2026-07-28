import { useEffect, useState } from 'react';
import {
  supplyRiskScenarios,
  supplyRiskWorkbench,
  type SupplyRiskScenario,
  type SupplyRiskWorkbench as Workbench,
} from '../api';

export function SupplyRiskWorkbench({ authReady = true }: { authReady?: boolean }) {
  const [scenarios, setScenarios] = useState<SupplyRiskScenario[]>([]);
  const [selected, setSelected] = useState('');
  const [data, setData] = useState<Workbench | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!authReady) return;
    supplyRiskScenarios()
      .then((result) => {
        setScenarios(result.scenarios);
        setSelected((current) => current || result.scenarios[0]?.scenario_id || '');
      })
      .catch((err: any) => setError(err?.message || 'Supply-risk scenarios unavailable'));
  }, [authReady]);

  useEffect(() => {
    if (!authReady || !selected) return;
    setBusy(true);
    setError(null);
    supplyRiskWorkbench(selected)
      .then(setData)
      .catch((err: any) => setError(err?.message || 'Supply-risk evidence unavailable'))
      .finally(() => setBusy(false));
  }, [authReady, selected]);

  return (
    <section className="card" data-testid="supply-risk-workbench" style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: 0 }}>Causal supply-risk workbench</h3>
          <div className="page-sub">
            Dependency evidence and bounded options. This simulation cannot execute procurement.
          </div>
        </div>
        <label style={{ marginLeft: 'auto' }}>
          Scenario{' '}
          <select
            aria-label="Supply-risk scenario"
            value={selected}
            disabled={busy}
            onChange={(event) => setSelected(event.target.value)}
          >
            {scenarios.map((scenario) => (
              <option key={scenario.scenario_id} value={scenario.scenario_id}>
                {scenario.scenario_id.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </label>
      </div>

      {busy && !data && <p>Evaluating replay…</p>}
      {error && <p role="alert" style={{ color: 'crimson' }}>{error}</p>}
      {data && (
        <>
          <div data-testid="supply-risk-trust-labels" style={{
            display: 'flex', gap: 8, flexWrap: 'wrap', margin: '12px 0',
          }}>
            <span className="badge">Authority: {data.authority.replace(/_/g, ' ').toUpperCase()}</span>
            <span className="badge">Execution: {data.execution_allowed ? 'ALLOWED' : 'PROHIBITED'}</span>
            <span className="badge">Tenant: {data.tenant_id}</span>
            <span className="badge">Confidence: {data.confidence == null ? 'UNDEFINED' : `${(data.confidence * 100).toFixed(0)}%`}</span>
            <span className="badge">PESTEL: {data.pestel_domains.join(', ') || 'UNDECLARED'}</span>
          </div>

          <div className="grid-2">
            <div>
              <h4>Estimated impact</h4>
              {data.impact ? (
                <dl>
                  <dt>Landed-cost range</dt>
                  <dd>
                    {data.impact.landed_cost_change_pct.low.toFixed(2)}%–
                    {data.impact.landed_cost_change_pct.high.toFixed(2)}%
                  </dd>
                  <dt>Availability direction</dt>
                  <dd>{data.impact.availability_direction}</dd>
                  <dt>Causal wording</dt>
                  <dd>{data.causal_language?.replace(/_/g, ' ')}</dd>
                </dl>
              ) : <p>No verified exposure path.</p>}
            </div>
            <div>
              <h4>Completeness and contradictions</h4>
              <div>Dependency path: {data.completeness.dependency_path ? 'present' : 'missing'}</div>
              <div>Signal provenance: {data.completeness.signal_provenance ? 'present' : 'missing'}</div>
              <div>Official candidates: {data.completeness.official_source_candidates ? 'present' : 'missing'}</div>
              <div>Contradictions: {data.contradictions.status.replace(/_/g, ' ')}</div>
              <small>{data.contradictions.policy}</small>
              {(data.completeness.missing_evidence || []).length > 0 && (
                <ul>
                  {data.completeness.missing_evidence.map((item: string) => (
                    <li key={item}>Missing: {item.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <h4>Dependency paths</h4>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%' }}>
              <thead>
                <tr><th>Signal</th><th>Path</th><th>Estimated cost effect</th><th>Confidence</th></tr>
              </thead>
              <tbody>
                {data.dependency_paths.map((path) => (
                  <tr key={`${path.signal_id}-${path.edge_ids.join('-')}`}>
                    <td>{path.signal_type.replace(/_/g, ' ')}</td>
                    <td>{path.node_path.join(' → ')}</td>
                    <td>
                      {path.estimated_landed_cost_change_pct.low.toFixed(2)}%–
                      {path.estimated_landed_cost_change_pct.high.toFixed(2)}%
                    </td>
                    <td>{(path.confidence * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4>Signals, provenance and licensed source candidates</h4>
          {data.signals.map((signal) => (
            <details key={signal.id}>
              <summary>
                {signal.signal_type.replace(/_/g, ' ')} · {signal.freshness.age_days} days old ·
                {' '}{(signal.confidence * 100).toFixed(0)}% confidence
              </summary>
              <div>Provenance: {signal.provenance_chain.join(' → ')}</div>
              {signal.official_source_candidates.length === 0 ? (
                <div>Official source adapter: missing</div>
              ) : signal.official_source_candidates.map((source) => (
                <div key={source.source_id}>
                  {source.publisher} · {source.trust_tier} · {source.measurement_scope} ·{' '}
                  <a href={source.licence_url} target="_blank" rel="noreferrer">
                    {source.licence_id}
                  </a>
                </div>
              ))}
            </details>
          ))}

          <div className="grid-2" style={{ marginTop: 12 }}>
            <div>
              <h4>Alternative explanations</h4>
              <ul>{data.alternatives.map((item) => <li key={item}>{item.replace(/_/g, ' ')}</li>)}</ul>
            </div>
            <div>
              <h4>Bounded procurement options</h4>
              <ul>
                {data.procurement_options.options.map((option) => (
                  <li key={option.action_type}>
                    <strong>{option.action_type.replace(/_/g, ' ')}</strong>
                    {' — '}{option.tradeoffs.join('; ')}
                    {option.requires_human_approval ? ' — human approval required' : ''}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default SupplyRiskWorkbench;
