import React, { useEffect, useMemo, useState } from 'react';
import { fetchOverview, fetchSecurityAttackTimeseries, fetchSecurityGeoAsnTrends, fetchTransactionTimeseries, fetchUpsellPerformance, type SecurityAttackBucket, type SecurityGeoAsnTrend, type TransactionTimeseriesPoint } from '../api';

type Props = { role: 'merchant' | 'owner' | 'developer' };

type Granularity = 'day' | 'month';

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

function formatMoney(n: number) {
  const v = Number(n || 0);
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

function addDays(d: Date, days: number) {
  const x = new Date(d.getTime());
  x.setDate(x.getDate() + days);
  return x;
}

function niceBucketLabel(bucket: string | null, granularity: Granularity) {
  if (!bucket) return '-';
  try {
    const dt = new Date(bucket);
    if (granularity === 'month') return dt.toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
    return dt.toLocaleDateString(undefined, { month: 'short', day: '2-digit' });
  } catch {
    return bucket;
  }
}

function seriesMax(points: Array<{ y: number }>) {
  return points.reduce((m, p) => Math.max(m, Number(p.y || 0)), 0);
}

function LineChart({
  title,
  subtitle,
  points,
  height = 170,
  color = '#cc5b2c',
  valueFormat,
}: {
  title: string;
  subtitle?: string;
  points: Array<{ x: string; y: number }>;
  height?: number;
  color?: string;
  valueFormat?: (n: number) => string;
}) {
  const w = 640;
  const h = height;
  const pad = 26;
  const xs = points.map((p) => p.x);
  const maxY = Math.max(1, seriesMax(points));
  const minY = 0;
  const innerW = w - pad * 2;
  const innerH = h - pad * 2;
  const pt = (i: number, y: number) => {
    const x = pad + (innerW * (points.length <= 1 ? 0 : i / (points.length - 1)));
    const ny = (y - minY) / (maxY - minY);
    const yy = pad + innerH * (1 - ny);
    return { x, y: yy };
  };
  const d = points
    .map((p, i) => {
      const { x, y } = pt(i, Number(p.y || 0));
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  const last = points[points.length - 1];
  const lastVal = last ? Number(last.y || 0) : 0;
  const label = valueFormat ? valueFormat(lastVal) : String(lastVal);

  return (
    <div className="card">
      <h3>{title}</h3>
      {subtitle && <div className="page-sub">{subtitle}</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, alignItems: 'baseline' }}>
        <div className="metric">{label}</div>
        <div className="page-sub">{xs.length ? xs[xs.length - 1] : '-'}</div>
      </div>
      <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 14, background: '#fff', overflow: 'hidden' }}>
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
          <rect x="0" y="0" width={w} height={h} fill="#fff" />
          <g opacity="0.55">
            {[0.25, 0.5, 0.75].map((t) => (
              <line key={t} x1={pad} x2={w - pad} y1={pad + innerH * t} y2={pad + innerH * t} stroke="rgba(90,95,106,0.18)" />
            ))}
          </g>
          <path d={d} fill="none" stroke={color} strokeWidth="3" />
          {points.length > 0 && (
            <circle
              cx={pt(points.length - 1, lastVal).x}
              cy={pt(points.length - 1, lastVal).y}
              r="5"
              fill={color}
              stroke="#fff"
              strokeWidth="2"
            />
          )}
        </svg>
      </div>
    </div>
  );
}

