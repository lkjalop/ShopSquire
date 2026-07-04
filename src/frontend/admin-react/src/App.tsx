import React, { useEffect, useMemo, useState } from 'react';
import { Overview } from './components/Overview';
import { Decisions } from './components/Decisions';
import { Security } from './components/Security';
import { Approvals } from './components/Approvals';
import { OwnerPanel } from './components/OwnerPanel';
import { DeveloperPanel } from './components/DeveloperPanel';
import { Incidents } from './components/Incidents';
import { EmailIncidents } from './components/EmailIncidents';
import { RulesAdmin } from './components/RulesAdmin';
import { Orders } from './components/Orders';
import { Analytics } from './components/Analytics';
import { Compliance } from './components/Compliance';
import { GRC } from './components/GRC';
import { GrafanaDashboards } from './components/GrafanaDashboards';
import { InventorySync } from './components/InventorySync';
import { CVIncidents } from './components/CVIncidents';
import { Playbooks } from './components/Playbooks';
import { MerchantBIPro } from './components/MerchantBIPro';
import { EscalationsConsole } from './components/EscalationsConsole';
import { ProcurementCases } from './components/ProcurementCases';
import { MarketIntelligence } from './components/MarketIntelligence';
import { InvestorMetrics } from './components/InvestorMetrics';
import { EmailXdr } from './components/EmailXdr';
import { SupplyChainSim } from './components/SupplyChainSim';
import { AgentIntelligence } from './components/AgentIntelligence';
import { MaestroRegistry } from './components/MaestroRegistry';
import { fetchMe, setApiKeyCookie, setClientApiKey } from './api';

type Role = 'merchant' | 'owner' | 'developer';

