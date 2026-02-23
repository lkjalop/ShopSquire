import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchSCScenarios,
  runSCScenario,
  runSCAll,
  startSCSwarm,
  fetchSCSwarm,
  streamSCAll,
  type SCScenario,
  type SCSimResult,
  type SCThinkingStep,
  type SCSwarmJob,
} from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

const SEV_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#22c55e',
  info: '#6b7280',
};

const VERDICT_COLORS: Record<string, string> = {
  PASS: '#22c55e',
  PARTIAL: '#eab308',
  FAIL: '#ef4444',
  ERROR: '#9333ea',
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        color: '#fff',
        background: color,
        marginRight: 4,
        marginBottom: 2,
      }}
    >
      {label}
    </span>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: '#1e1e2e',
        border: '1px solid #333',
        borderRadius: 8,
        padding: 16,
        marginBottom: 12,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// ---- Thinking Step Timeline ----
function ThinkingTimeline({ steps, scenarioId }: { steps: SCThinkingStep[]; scenarioId?: string }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      {/* vertical line */}
      <div
        style={{
          position: 'absolute',
          left: 10,
          top: 0,
          bottom: 0,
          width: 2,
          background: '#444',
        }}
      />
      {steps.map((s) => (
        <div key={s.step_id} style={{ position: 'relative', marginBottom: 8 }}>
          <div
            style={{
              position: 'absolute',
              left: -18,
              top: 6,
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: s.outputs?.escalated ? '#ef4444' : '#3b82f6',
              border: '2px solid #1e1e2e',
            }}
          />
          <div
            style={{ cursor: 'pointer', padding: '4px 0' }}
            onClick={() => setExpanded(expanded === s.step_id ? null : s.step_id)}
          >
            <span style={{ fontWeight: 600, color: '#e2e8f0', fontSize: 13 }}>
              {s.agent}
            </span>
            <span style={{ color: '#94a3b8', fontSize: 12, marginLeft: 8 }}>{s.action}</span>
            <span style={{ color: '#64748b', fontSize: 11, marginLeft: 8 }}>
              {s.duration_ms.toFixed(0)}ms
            </span>
          </div>
          {expanded === s.step_id && (
            <div style={{ background: '#262637', padding: 10, borderRadius: 6, fontSize: 12, marginTop: 4 }}>
              <div style={{ color: '#a5b4fc', marginBottom: 6, whiteSpace: 'pre-wrap' }}>{s.reasoning}</div>
              {Object.keys(s.outputs || {}).length > 0 && (
                <details>
                  <summary style={{ color: '#64748b', cursor: 'pointer' }}>Outputs</summary>
                  <pre style={{ color: '#94a3b8', fontSize: 11, maxHeight: 200, overflow: 'auto' }}>
                    {JSON.stringify(s.outputs, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---- Agent Chain Diagram ----
function AgentChain({ chain }: { chain: SCSimResult['agent_chain'] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
      {chain.map((a, i) => (
        <React.Fragment key={a.agent_id}>
          <span
            style={{
              display: 'inline-block',
              padding: '3px 8px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              background: a.status === 'done' ? '#1e3a5f' : '#3a1e1e',
              color: a.status === 'done' ? '#60a5fa' : '#f87171',
              border: `1px solid ${a.status === 'done' ? '#2563eb44' : '#ef444444'}`,
            }}
            title={a.role}
          >
            {a.agent_id}
          </span>
          {i < chain.length - 1 && <span style={{ color: '#475569', fontSize: 14 }}>→</span>}
        </React.Fragment>
      ))}
    </div>
  );
}

// ---- Scenario Result Card ----
function ScenarioResult({ result }: { result: SCSimResult }) {
  const [showTrace, setShowTrace] = useState(false);
  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontWeight: 700, color: '#e2e8f0', fontSize: 14 }}>{result.scenario_id} — {result.scenario_name}</div>
          <div style={{ marginTop: 4 }}>
            <Badge label={result.pass_fail} color={VERDICT_COLORS[result.pass_fail] || '#6b7280'} />
            <Badge label={result.severity} color={SEV_COLORS[result.severity] || '#6b7280'} />
            {result.human_escalation_triggered && <Badge label="ESCALATED" color="#ef4444" />}
          </div>
        </div>
        <div style={{ textAlign: 'right', fontSize: 11, color: '#64748b' }}>
          <div>{result.elapsed_ms.toFixed(0)}ms</div>
          <div title={result.trace_id}>trace: {result.trace_id.slice(0, 8)}…</div>
        </div>
      </div>

      {/* Signals */}
      {result.signals_detected.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <span style={{ fontSize: 11, color: '#64748b' }}>Signals: </span>
          {result.signals_detected.map((s) => (
            <Badge key={s} label={s} color="#4338ca" />
          ))}
        </div>
      )}

      {/* Agent chain */}
      <AgentChain chain={result.agent_chain} />

      {/* Toggle thinking trace */}
      <button
        onClick={() => setShowTrace(!showTrace)}
        style={{
          marginTop: 8,
          background: 'none',
          border: '1px solid #374151',
          color: '#94a3b8',
          fontSize: 11,
          padding: '3px 10px',
          borderRadius: 4,
          cursor: 'pointer',
        }}
      >
        {showTrace ? 'Hide' : 'Show'} Interleaved Thinking ({result.thinking_steps.length} steps)
      </button>
      {showTrace && (
        <div style={{ marginTop: 8 }}>
          <ThinkingTimeline steps={result.thinking_steps} scenarioId={result.scenario_id} />
        </div>
      )}

      {/* MITRE / Bitemporal metadata */}
      <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: 11, color: '#64748b' }}>
        <div>
          <strong>Bitemporal:</strong> valid_from={result.bitemporal?.valid_from?.slice(0, 19) || '-'}
        </div>
        {result.risk_analysis?.mitre_atlas && (
          <div>
            <strong>MITRE:</strong> {(result.risk_analysis.mitre_atlas as string[]).join(', ')}
          </div>
        )}
      </div>
    </Card>
  );
}

// ---- Main Component ----
export function SupplyChainSim({ role }: Props) {
  const [scenarios, setScenarios] = useState<SCScenario[]>([]);
  const [results, setResults] = useState<SCSimResult[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [liveSteps, setLiveSteps] = useState<(SCThinkingStep & { scenario_id?: string })[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Swarm state
  const [swarmJob, setSwarmJob] = useState<SCSwarmJob | null>(null);
  const [swarmRounds, setSwarmRounds] = useState(1);
  const [swarmPolling, setSwarmPolling] = useState(false);

  const [selectedScenario, setSelectedScenario] = useState<SCScenario | null>(null);
  const [singleResult, setSingleResult] = useState<SCSimResult | null>(null);
  const [singleLoading, setSingleLoading] = useState(false);

  // Load catalogue
  useEffect(() => {
    fetchSCScenarios()
      .then(setScenarios)
      .catch((e) => setError(e.message));
  }, []);

  // Run all (JSON)
  const handleRunAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResults([]);
    setSummary(null);
    try {
      const data = await runSCAll();
      setResults(data.results);
      setSummary(data.summary);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Run all with SSE
  const handleStreamAll = useCallback(() => {
    setStreaming(true);
    setError(null);
    setResults([]);
    setSummary(null);
    setLiveSteps([]);

    const collected: SCSimResult[] = [];
    const es = streamSCAll();

    es.addEventListener('agent_step', (e: MessageEvent) => {
      try {
        const step = JSON.parse(e.data);
        setLiveSteps((prev) => [...prev, step]);
      } catch {}
    });

    es.addEventListener('scenario_result', (e: MessageEvent) => {
      try {
        const r = JSON.parse(e.data) as SCSimResult;
        collected.push(r);
        setResults([...collected]);
      } catch {}
    });

    es.addEventListener('summary', (e: MessageEvent) => {
      try {
        setSummary(JSON.parse(e.data));
      } catch {}
    });

    es.addEventListener('done', () => {
      es.close();
      setStreaming(false);
    });

    es.addEventListener('error', () => {
      es.close();
      setStreaming(false);
      setError('Stream connection lost');
    });
  }, []);

  // Run single
  const handleRunSingle = useCallback(async (id: string) => {
    setSingleLoading(true);
    setSingleResult(null);
    try {
      const r = await runSCScenario(id);
      setSingleResult(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSingleLoading(false);
    }
  }, []);

  // Swarm
  const handleSwarm = useCallback(async () => {
    setError(null);
    try {
      const job = await startSCSwarm(swarmRounds);
      setSwarmJob({ ...job, status: 'queued' } as SCSwarmJob);
      setSwarmPolling(true);
    } catch (e: any) {
      setError(e.message);
    }
  }, [swarmRounds]);

  // Poll swarm status
  useEffect(() => {
    if (!swarmPolling || !swarmJob?.job_id) return;
    const iv = setInterval(async () => {
      try {
        const j = await fetchSCSwarm(swarmJob.job_id);
        setSwarmJob(j);
        if (j.status === 'completed' || j.status === 'failed') {
          setSwarmPolling(false);
        }
      } catch {}
    }, 2000);
    return () => clearInterval(iv);
  }, [swarmPolling, swarmJob?.job_id]);

  return (
    <div style={{ color: '#e2e8f0', maxWidth: 1100 }}>
      {error && (
        <div style={{ background: '#3a1e1e', border: '1px solid #ef4444', borderRadius: 6, padding: '8px 12px', marginBottom: 12, fontSize: 13, color: '#fca5a5' }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 8, background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Controls */}
      <Card style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={handleRunAll}
          disabled={loading || streaming}
          style={{ padding: '6px 16px', borderRadius: 6, border: 'none', background: '#2563eb', color: '#fff', fontWeight: 600, cursor: 'pointer', opacity: loading || streaming ? 0.5 : 1 }}
        >
          {loading ? 'Running…' : 'Run All Scenarios'}
        </button>
        <button
          onClick={handleStreamAll}
          disabled={loading || streaming}
          style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #2563eb', background: 'transparent', color: '#60a5fa', fontWeight: 600, cursor: 'pointer', opacity: loading || streaming ? 0.5 : 1 }}
        >
          {streaming ? `Streaming (${liveSteps.length} steps)…` : 'Stream All (Real-time)'}
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <label style={{ fontSize: 12, color: '#94a3b8' }}>Swarm rounds:</label>
          <input
            type="number"
            min={1}
            max={10}
            value={swarmRounds}
            onChange={(e) => setSwarmRounds(Math.max(1, Math.min(10, Number(e.target.value))))}
            style={{ width: 50, background: '#262637', border: '1px solid #444', color: '#e2e8f0', borderRadius: 4, padding: '4px 6px', fontSize: 12 }}
          />
          <button
            onClick={handleSwarm}
            disabled={swarmPolling}
            style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #7c3aed', background: 'transparent', color: '#a78bfa', fontWeight: 600, cursor: 'pointer', opacity: swarmPolling ? 0.5 : 1 }}
          >
            {swarmPolling ? 'Swarm running…' : 'Launch Swarm'}
          </button>
        </div>
      </Card>

      {/* Summary */}
      {summary && (
        <Card style={{ display: 'flex', gap: 24, justifyContent: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#e2e8f0' }}>{summary.total}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Total</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#22c55e' }}>{summary.pass}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Pass</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#eab308' }}>{summary.partial}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Partial</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: '#ef4444' }}>{summary.fail}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>Fail</div>
          </div>
        </Card>
      )}

      {/* Swarm job status */}
      {swarmJob && (
        <Card>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6 }}>
            Parallel Swarm Job
            <Badge label={swarmJob.status} color={swarmJob.status === 'completed' ? '#22c55e' : swarmJob.status === 'running' ? '#3b82f6' : '#64748b'} />
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>Job: {swarmJob.job_id}</div>
          {swarmJob.summary && (
            <div style={{ marginTop: 8, display: 'flex', gap: 16, fontSize: 13 }}>
              <span>Total runs: <strong>{swarmJob.summary.total_runs}</strong></span>
              <span>Pass rate: <strong>{(swarmJob.summary.pass_rate * 100).toFixed(1)}%</strong></span>
              <span>Rounds: <strong>{swarmJob.summary.rounds_completed}</strong></span>
            </div>
          )}
          {swarmJob.rounds?.map((rnd) => (
            <details key={rnd.round} style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: '#94a3b8' }}>
                Round {rnd.round} — {rnd.results.length} scenarios
              </summary>
              <div style={{ marginLeft: 16, fontSize: 11 }}>
                {rnd.results.map((r: any, i: number) => (
                  <div key={i} style={{ padding: '2px 0' }}>
                    <Badge label={r.pass_fail || 'ERROR'} color={VERDICT_COLORS[r.pass_fail] || '#9333ea'} />
                    <span style={{ color: '#e2e8f0' }}>{r.scenario_id}</span>
                    <span style={{ color: '#64748b', marginLeft: 8 }}>{r.severity} {r.elapsed_ms ? `${r.elapsed_ms.toFixed(0)}ms` : ''}</span>
                    {r.escalated && <Badge label="ESC" color="#ef4444" />}
                  </div>
                ))}
              </div>
            </details>
          ))}
        </Card>
      )}

      {/* Live streaming steps */}
      {streaming && liveSteps.length > 0 && (
        <Card>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 6, color: '#60a5fa' }}>
            Live Agent Steps
          </div>
          <div style={{ maxHeight: 300, overflow: 'auto' }}>
            {liveSteps.map((s, i) => (
              <div key={i} style={{ padding: '3px 0', fontSize: 12, borderBottom: '1px solid #333' }}>
                <Badge label={s.scenario_id || '?'} color="#4338ca" />
                <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{s.agent}</span>
                <span style={{ color: '#94a3b8', marginLeft: 8 }}>{s.action}</span>
                <span style={{ color: '#64748b', marginLeft: 8 }}>{s.duration_ms?.toFixed(0)}ms</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Results list */}
      {results.length > 0 && (
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 8 }}>Simulation Results</h3>
          {results.map((r) => (
            <ScenarioResult key={r.trace_id} result={r} />
          ))}
        </div>
      )}

      {/* Scenario catalogue */}
      {scenarios.length > 0 && results.length === 0 && !loading && !streaming && (
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 8 }}>
            Attack Scenarios ({scenarios.length})
          </h3>
          {scenarios.map((sc) => (
            <Card key={sc.scenario_id}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 700, color: '#e2e8f0', fontSize: 14 }}>{sc.scenario_id} — {sc.name}</div>
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{sc.description}</div>
                  <div style={{ marginTop: 6 }}>
                    <Badge label={sc.expected_severity} color={SEV_COLORS[sc.expected_severity] || '#6b7280'} />
                    {sc.human_escalation_expected && <Badge label="Escalation Expected" color="#f97316" />}
                  </div>
                  <div style={{ marginTop: 4 }}>
                    {sc.mitre_attack.map((t) => (
                      <Badge key={t} label={t} color="#1e3a5f" />
                    ))}
                  </div>
                  <div style={{ marginTop: 4, fontSize: 11, color: '#64748b' }}>
                    Kill chain: {sc.kill_chain.join(' → ')}
                  </div>
                </div>
                <button
                  onClick={() => { setSelectedScenario(sc); handleRunSingle(sc.scenario_id); }}
                  disabled={singleLoading}
                  style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid #2563eb', background: 'transparent', color: '#60a5fa', fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap' }}
                >
                  Run
                </button>
              </div>
              {singleResult && selectedScenario?.scenario_id === sc.scenario_id && (
                <div style={{ marginTop: 12, borderTop: '1px solid #333', paddingTop: 12 }}>
                  <ScenarioResult result={singleResult} />
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