function StackedByType({
  title,
  subtitle,
  buckets,
  types,
  colorFor,
  height = 220,
}: {
  title: string;
  subtitle?: string;
  buckets: string[];
  types: string[];
  colorFor: (t: string) => string;
  height?: number;
}) {
  const w = 720;
  const h = height;
  const pad = 24;
  const innerW = w - pad * 2;
  const innerH = h - pad * 2;
  const barW = buckets.length ? innerW / buckets.length : innerW;

  const totalsByBucket = buckets.map((b) => {
    let total = 0;
    for (const t of types) {
      total += (bucketData[b]?.[t] || 0);
    }
    return total;
  });
  const maxTotal = Math.max(1, ...totalsByBucket);

  return (
    <div className="card">
      <h3>{title}</h3>
      {subtitle && <div className="page-sub">{subtitle}</div>}
      <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 14, background: '#fff', overflow: 'hidden' }}>
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
          <rect x="0" y="0" width={w} height={h} fill="#fff" />
          <g opacity="0.55">
            {[0.25, 0.5, 0.75].map((t) => (
              <line key={t} x1={pad} x2={w - pad} y1={pad + innerH * t} y2={pad + innerH * t} stroke="rgba(90,95,106,0.18)" />
            ))}
          </g>
          {buckets.map((b, idx) => {
            const x0 = pad + idx * barW;
            const total = totalsByBucket[idx] || 0;
            const fullH = innerH * (total / maxTotal);
            let y = pad + innerH;
            return (
              <g key={b}>
                {types.map((t) => {
                  const v = bucketData[b]?.[t] || 0;
                  if (!v) return null;
                  const segH = fullH * (v / Math.max(1, total));
                  y -= segH;
                  return (
                    <rect
                      key={`${b}-${t}`}
                      x={x0 + 2}
                      y={y}
                      width={Math.max(2, barW - 4)}
                      height={segH}
                      fill={colorFor(t)}
                      rx="3"
                    />
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
        {types.map((t) => (
          <span key={t} className="badge" style={{ background: 'rgba(42,109,107,0.08)', borderColor: 'rgba(32,33,36,0.12)' }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, background: colorFor(t), marginRight: 6 }} />
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// Bucket storage for stacked security chart; filled by hook below.
const bucketData: Record<string, Record<string, number>> = {};

export function MerchantBIPro({ role }: Props) {
  const [granularity, setGranularity] = useState<Granularity>('day');
  const [rangeKey, setRangeKey] = useState<'last30' | 'last90' | 'janfeb'>('janfeb');
  const [tx, setTx] = useState<{ series: TransactionTimeseriesPoint[]; totals: any } | null>(null);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);

  const [attackBuckets, setAttackBuckets] = useState<SecurityAttackBucket[]>([]);
  const [attackLoading, setAttackLoading] = useState(false);
  const [attackError, setAttackError] = useState<string | null>(null);

  const [geo, setGeo] = useState<SecurityGeoAsnTrend[]>([]);
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);

  const [overview, setOverview] = useState<any>(null);
  const [upsell, setUpsell] = useState<any>(null);

  const { start, end, hours } = useMemo(() => {
    const now = new Date();
    if (rangeKey === 'janfeb') {
      return { start: '2026-01-01', end: '2026-03-01', hours: 24 * 60 };
    }
    if (rangeKey === 'last90') {
      const e = isoDate(addDays(now, 1));
      const s = isoDate(addDays(now, -90));
      return { start: s, end: e, hours: 24 * 90 };
    }
    const e = isoDate(addDays(now, 1));
    const s = isoDate(addDays(now, -30));
    return { start: s, end: e, hours: 24 * 30 };
  }, [rangeKey]);

  useEffect(() => {
    let cancelled = false;
    setTxLoading(true);
    setTxError(null);
    fetchTransactionTimeseries({ granularity, start, end })
      .then((r) => {
        if (cancelled) return;
        setTx({ series: r.series || [], totals: r.totals || {} });
      })
      .catch((e: any) => {
        if (cancelled) return;
        setTxError(e.message || 'Failed to load transactions');
        setTx(null);
      })
      .finally(() => {
        if (!cancelled) setTxLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [granularity, start, end]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setAttackLoading(true);
      setAttackError(null);
      try {
        const data = await fetchSecurityAttackTimeseries(hours, 8000);
        if (cancelled) return;
        setAttackBuckets(Array.isArray(data.buckets) ? data.buckets : []);
      } catch (e: any) {
        if (!cancelled) setAttackError(e.message || 'Failed to load security trends');
      } finally {
        if (!cancelled) setAttackLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [hours]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setGeoLoading(true);
      setGeoError(null);
      try {
        const data = await fetchSecurityGeoAsnTrends(hours, 4000);
        if (cancelled) return;
        setGeo((data.trends || []).slice(0, 10));
      } catch (e: any) {
        if (!cancelled) setGeoError(e.message || 'Failed to load geo/ASN trends');
      } finally {
        if (!cancelled) setGeoLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [hours]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchOverview(), fetchUpsellPerformance(24, 6)])
      .then(([ov, up]) => {
        if (cancelled) return;
        setOverview(ov);
        setUpsell(up);
      })
      .catch(() => {})
      .finally(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const txOrdersPoints = useMemo(() => {
    const series = tx?.series || [];
    return series.map((p) => ({ x: niceBucketLabel(p.bucket, granularity), y: Number(p.orders || 0) }));
  }, [tx, granularity]);
  const txRevenuePoints = useMemo(() => {
    const series = tx?.series || [];
    return series.map((p) => ({ x: niceBucketLabel(p.bucket, granularity), y: Number(p.revenue || 0) }));
  }, [tx, granularity]);

  const secTypes = useMemo(() => {
    const seen = new Set<string>();
    for (const b of attackBuckets || []) {
      if (b.security_type) seen.add(String(b.security_type));
    }
    const core = ['email', 'cv', 'nlp', 'supply_chain', 'endpoint', 'network'];
    const out = [...core.filter((c) => seen.has(c)), ...Array.from(seen).filter((x) => !core.includes(x)).slice(0, 4)];
    return out.length ? out : core;
  }, [attackBuckets]);

  const { secBuckets, secBucketLabel } = useMemo(() => {
    const map: Record<string, Record<string, number>> = {};
    const labelFor = (isoHour: string) => {
      try {
        const dt = new Date(isoHour);
        if (granularity === 'month') {
          return new Date(dt.getFullYear(), dt.getMonth(), 1).toISOString().slice(0, 10);
        }
        return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate()).toISOString().slice(0, 10);
      } catch {
        return isoHour.slice(0, 10);
      }
    };
    for (const b of attackBuckets || []) {
      const key = labelFor(String(b.hour || ''));
      if (!map[key]) map[key] = {};
      const t = String(b.security_type || 'other');
      map[key][t] = (map[key][t] || 0) + Number(b.count || 0);
    }
    for (const k of Object.keys(bucketData)) delete bucketData[k];
    for (const k of Object.keys(map)) bucketData[k] = map[k];
    const keys = Object.keys(map).sort();
    return { secBuckets: keys, secBucketLabel: labelFor };
  }, [attackBuckets, granularity]);

  const colorForType = (t: string) => {
    const palette: Record<string, string> = {
      email: '#2a6d6b',
      cv: '#cc5b2c',
      nlp: '#1f4f8f',
      supply_chain: '#7c3aed',
      endpoint: '#0f766e',
      network: '#b45309',
      other: '#64748b',
    };
    return palette[t] || '#64748b';
  };

  const headline = (
    <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 14 }}>
      <div>
        <h3 style={{ marginBottom: 6 }}>Merchant BI (Custom)</h3>
        <div className="page-sub">Transactions and security posture. Toggle daily vs monthly; focus ranges for Jan-Feb demo or last 30/90 days.</div>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <button className={`btn ${granularity === 'day' ? '' : 'secondary'}`} onClick={() => setGranularity('day')}>Daily</button>
        <button className={`btn ${granularity === 'month' ? '' : 'secondary'}`} onClick={() => setGranularity('month')}>Monthly</button>
        <button className={`btn ${rangeKey === 'janfeb' ? '' : 'secondary'}`} onClick={() => setRangeKey('janfeb')}>Jan-Feb</button>
        <button className={`btn ${rangeKey === 'last30' ? '' : 'secondary'}`} onClick={() => setRangeKey('last30')}>Last 30d</button>
        <button className={`btn ${rangeKey === 'last90' ? '' : 'secondary'}`} onClick={() => setRangeKey('last90')}>Last 90d</button>
      </div>
    </div>
  );

  const kpis = (
    <div className="grid-4" style={{ marginTop: 14 }}>
      <div className="card">
        <h3>Total Revenue</h3>
        <div className="metric">{formatMoney(Number(tx?.totals?.revenue || 0))}</div>
        <div className="page-sub">range {start} → {end}</div>
      </div>
      <div className="card">
        <h3>Orders</h3>
        <div className="metric">{Number(tx?.totals?.orders || 0).toLocaleString()}</div>
        <div className="page-sub">AOV {formatMoney(Number(tx?.totals?.aov || 0))}</div>
      </div>
      <div className="card">
        <h3>Security Posture</h3>
        <div className="metric">{String(overview?.security_status || 'unknown')}</div>
        <div className="page-sub">critical 24h: {Number(overview?.critical_events_24h || 0)}</div>
      </div>
      <div className="card">
        <h3>Autonomy</h3>
        <div className="metric">{Number(overview?.autonomy_percent || 0)}%</div>
        <div className="page-sub">approvals pending: {Number(overview?.approval_pending || 0)}</div>
      </div>
    </div>
  );

  return (
    <div className="stagger">
      {headline}
      {kpis}

      {(txLoading || txError) && (
        <div className="callout" style={{ marginTop: 14 }}>
          {txLoading && 'Loading transactions…'}
          {txError && `Transaction load error: ${txError}`}
        </div>
      )}

      <div className="grid-2" style={{ marginTop: 14 }}>
        <LineChart title="Orders Over Time" subtitle="Counts per bucket" points={txOrdersPoints} valueFormat={(n) => `${Math.round(n).toLocaleString()} orders`} />
        <LineChart title="Revenue Over Time" subtitle="Gross revenue per bucket" points={txRevenuePoints} color="#2a6d6b" valueFormat={(n) => formatMoney(n)} />
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Order Status Mix</h3>
          <div className="page-sub">Paid vs refunded/chargeback/pending for the selected range.</div>
          <div className="list" style={{ marginTop: 10 }}>
            <div className="list-item"><div>Paid</div><strong>{Number(tx?.totals?.paid || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Refunded</div><strong>{Number(tx?.totals?.refunded || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Chargeback</div><strong>{Number(tx?.totals?.chargeback || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Pending payment</div><strong>{Number(tx?.totals?.pending_payment || 0).toLocaleString()}</strong></div>
          </div>
          <div className="page-sub" style={{ marginTop: 10 }}>
            Note: demo data uses synthetic distributions; in prod this becomes your ground truth.
          </div>
        </div>

        <div className="card">
          <h3>Upsell Impact (24h)</h3>
          <div className="page-sub">Checkout add-on suggestions with poison-guard stats.</div>
          {!upsell && <div className="page-sub" style={{ marginTop: 10 }}>Loading…</div>}
          {!!upsell && (
            <div className="list" style={{ marginTop: 10 }}>
              <div className="list-item"><div>CTR</div><strong>{(Number(upsell.ctr || 0) * 100).toFixed(1)}%</strong></div>
              <div className="list-item"><div>Add-to-cart rate</div><strong>{(Number(upsell.add_to_cart_rate || 0) * 100).toFixed(1)}%</strong></div>
              <div className="list-item"><div>Blocked poisoned</div><strong>{Number(upsell.blocked_poisoned_candidates || 0)}</strong></div>
              <div className="list-item"><div>Impressions</div><strong>{Number(upsell.impressions || 0).toLocaleString()}</strong></div>
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 14 }}>
        {(attackLoading || attackError) && (
          <div className="callout">
            {attackLoading && 'Loading security breakdown…'}
            {attackError && `Security breakdown error: ${attackError}`}
          </div>
        )}
        {!attackLoading && !attackError && (
          <StackedByType
            title="Security Activity By Domain"
            subtitle="Stacked volume (email / CV / NLP / supply-chain / endpoint / network)."
            buckets={secBuckets.slice(-clamp(granularity === 'day' ? 45 : 12, 6, 60))}
            types={secTypes}
            colorFor={colorForType}
          />
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Suspicious GeoIP / ASN (Window)</h3>
        <div className="page-sub">Not an XDR replacement; a triage view that correlates with agent traces.</div>
        {geoLoading && <div className="page-sub" style={{ marginTop: 10 }}>Loading…</div>}
        {geoError && <div className="page-sub" style={{ marginTop: 10, color: '#9f2d1b' }}>{geoError}</div>}
        {!geoLoading && !geoError && !geo.length && <div className="page-sub" style={{ marginTop: 10 }}>No data.</div>}
        {!!geo.length && (
          <table className="table" style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>ASN</th>
                <th>Country</th>
                <th>Events</th>
                <th>Geo Trust</th>
                <th>VPN/Hosting hits</th>
                <th>ASN risk avg</th>
              </tr>
            </thead>
            <tbody>
              {geo.slice(0, 10).map((g) => (
                <tr key={`${g.asn}-${g.country}`}>
                  <td>{g.asn}</td>
                  <td>{g.country}</td>
                  <td>{g.count}</td>
                  <td>{g.geo_trust_level}</td>
                  <td>{g.vpn_or_hosting_hits}</td>
                  <td>{Number(g.asn_risk_avg || 0).toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Audit “Receipts” (for SOC2/ISO/GDPR/NIST AI RMF/EU AI Act/PCI)</h3>
        <div className="page-sub">Open JSON bundles that prove what happened, when, and why. Use for auditor walkthroughs.</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <a className="btn secondary" href="/api/v1/admin/compliance/overview?days=30" target="_blank" rel="noreferrer">Compliance overview (30d)</a>
          <a className="btn secondary" href="/api/v1/admin/compliance/evidence?days=30" target="_blank" rel="noreferrer">Evidence bundle (30d)</a>
          <a className="btn secondary" href="/api/v1/admin/grc/risk-register?days=30" target="_blank" rel="noreferrer">Risk register (30d)</a>
          <a className="btn secondary" href="/api/v1/admin/grc/report?days=30" target="_blank" rel="noreferrer">GRC report (30d)</a>
          <a className="btn ghost" href="/api/v1/decisions/query" target="_blank" rel="noreferrer">Decision logs</a>
          <a className="btn ghost" href="/api/v1/admin/security/events?limit=50&offset=0" target="_blank" rel="noreferrer">Security events</a>
        </div>
      </div>
    </div>
  );
}