export default function App() {
  const [active, setActive] = useState('overview');
  const [incidentIdParam, setIncidentIdParam] = useState<string | null>(null);
  const [role, setRole] = useState<Role>('merchant');
  const [allowedRoles, setAllowedRoles] = useState<Role[]>(['merchant']);
  const [authReady, setAuthReady] = useState(false);
  const [showKeyPrompt, setShowKeyPrompt] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [authVersion, setAuthVersion] = useState(0);
  const [authError, setAuthError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const _TAB_KEYWORDS: Record<string, string[]> = {
    decisions: ['decision', 'decisions', 'log', 'audit'],
    security: ['security', 'event', 'events', 'threat', 'attack', 'mitre'],
    overview: ['overview', 'summary', 'dashboard'],
    'email-xdr': ['email', 'phishing', 'xdr', 'bec'],
    escalations: ['escalation', 'escalate', 'incident'],
    rules: ['rule', 'rules', 'policy'],
    approvals: ['approval', 'approvals', 'approve'],
    orders: ['order', 'orders'],
    analytics: ['analytics', 'ragas', 'eval'],
    compliance: ['compliance', 'gdpr', 'pci'],
    grc: ['grc', 'risk'],
    'cv-incidents': ['cv', 'image', 'computer vision'],
    'merchant-bi': ['bi', 'metrics', 'kpi'],
    playbooks: ['playbook', 'runbook'],
    maestro: ['maestro', 'agentic', 'boundary', 'sc-04b', 'agent boundary', 'csa'],
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim().toLowerCase();
    if (!q) return;
    for (const [tab, kws] of Object.entries(_TAB_KEYWORDS)) {
      if (kws.some((k) => q.includes(k) || k.includes(q))) {
        setActive(tab);
        setSearchQuery('');
        return;
      }
    }
    // Fallback: route decisions for unrecognised queries
    setActive('decisions');
    setSearchQuery('');
  };

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const tab = params.get('tab');
      const incidentId = params.get('incident_id');
      if (tab) setActive(tab);
      if (incidentId) {
        setIncidentIdParam(incidentId);
        if (!tab) setActive('escalations');
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchMe()
      .then((data) => {
        const allowed = (data.allowed_roles || [data.role]) as Role[];
        setAllowedRoles(allowed);
        setRole(data.role);
        if (!new URLSearchParams(window.location.search).get('tab')) {
          setActive('overview');
        }
        setAuthError('');
      })
      .catch((err: any) => {
        setAllowedRoles(['merchant']);
        if (err?.status === 401 || err?.status === 403) {
          setAuthError('Invalid or missing API key. Please set a valid key to access admin features.');
          setShowKeyPrompt(true);
        }
      })
      .finally(() => {
        setAuthReady(true);
      });
  }, [authVersion]);

  const canOwner = allowedRoles.includes('owner');
  const canDeveloper = allowedRoles.includes('developer');
  const roleOptions = useMemo(() => {
    const opts: Role[] = ['merchant'];
    if (canOwner) opts.push('owner');
    if (canDeveloper) opts.push('developer');
    return opts;
  }, [canOwner, canDeveloper]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">ShopSquire</div>
        <div className="brand-sub">Trust-first commerce ops</div>

        <div className="nav-section">Merchant</div>
        <div className="nav">
          {['merchant-bi', 'overview', 'decisions', 'security', 'maestro', 'email-xdr', 'cv-incidents', 'inventory-sync', 'email-incidents', 'escalations', 'playbooks', 'rules', 'approvals', 'procurement', 'market-intel', 'investor', 'orders', 'analytics', 'grafana', 'incidents', 'compliance', 'grc', 'agent-intelligence'].map((key) => {
            const locked = (key === 'compliance' && !canOwner) || (key === 'rules' && !(canOwner || canDeveloper)) || (key === 'grc' && !(canOwner || canDeveloper));
            return (
              <button
                key={key}
                className={`${active === key ? 'active' : ''} ${locked ? 'nav-locked' : ''}`}
                onClick={() => setActive(key)}
              >
                {key[0].toUpperCase() + key.slice(1)} <span>{locked ? 'Locked' : 'Core'}</span>
              </button>
            );
          })}
        </div>

        <>
          <div className="nav-section">Owner</div>
          <div className="nav">
            <button
              className={`${active === 'owner' ? 'active' : ''} ${!canOwner ? 'nav-locked' : ''}`}
              onClick={() => setActive('owner')}
            >
              Owner Console <span>{canOwner ? 'Restricted' : 'Locked'}</span>
            </button>
            <button
              className={`${active === 'sc-sim' ? 'active' : ''} ${!(canOwner || canDeveloper) ? 'nav-locked' : ''}`}
              onClick={() => setActive('sc-sim')}
            >
              Supply Chain Sim <span>{(canOwner || canDeveloper) ? 'Admin' : 'Locked'}</span>
            </button>
          </div>
        </>

        <>
          <div className="nav-section">Developer</div>
          <div className="nav">
            <button
              className={`${active === 'developer' ? 'active' : ''} ${!canDeveloper ? 'nav-locked' : ''}`}
              onClick={() => setActive('developer')}
            >
              Developer Hub <span>{canDeveloper ? 'Restricted' : 'Locked'}</span>
            </button>
            <button
              className={`${active === 'interleaving' ? 'active' : ''} ${!(canDeveloper || canOwner) ? 'nav-locked' : ''}`}
              onClick={() => {
                if (canDeveloper || canOwner) {
                  window.location.href = '/api/v1/admin/interleaving/ui';
                } else {
                  setActive('developer');
                }
              }}
            >
              Interleaving <span>{(canDeveloper || canOwner) ? 'Admin' : 'Locked'}</span>
            </button>
          </div>
        </>
      </aside>

      <main className="content">
        <div className="topbar">
          <div className="search">
            <form onSubmit={handleSearch} style={{ display: 'flex', gap: 4 }}>
              <input
                placeholder="Search decisions, events, users"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Navigate to section"
              />
              <button type="submit" style={{ padding: '0 10px' }}>Go</button>
            </form>
          </div>
          <div className="controls">
            <div className="pill">Env: Sandbox</div>
            <select
              className="role-select"
              value={role}
              disabled={roleOptions.length <= 1}
              onChange={(e) => setRole(e.target.value as Role)}
            >
              {roleOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt[0].toUpperCase() + opt.slice(1)}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={() => setShowKeyPrompt(true)}>API Key</button>
            <div className="avatar">KJ</div>
          </div>
        </div>

        <div className="page-head">
          <h1 className="page-title">
            {active === 'merchant-bi' && 'Merchant BI Dashboard'}
            {active === 'overview' && 'Operational Overview'}
            {active === 'decisions' && 'Decision Control Room'}
            {active === 'security' && 'Security Monitor'}
            {active === 'cv-incidents' && 'CV Incidents'}
            {active === 'inventory-sync' && 'Inventory Sync'}
            {active === 'email-xdr' && 'Email XDR Triage'}
            {active === 'email-incidents' && 'Email Security Incidents'}
            {active === 'rules' && 'Rules Admin'}
            {active === 'playbooks' && 'Playbook Editor'}
            {active === 'approvals' && 'Human Approvals'}
            {active === 'procurement' && 'Procurement Control Room'}
            {active === 'market-intel' && 'Market Intelligence (Synthetic Replay)'}
            {active === 'investor' && 'Investor Metrics'}
            {active === 'grafana' && 'Grafana Observability'}
            {active === 'escalations' && 'Human Escalations Console'}
            {active === 'owner' && 'Owner Console'}
            {active === 'developer' && 'Developer Hub'}
            {active === 'grc' && 'GRC Consultant Console'}
            {active === 'sc-sim' && 'Supply Chain Attack Simulation'}
            {active === 'agent-intelligence' && 'Agent Intelligence'}
            {active === 'maestro' && 'MAESTRO Boundary Registry'}
          </h1>
          <p className="page-sub">
            {active === 'merchant-bi' && 'Custom charts for revenue and security without Grafana.'}
            {active === 'overview' && 'Realtime posture across revenue, autonomy, and policy health.'}
            {active === 'decisions' && 'Audit every recommendation and trace policy enforcement.'}
            {active === 'security' && 'Track threats, risk scores, and response actions.'}
            {active === 'cv-incidents' && 'Review CV evidence bundles and tags; drill down by SKU.'}
            {active === 'inventory-sync' && 'Ingest external inventory snapshots and track sync health.'}
            {active === 'email-xdr' && 'Mini-XDR view for email incidents, playbooks, and escalation actions.'}
            {active === 'email-incidents' && 'Deterministic detections with playbooks, tags, and links.'}
            {active === 'rules' && 'Create, validate, and preview prioritized rules (tenant-scoped).'}
            {active === 'playbooks' && 'Validate, dry-run, publish, rollback, and audit playbook changes.'}
            {active === 'approvals' && 'Review and approve high-stakes proposals.'}
            {active === 'procurement' && 'Auditable buyer→supplier procurement: draft, approve+send (GATE 2), supplier reply, validate, options — every step bitemporally traced.'}
            {active === 'market-intel' && 'Advance a synthetic 7-day market replay through the REAL ingestion→analysis→finding path (isolated demo tenant).'}
            {active === 'investor' && 'One screen: exec KPIs, bounded-autonomy proof, procurement cycle time, capability-gap ledger, governance pulse.'}
            {active === 'orders' && 'Manage order lifecycle for refunds, cancellations, and returns.'}
            {active === 'analytics' && 'Time-series performance across orders, decisions, and security.'}
            {active === 'grafana' && 'Full Grafana observability suite with drill-down dashboards.'}
            {active === 'compliance' && 'Owner-only compliance coverage, evidence, and audit exports.'}
            {active === 'escalations' && 'Human-to-human chat rooms with incident context bundles.'}
            {active === 'owner' && 'Billing, governance, and organization-wide controls.'}
            {active === 'developer' && 'API keys, webhooks, and integration status.'}
            {active === 'grc' && 'Risk register, fingerprint threat monitoring, control mapping, and multi-format reporting.'}
            {active === 'sc-sim' && 'Safe supply-chain attack simulation with parallel agent swarms, real-time SSE streaming, and bitemporal decision trace.'}
            {active === 'agent-intelligence' && 'Citation memory, observation summaries, behavioral models, and agent trust scoring.'}
            {active === 'maestro' && 'CSA Agentic AI Security Framework (Feb 2025) — SC-04B tool-call allowlist per agent with live violation counts.'}
          </p>
          {!canOwner && !canDeveloper && (
            <div className="callout" style={{ marginTop: 8 }}>
              Access level: Merchant only. Set an Owner/Developer key to unlock advanced controls.
            </div>
          )}
        </div>

        {/* Gate ALL panels on auth: they mount + fetch on mount, so rendering them before fetchMe resolves
            (authReady) fired a burst of 401s and drew empty cards; rendering them when auth FAILED (authError)
            fired 401s against an invalid key. One gate here fixes it for every panel — cheaper and safer than
            threading authReady into 23 components (only MarketIntelligence took that per-component route). */}
        {authReady && !authError && (
        <>
        {active === 'merchant-bi' && <MerchantBIPro role={role} />}
        {active === 'overview' && <Overview role={role} />}
        {active === 'decisions' && <Decisions role={role} />}
        {active === 'security' && <Security role={role} />}
        {active === 'email-xdr' && <EmailXdr role={role} />}
        {active === 'cv-incidents' && <CVIncidents role={role} />}
        {active === 'inventory-sync' && <InventorySync role={role} />}
        {active === 'email-incidents' && <EmailIncidents />}
        {active === 'escalations' && <EscalationsConsole role={role} initialIncidentId={incidentIdParam} />}
        {active === 'playbooks' && <Playbooks />}
        {active === 'rules' && <RulesAdmin role={role} />}
        {active === 'approvals' && <Approvals role={role} />}
        {active === 'procurement' && <ProcurementCases />}
        {active === 'market-intel' && <MarketIntelligence authVersion={authVersion} authReady={authReady} />}
        {active === 'investor' && <InvestorMetrics authVersion={authVersion} authReady={authReady} />}
        {active === 'orders' && <Orders role={role} />}
        {active === 'analytics' && <Analytics role={role} />}
        {active === 'grafana' && <GrafanaDashboards role={role} />}
        {active === 'incidents' && <Incidents />}
        {active === 'compliance' && <Compliance role={role} />}
        {active === 'grc' && <GRC role={role} />}
        {active === 'owner' && <OwnerPanel role={canOwner ? role : 'merchant'} />}
        {active === 'developer' && <DeveloperPanel role={canDeveloper ? role : 'merchant'} />}
        {active === 'sc-sim' && <SupplyChainSim role={role} />}
        {active === 'agent-intelligence' && <AgentIntelligence role={role} />}
        {active === 'maestro' && <MaestroRegistry role={role} />}
        </>
        )}

        {!authReady && (
          <div className="callout" style={{ marginTop: 12 }}>
            Authenticating...
          </div>
        )}
        {authError && (
          <div className="callout" style={{ marginTop: 12 }}>
            {authError}
            <div style={{ marginTop: 8 }}>
              <button className="btn secondary" onClick={() => setShowKeyPrompt(true)}>Retry</button>
            </div>
          </div>
        )}
        {showKeyPrompt && (
          <div className="modal-backdrop" onClick={() => setShowKeyPrompt(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <h3>Set API Key</h3>
              <p className="page-sub">Paste a merchant/owner/developer key to unlock role views.</p>
              <input
                className="modal-input"
                placeholder="x-api-key"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
              />
              <div className="modal-actions">
                <button className="btn secondary" onClick={() => setShowKeyPrompt(false)}>Cancel</button>
                <button
                  className="btn"
                  onClick={async () => {
                    if (keyInput.trim()) {
                      const next = keyInput.trim();
                      setClientApiKey(next);
                      try {
                        await setApiKeyCookie(next);
                      } catch {}
                      setAuthReady(false);
                      setAuthError('');
                      setShowKeyPrompt(false);
                      setAuthVersion((v) => v + 1);
                    }
                  }}
                >
                  Save Key
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
