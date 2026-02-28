import React, { useEffect, useMemo, useState } from 'react';
import { fetchAgenticRagSummary, fetchDbStackStatus, fetchExecutivePulse, fetchHitlReviewerConsistency, fetchMemoryHealth, fetchMlGovernanceSummary, fetchOverview, fetchSecurityAttackTimeseries, fetchSecurityGeoAsnTrends, fetchTransactionTimeseries, fetchTrendPackAlarms, fetchUpsellPerformance, runBiQueryAgent, type ExecutivePulse, type MemoryHealthSummary, type SecurityAttackBucket, type SecurityGeoAsnTrend, type TransactionTimeseriesPoint } from '../api';

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

function hashSeed(input: string) {
  let h = 0;
  for (let i = 0; i < input.length; i += 1) {
    h = (h * 31 + input.charCodeAt(i)) % 2147483647;
  }
  return Math.abs(h || 1);
}

function buildDeterministicTransactionDemo(start: string, end: string, granularity: Granularity): { series: TransactionTimeseriesPoint[]; totals: any } {
  const out: TransactionTimeseriesPoint[] = [];
  const seed = hashSeed(`${start}:${end}:${granularity}`);
  const from = new Date(`${start}T00:00:00Z`);
  const to = new Date(`${end}T00:00:00Z`);
  let idx = 0;
  const totals = { orders: 0, revenue: 0, paid: 0, refunded: 0, chargeback: 0, pending_payment: 0, aov: 0 };

  const cursor = new Date(from.getTime());
  while (cursor < to) {
    const bucket = new Date(cursor.getTime());
    let label = isoDate(bucket);
    if (granularity === 'month') {
      label = `${bucket.getUTCFullYear()}-${String(bucket.getUTCMonth() + 1).padStart(2, '0')}-01`;
    }
    const orders = 24 + ((seed + idx * 17) % 43);
    const unitPrice = 720 + ((seed + idx * 29) % 980);
    const gross = Number(((orders * unitPrice) / 100).toFixed(2));
    const paid = Math.max(0, Math.round(orders * 0.86));
    const refunded = Math.max(0, Math.round(orders * 0.08));
    const chargeback = Math.max(0, Math.round(orders * 0.02));
    const pending = Math.max(0, orders - paid - refunded - chargeback);
    out.push({
      bucket: label,
      orders,
      revenue: gross,
      paid,
      refunded,
      chargeback,
      pending_payment: pending,
    });
    totals.orders += orders;
    totals.revenue += gross;
    totals.paid += paid;
    totals.refunded += refunded;
    totals.chargeback += chargeback;
    totals.pending_payment += pending;
    idx += 1;
    if (granularity === 'month') {
      cursor.setUTCMonth(cursor.getUTCMonth() + 1);
      cursor.setUTCDate(1);
    } else {
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
  }

  totals.revenue = Number(totals.revenue.toFixed(2));
  totals.aov = totals.orders > 0 ? Number((totals.revenue / totals.orders).toFixed(2)) : 0;
  return { series: out, totals };
}

function buildDeterministicAttackDemo(hours: number): SecurityAttackBucket[] {
  const days = Math.max(1, Math.min(50, Math.ceil(hours / 24)));
  const now = new Date();
  const types = ['email', 'cv', 'nlp', 'supply_chain', 'endpoint', 'network'];
  const threats: Record<string, string> = {
    email: 'bec',
    cv: 'overlay',
    nlp: 'prompt_injection',
    supply_chain: 'supplier_takeover',
    endpoint: 'lolbin',
    network: 'c2_beacon',
  };
  const vectors: Record<string, string> = {
    email: 'header',
    cv: 'image_overlay',
    nlp: 'instruction',
    supply_chain: 'vendor_account',
    endpoint: 'macro',
    network: 'callback',
  };
  const seed = hashSeed(String(hours));
  const out: SecurityAttackBucket[] = [];
  for (let d = days - 1; d >= 0; d -= 1) {
    const day = addDays(now, -d);
    const hour = `${isoDate(day)}T12:00:00Z`;
    for (let i = 0; i < types.length; i += 1) {
      const t = types[i];
      const count = 2 + ((seed + d * 13 + i * 11) % 16);
      out.push({
        hour,
        security_type: t,
        threat: threats[t] || 'unknown',
        vector: vectors[t] || 'unknown',
        count,
      });
    }
  }
  return out;
}

function buildDeterministicGeoDemo(hours: number): SecurityGeoAsnTrend[] {
  const seed = hashSeed(String(hours));
  const rows = [
    ['AS15169', 'US'],
    ['AS13335', 'US'],
    ['AS4766', 'AU'],
    ['AS16509', 'US'],
    ['AS9009', 'DE'],
    ['AS4837', 'CN'],
  ];
  return rows.map((row, idx) => {
    const count = 8 + ((seed + idx * 7) % 35);
    const geoTrust = idx < 2 ? 'high' : (idx < 4 ? 'medium' : 'low');
    return {
      asn: row[0],
      country: row[1],
      count,
      network_confidence: Number((0.42 + ((seed + idx * 3) % 35) / 100).toFixed(3)),
      network_confidence_avg: Number((0.42 + ((seed + idx * 3) % 35) / 100).toFixed(3)),
      asn_risk_avg: Number((0.2 + ((seed + idx * 5) % 60) / 100).toFixed(3)),
      vpn_or_hosting_hits: Math.max(0, Math.round(count * (idx >= 3 ? 0.45 : 0.2))),
      velocity_anomaly_hits: Math.max(0, Math.round(count * (idx >= 4 ? 0.3 : 0.12))),
      sender_tool_behavior_avg: Number((0.3 + ((seed + idx * 4) % 40) / 100).toFixed(3)),
      ip_churn_velocity: Number((0.08 + ((seed + idx * 6) % 45) / 100).toFixed(3)),
      geo_trust_level: geoTrust as 'low' | 'medium' | 'high',
      last_seen: new Date().toISOString(),
      business_contexts: { storefront: Math.max(1, Math.round(count * 0.6)) },
      security_contexts: { auth_fail: Math.max(1, Math.round(count * 0.35)) },
    };
  });
}

function buildDeterministicOverview() {
  return {
    security_status: 'guarded',
    critical_events_24h: 2,
    autonomy_percent: 71,
    approval_pending: 3,
  };
}

function buildDeterministicUpsell() {
  return {
    ctr: 0.114,
    add_to_cart_rate: 0.061,
    blocked_poisoned_candidates: 2,
    impressions: 1842,
  };
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

function OverlayLineChart({
  title,
  points,
}: {
  title: string;
  points: Array<{ x: string; actual: number; baseline: number; low: number; high: number; anomaly: boolean }>;
}) {
  const w = 660;
  const h = 200;
  const pad = 24;
  const maxY = Math.max(1, ...points.map((p) => Math.max(p.actual, p.high)));
  const innerW = w - pad * 2;
  const innerH = h - pad * 2;
  const xy = (i: number, y: number) => ({
    x: pad + (innerW * (points.length <= 1 ? 0 : i / (points.length - 1))),
    y: pad + innerH * (1 - (y / maxY)),
  });
  const path = (key: 'actual' | 'baseline') =>
    points
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xy(i, Number(p[key] || 0)).x.toFixed(2)} ${xy(i, Number(p[key] || 0)).y.toFixed(2)}`)
      .join(' ');
  const areaTop = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xy(i, Number(p.high || 0)).x.toFixed(2)} ${xy(i, Number(p.high || 0)).y.toFixed(2)}`)
    .join(' ');
  const areaBottom = points
    .map((_p, i) => {
      const rev = points.length - 1 - i;
      return `${i === 0 ? 'L' : 'L'} ${xy(rev, Number(points[rev]?.low || 0)).x.toFixed(2)} ${xy(rev, Number(points[rev]?.low || 0)).y.toFixed(2)}`;
    })
    .join(' ');
  const area = `${areaTop} ${areaBottom} Z`;
  return (
    <div className="card">
      <h3>{title}</h3>
      <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 14, background: '#fff', overflow: 'hidden' }}>
        <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
          <rect x="0" y="0" width={w} height={h} fill="#fff" />
          <path d={area} fill="rgba(42,109,107,0.10)" />
          <path d={path('baseline')} fill="none" stroke="#2a6d6b" strokeWidth="2" strokeDasharray="4 4" />
          <path d={path('actual')} fill="none" stroke="#cc5b2c" strokeWidth="3" />
          {points.map((p, i) =>
            p.anomaly ? <circle key={`${p.x}-${i}`} cx={xy(i, p.actual).x} cy={xy(i, p.actual).y} r="4" fill="#9f2d1b" /> : null
          )}
        </svg>
      </div>
    </div>
  );
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
  const allowSyntheticFallback = ((import.meta as any).env?.VITE_BI_ALLOW_SYNTHETIC_FALLBACK === '1');
  const [granularity, setGranularity] = useState<Granularity>('day');
  const [rangeKey, setRangeKey] = useState<'last30' | 'last90' | 'janfeb'>('janfeb');
  const [tx, setTx] = useState<{ series: TransactionTimeseriesPoint[]; totals: any } | null>(null);
  const [txDemoSeeded, setTxDemoSeeded] = useState(false);
  const [txLoading, setTxLoading] = useState(false);
  const [txError, setTxError] = useState<string | null>(null);

  const [attackBuckets, setAttackBuckets] = useState<SecurityAttackBucket[]>([]);
  const [attackDemoSeeded, setAttackDemoSeeded] = useState(false);
  const [attackLoading, setAttackLoading] = useState(false);
  const [attackError, setAttackError] = useState<string | null>(null);

  const [geo, setGeo] = useState<SecurityGeoAsnTrend[]>([]);
  const [geoDemoSeeded, setGeoDemoSeeded] = useState(false);
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);

  const [overview, setOverview] = useState<any>(null);
  const [upsell, setUpsell] = useState<any>(null);
  const [pulse, setPulse] = useState<ExecutivePulse | null>(null);
  const [alarms, setAlarms] = useState<Array<{ type: string; severity: string; message: string }>>([]);
  const [queryText, setQueryText] = useState('show me refund rate and approval rate');
  const [queryResult, setQueryResult] = useState<any>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [ragSummary, setRagSummary] = useState<any>(null);
  const [dbStack, setDbStack] = useState<any>(null);
  const [mlGovernance, setMlGovernance] = useState<any>(null);
  const [reviewerConsistency, setReviewerConsistency] = useState<any>(null);
  const [memoryHealth, setMemoryHealth] = useState<MemoryHealthSummary | null>(null);
  const [overviewDemoSeeded, setOverviewDemoSeeded] = useState(false);
  const [upsellDemoSeeded, setUpsellDemoSeeded] = useState(false);

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
    setTxDemoSeeded(false);
    fetchTransactionTimeseries({ granularity, start, end })
      .then((r) => {
        if (cancelled) return;
        const series = Array.isArray(r.series) ? r.series : [];
        if (series.length > 0) {
          setTx({ series, totals: r.totals || {} });
          setTxDemoSeeded(false);
          return;
        }
        if (allowSyntheticFallback) {
          setTx(buildDeterministicTransactionDemo(start, end, granularity));
          setTxDemoSeeded(true);
        } else {
          setTx({ series: [], totals: {} });
          setTxError('No transaction data available for selected range.');
        }
      })
      .catch((e: any) => {
        if (cancelled) return;
        setTxError(e.message || 'Failed to load transactions');
        if (allowSyntheticFallback) {
          setTx(buildDeterministicTransactionDemo(start, end, granularity));
          setTxDemoSeeded(true);
        } else {
          setTx({ series: [], totals: {} });
        }
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
      setAttackDemoSeeded(false);
      try {
        const data = await fetchSecurityAttackTimeseries(hours, 8000);
        if (cancelled) return;
        const buckets = Array.isArray(data.buckets) ? data.buckets : [];
        if (buckets.length > 0) {
          setAttackBuckets(buckets);
          setAttackDemoSeeded(false);
          return;
        }
        if (allowSyntheticFallback) {
          setAttackBuckets(buildDeterministicAttackDemo(hours));
          setAttackDemoSeeded(true);
        } else {
          setAttackBuckets([]);
          setAttackError('No security trend data available.');
        }
      } catch (e: any) {
        if (cancelled) return;
        setAttackError(e.message || 'Failed to load security trends');
        if (allowSyntheticFallback) {
          setAttackBuckets(buildDeterministicAttackDemo(hours));
          setAttackDemoSeeded(true);
        } else {
          setAttackBuckets([]);
        }
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
      setGeoDemoSeeded(false);
      try {
        const data = await fetchSecurityGeoAsnTrends(hours, 4000);
        if (cancelled) return;
        const trends = Array.isArray(data.trends) ? data.trends.slice(0, 10) : [];
        if (trends.length > 0) {
          setGeo(trends);
          setGeoDemoSeeded(false);
          return;
        }
        if (allowSyntheticFallback) {
          setGeo(buildDeterministicGeoDemo(hours));
          setGeoDemoSeeded(true);
        } else {
          setGeo([]);
          setGeoError('No geo/ASN trend data available.');
        }
      } catch (e: any) {
        if (cancelled) return;
        setGeoError(e.message || 'Failed to load geo/ASN trends');
        if (allowSyntheticFallback) {
          setGeo(buildDeterministicGeoDemo(hours));
          setGeoDemoSeeded(true);
        } else {
          setGeo([]);
        }
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
    setOverviewDemoSeeded(false);
    setUpsellDemoSeeded(false);
    Promise.allSettled([fetchOverview(), fetchUpsellPerformance(24, 6)])
      .then((res) => {
        if (cancelled) return;
        const ov = res[0];
        const up = res[1];
        if (ov.status === 'fulfilled' && ov.value) {
          setOverview(ov.value);
          setOverviewDemoSeeded(false);
        } else {
          if (allowSyntheticFallback) {
            setOverview(buildDeterministicOverview());
            setOverviewDemoSeeded(true);
          } else {
            setOverview({ security_status: 'unknown', critical_events_24h: 0, autonomy_percent: 0, approval_pending: 0 });
          }
        }
        if (up.status === 'fulfilled' && up.value) {
          setUpsell(up.value);
          setUpsellDemoSeeded(false);
        } else {
          if (allowSyntheticFallback) {
            setUpsell(buildDeterministicUpsell());
            setUpsellDemoSeeded(true);
          } else {
            setUpsell({ ctr: 0, add_to_cart_rate: 0, blocked_poisoned_candidates: 0, impressions: 0 });
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        if (allowSyntheticFallback) {
          setOverview(buildDeterministicOverview());
          setUpsell(buildDeterministicUpsell());
          setOverviewDemoSeeded(true);
          setUpsellDemoSeeded(true);
        } else {
          setOverview({ security_status: 'unknown', critical_events_24h: 0, autonomy_percent: 0, approval_pending: 0 });
          setUpsell({ ctr: 0, add_to_cart_rate: 0, blocked_poisoned_candidates: 0, impressions: 0 });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [allowSyntheticFallback]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([fetchExecutivePulse(start, end), fetchTrendPackAlarms(8)])
      .then((res) => {
        if (cancelled) return;
        const p = res[0];
        const a = res[1];
        if (p.status === 'fulfilled') setPulse(p.value);
        else setPulse(null);
        if (a.status === 'fulfilled') setAlarms(Array.isArray(a.value.alarms) ? a.value.alarms : []);
        else setAlarms([]);
      })
      .catch(() => {
        if (cancelled) return;
        setPulse(null);
        setAlarms([]);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  useEffect(() => {
    let cancelled = false;
    fetchDbStackStatus()
      .then((r) => {
        if (!cancelled) setDbStack(r);
      })
      .catch(() => {
        if (!cancelled) setDbStack(null);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  useEffect(() => {
    let cancelled = false;
    fetchAgenticRagSummary(7)
      .then((r) => {
        if (!cancelled) setRagSummary(r);
      })
      .catch(() => {
        if (!cancelled) setRagSummary(null);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([fetchMlGovernanceSummary(30), fetchHitlReviewerConsistency(30)])
      .then((res) => {
        if (cancelled) return;
        const mg = res[0];
        const rc = res[1];
        setMlGovernance(mg.status === 'fulfilled' ? mg.value : null);
        setReviewerConsistency(rc.status === 'fulfilled' ? rc.value : null);
      })
      .catch(() => {
        if (cancelled) return;
        setMlGovernance(null);
        setReviewerConsistency(null);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  useEffect(() => {
    let cancelled = false;
    fetchMemoryHealth(14)
      .then((r) => {
        if (!cancelled) setMemoryHealth(r);
      })
      .catch(() => {
        if (!cancelled) setMemoryHealth(null);
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

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

  const { secBuckets } = useMemo(() => {
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
    return { secBuckets: keys };
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
      {allowSyntheticFallback && (txDemoSeeded || attackDemoSeeded || geoDemoSeeded || overviewDemoSeeded || upsellDemoSeeded) && (
        <div className="callout" style={{ marginTop: 14 }}>
          Demo-seeded data active for:
          {' '}
          {[
            txDemoSeeded ? 'transactions' : null,
            attackDemoSeeded ? 'security activity' : null,
            geoDemoSeeded ? 'geo/ASN' : null,
            overviewDemoSeeded ? 'overview' : null,
            upsellDemoSeeded ? 'upsell' : null,
          ].filter(Boolean).join(', ')}
          .
        </div>
      )}

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
          {allowSyntheticFallback && (
            <div className="page-sub" style={{ marginTop: 10 }}>
              Note: demo data uses synthetic distributions; in prod this becomes your ground truth.
            </div>
          )}
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

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Memory Health (14d)</h3>
        <div className="page-sub">Conversation-memory reliability from trace telemetry.</div>
        {!memoryHealth && <div className="page-sub" style={{ marginTop: 10 }}>Loading…</div>}
        {!!memoryHealth && (
          <div className="list" style={{ marginTop: 10 }}>
            <div className="list-item"><div>Memory confidence (avg)</div><strong>{Number(memoryHealth.averages?.memory_confidence || 0).toFixed(3)}</strong></div>
            <div className="list-item"><div>Memory misses</div><strong>{Number(memoryHealth.totals?.memory_miss || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Shortlist lock failures</div><strong>{Number(memoryHealth.totals?.shortlist_lock_failed || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Disambiguation prompts</div><strong>{Number(memoryHealth.totals?.disambiguation_prompts || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Summary checkpoints</div><strong>{Number(memoryHealth.totals?.summary_checkpoints || 0).toLocaleString()}</strong></div>
            <div className="list-item"><div>Summary age (avg sec)</div><strong>{Number(memoryHealth.averages?.summary_age_sec || 0).toFixed(1)}</strong></div>
          </div>
        )}
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

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Executive Pulse</h3>
        {!pulse && <div className="page-sub">Loading pulse...</div>}
        {!!pulse && (
          <>
            <div className="grid-4" style={{ marginTop: 10 }}>
              <div className="list-item"><div>Revenue</div><strong>{formatMoney(Number(pulse.kpis.revenue || 0))}</strong></div>
              <div className="list-item"><div>Gross margin %</div><strong>{Number(pulse.kpis.gross_margin_pct || 0).toFixed(2)}%</strong></div>
              <div className="list-item"><div>Refund %</div><strong>{Number(pulse.kpis.refund_pct || 0).toFixed(2)}%</strong></div>
              <div className="list-item"><div>Chargeback %</div><strong>{Number(pulse.kpis.chargeback_pct || 0).toFixed(2)}%</strong></div>
              <div className="list-item"><div>Approval rate</div><strong>{Number(pulse.kpis.approval_rate || 0).toFixed(2)}%</strong></div>
              <div className="list-item"><div>Autonomy %</div><strong>{Number(pulse.kpis.autonomy_pct || 0).toFixed(2)}%</strong></div>
              <div className="list-item"><div>MTTD</div><strong>{Number(pulse.kpis.mttd_minutes || 0).toFixed(2)} min</strong></div>
              <div className="list-item"><div>MTTR</div><strong>{Number(pulse.kpis.mttr_minutes || 0).toFixed(2)} min</strong></div>
            </div>
            {!!alarms.length && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                {alarms.map((a, idx) => (
                  <span key={`${a.type}-${idx}`} className="badge" style={{ background: 'rgba(159,45,27,0.08)', borderColor: 'rgba(159,45,27,0.2)' }}>
                    [{a.severity}] {a.message}
                  </span>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {!!pulse && (
        <>
          <div className="grid-2" style={{ marginTop: 14 }}>
            <OverlayLineChart
              title="Trend Overlay: Revenue vs Baseline"
              points={(pulse.trend_overlays.revenue || []).map((r) => ({
                x: String(r.bucket || ''),
                actual: Number(r.actual || 0),
                baseline: Number(r.baseline || 0),
                low: Number(r.anomaly_low || 0),
                high: Number(r.anomaly_high || 0),
                anomaly: Boolean(r.is_anomaly),
              }))}
            />
            <div className="card">
              <h3>Causal Factor Chips</h3>
              <div className="page-sub">Promo, supplier outage, traffic-drop style tags from incident correlations.</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                {(pulse.trend_overlays.causal_factors || []).length === 0 && <span className="page-sub">No causal factors in range.</span>}
                {(pulse.trend_overlays.causal_factors || []).map((c) => (
                  <span key={c.id} className="badge">{c.id} ({c.count})</span>
                ))}
              </div>
            </div>
          </div>

          <div className="grid-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3>Agentic Ops</h3>
              <div className="page-sub">Auto vs human-reviewed, false-positive drift, per-agent latency/error.</div>
              <table className="table" style={{ marginTop: 10 }}>
                <thead><tr><th>Bucket</th><th>Auto</th><th>Human</th></tr></thead>
                <tbody>
                  {(pulse.agentic_ops.auto_vs_human || []).slice(-8).map((r) => <tr key={r.bucket}><td>{r.bucket}</td><td>{r.auto}</td><td>{r.human}</td></tr>)}
                </tbody>
              </table>
              <div style={{ marginTop: 10 }}>
                {(pulse.agentic_ops.false_positive_drift || []).slice(-8).map((f) => (
                  <span key={f.week} className="badge" style={{ marginRight: 6 }}>{f.week}: {Number(f.fp_rate || 0).toFixed(1)}%</span>
                ))}
              </div>
            </div>

            <div className="card">
              <h3>Security Incursions Matrix</h3>
              <div className="page-sub">Type x severity x week.</div>
              <table className="table" style={{ marginTop: 10 }}>
                <thead><tr><th>Week</th><th>Type</th><th>Severity</th><th>Count</th></tr></thead>
                <tbody>
                  {(pulse.security_incursions_matrix || []).slice(-20).map((m, idx) => (
                    <tr key={`${m.week}-${m.type}-${m.severity}-${idx}`}>
                      <td>{m.week}</td><td>{m.type}</td><td>{m.severity}</td><td>{m.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ marginTop: 14 }}>
            <h3>Decision Replay</h3>
            <div className="page-sub">Policy version changes vs outcome shifts.</div>
            <table className="table" style={{ marginTop: 10 }}>
              <thead><tr><th>Policy</th><th>Decisions</th><th>Approval rate</th></tr></thead>
              <tbody>
                {(pulse.decision_replay || []).map((r) => (
                  <tr key={r.policy_version}><td>{r.policy_version}</td><td>{r.decisions}</td><td>{Number(r.approval_rate || 0).toFixed(2)}%</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="card" style={{ marginTop: 14 }}>
        <h3>NL-to-BI Query Agent</h3>
        <div className="page-sub">Template SQL only, strict schema guardrails.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <input className="modal-input" value={queryText} onChange={(e) => setQueryText(e.target.value)} style={{ flex: 1 }} />
          <button
            className="btn"
            disabled={queryLoading}
            onClick={async () => {
              setQueryLoading(true);
              try {
                const res = await runBiQueryAgent({ query: queryText, start, end, limit: 200 });
                setQueryResult(res);
              } catch (e: any) {
                setQueryResult({ status: 'error', error: e?.message || 'query_failed' });
              } finally {
                setQueryLoading(false);
              }
            }}
          >
            {queryLoading ? 'Running...' : 'Run'}
          </button>
        </div>
        {queryResult && (
          <pre style={{ marginTop: 10, maxHeight: 220, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 10, padding: 10, background: '#fff' }}>
            {JSON.stringify(queryResult, null, 2)}
          </pre>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Agentic RAG Pipeline Signals</h3>
        <div className="page-sub">Plan to Retrieve to Rank to Inject to Decide to Verify to Trace, surfaced from decision trace events.</div>
        {!ragSummary && <div className="page-sub" style={{ marginTop: 10 }}>No recent agentic RAG events.</div>}
        {!!ragSummary && (
          <div className="list" style={{ marginTop: 10 }}>
            <div className="list-item"><div>Injected contexts (7d)</div><strong>{Number(ragSummary.contexts_injected || 0)}</strong></div>
            <div className="list-item"><div>Verify failures (7d)</div><strong>{Number(ragSummary.verify_failures || 0)}</strong></div>
            <div className="list-item"><div>Avg budget utilization</div><strong>{(100 * Number(ragSummary.avg_budget_utilization || 0)).toFixed(1)}%</strong></div>
            <div className="list-item"><div>Event counts</div><strong>{Object.entries((ragSummary.event_counts || {})).map(([k, v]) => `${k}:${v}`).join(' | ') || '-'}</strong></div>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>DB Stack Status</h3>
        <div className="page-sub">Postgres source-of-truth, Timescale, CacheRAG/Redis, and Neo4j pilot readiness.</div>
        {!dbStack && <div className="page-sub" style={{ marginTop: 10 }}>Unavailable.</div>}
        {!!dbStack && (
          <div className="list" style={{ marginTop: 10 }}>
            <div className="list-item"><div>Postgres source of truth</div><strong>{dbStack.postgres_source_of_truth ? 'yes' : 'no'}</strong></div>
            <div className="list-item"><div>Timescale extension</div><strong>{dbStack.timescaledb_extension ? 'yes' : 'no'}</strong></div>
            <div className="list-item"><div>Timescale CAGG orders_hourly</div><strong>{dbStack.timescale_cagg_orders_hourly ? 'yes' : 'no'}</strong></div>
            <div className="list-item"><div>Redis configured</div><strong>{dbStack.redis_configured ? 'yes' : 'no'}</strong></div>
            <div className="list-item"><div>Neo4j fraud pilot enabled</div><strong>{dbStack.neo4j_pilot_enabled ? 'yes' : 'no'}</strong></div>
            <div className="list-item"><div>Security event sinks</div><strong>{Array.isArray(dbStack.security_event_storage_targets) && dbStack.security_event_storage_targets.length ? dbStack.security_event_storage_targets.join(', ') : 'database'}</strong></div>
          </div>
        )}
      </div>

      <div className="grid-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>ML Governance</h3>
          <div className="page-sub">Forecast retrain governance and collaborative-filtering train health.</div>
          {!mlGovernance && <div className="page-sub" style={{ marginTop: 10 }}>Unavailable.</div>}
          {!!mlGovernance && (
            <div className="list" style={{ marginTop: 10 }}>
              <div className="list-item"><div>CF model version</div><strong>{mlGovernance?.cf_training?.last_success_model_version || '-'}</strong></div>
              <div className="list-item"><div>CF last success</div><strong>{mlGovernance?.cf_training?.last_success_at || '-'}</strong></div>
              <div className="list-item"><div>Forecast avg MAPE proxy</div><strong>{mlGovernance?.forecast_governance?.avg_mape_proxy ?? '-'}</strong></div>
              <div className="list-item"><div>Forecast quarantine avg</div><strong>{mlGovernance?.forecast_governance?.avg_quarantined_points ?? '-'}</strong></div>
            </div>
          )}
        </div>

        <div className="card">
          <h3>HITL Reviewer Consistency</h3>
          <div className="page-sub">Reviewer approval/rejection/escalation patterns and turnaround consistency.</div>
          {!reviewerConsistency && <div className="page-sub" style={{ marginTop: 10 }}>Unavailable.</div>}
          {!!reviewerConsistency && (
            <>
              <div className="list" style={{ marginTop: 10 }}>
                <div className="list-item"><div>Total reviews (30d)</div><strong>{reviewerConsistency?.summary?.total_reviews ?? 0}</strong></div>
                <div className="list-item"><div>Median turnaround (min)</div><strong>{reviewerConsistency?.summary?.median_turnaround_minutes ?? 0}</strong></div>
              </div>
              <table className="table" style={{ marginTop: 10 }}>
                <thead><tr><th>Reviewer</th><th>Reviews</th><th>Approval %</th><th>Escalation %</th><th>Band</th></tr></thead>
                <tbody>
                  {(reviewerConsistency?.reviewers || []).slice(0, 8).map((r: any) => (
                    <tr key={r.reviewer_id}>
                      <td>{r.reviewer_id}</td>
                      <td>{r.total_reviews}</td>
                      <td>{Number(r.approval_rate || 0).toFixed(1)}</td>
                      <td>{Number(r.escalation_rate || 0).toFixed(1)}</td>
                      <td>{r.consistency_band || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
