import styles from './CVResultsPanel.module.css';

export type CVResult = {
  case_id?: string;
  decision_id?: string;
  suggested_routing?: string;
  analysis?: any;
  cv_tiered_analysis?: any;
  human_review?: { status?: string; ticket_id?: string | null } | boolean;
  evidence_tags?: string[];
  playbook_preview?: any;
  image_consistency?: {
    status?: string;
    mismatch_count?: number;
    suspicious_count?: number;
    needs_better_count?: number;
  };
  order_validation?: { provided?: boolean; exists?: boolean | null; triggered_security?: boolean } | null;
  user_prompt?: string | null;
  ui_actions?: { chat_with_admin?: boolean };
};

export default function CVResultsPanel({
  result,
  onClose,
}: {
  result: CVResult | null;
  onClose?: () => void;
}) {
  if (!result) return null;
  const analysis = result.analysis || {};
  const playbook = result.playbook_preview?.playbook;
  const triggeredBy = result.playbook_preview?.triggered_by || result.evidence_tags || [];
  const tier2 = result.cv_tiered_analysis?.tier2 || {};
  const tier2Summary = result.cv_tiered_analysis?.tier2_summary || tier2?.summary || {};
  const detectorSummary = tier2?.detector?.summary || {};
  const qualityScores = tier2?.quality?.scores || {};
  const role = (localStorage.getItem('role') || '').toLowerCase();
  const isAdmin = role === 'admin' || role === 'merchant_admin' || role === 'security_admin';
  const showInternalCvDetails = isAdmin && (
    ((import.meta as any).env?.VITE_CV_ADVANCED_UI === '1')
    || (localStorage.getItem('cv_debug_ui') === '1')
  );
  const topQuality = Object.entries(qualityScores)
    .sort((a: any, b: any) => b[1] - a[1])
    .slice(0, 3);

  const orderValidationLabel = result.order_validation?.provided
    ? result.order_validation?.exists === true
      ? 'verified'
      : result.order_validation?.exists === false
        ? 'not_found'
    : 'unknown'
    : 'not_provided';
  const confidence = typeof analysis.confidence === 'number' ? analysis.confidence : null;
  const confidenceBand = confidence === null
    ? '-'
    : confidence >= 0.85
      ? 'high'
      : confidence >= 0.6
        ? 'medium'
        : 'low';
  const safeSummary = [
    { label: 'Issue Type', value: analysis.damage_type || '-' },
    { label: 'Component', value: analysis.component || '-' },
    { label: 'Severity', value: analysis.severity || '-' },
    { label: 'Needs Human Review', value: analysis.needs_human_review === true ? 'yes' : 'no' },
    { label: 'Serial Detected', value: analysis.serial_number ? 'yes' : 'no' },
  ];

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <div className={styles.title}>CV Triage Result</div>
        {onClose && <button className={styles.closeBtn} onClick={onClose}>Close</button>}
      </div>
      <div className={styles.grid}>
        <div><span>Verdict</span><strong>{result.suggested_routing || '-'}</strong></div>
        <div><span>Case</span><strong>{result.case_id || '-'}</strong></div>
        <div><span>Decision</span><strong>{result.decision_id || '-'}</strong></div>
        <div><span>Confidence</span><strong>{analysis.confidence ?? '-'}</strong></div>
        <div><span>Severity</span><strong>{analysis.severity ?? '-'}</strong></div>
        <div><span>Damage</span><strong>{analysis.damage_type ?? analysis.component ?? '-'}</strong></div>
        <div><span>Image Consistency</span><strong>{result.image_consistency?.status ?? '-'}</strong></div>
        <div><span>Order Validation</span><strong>{orderValidationLabel}</strong></div>
      </div>
      {analysis && (
        <div className={styles.details}>
          <div className={styles.subTitle}>Assessment Summary</div>
          <div className={styles.grid}>
            <div><span>Confidence Band</span><strong>{confidenceBand}</strong></div>
            <div><span>Confidence Score</span><strong>{confidence === null ? '-' : confidence.toFixed(2)}</strong></div>
            {safeSummary.map((item) => (
              <div key={item.label}><span>{item.label}</span><strong>{String(item.value)}</strong></div>
            ))}
          </div>
        </div>
      )}
      {result.cv_tiered_analysis && (
        <div className={styles.details}>
          <div className={styles.subTitle}>Tier 2 Summary</div>
          <div className={styles.grid}>
            <div><span>Model Pack</span><strong>{tier2Summary.model_pack || tier2?.model_pack || '-'}</strong></div>
            <div><span>OCR</span><strong>{tier2?.ocr?.provider || '-'}</strong></div>
            <div><span>Detections</span><strong>{(detectorSummary.unique || []).join(', ') || '-'}</strong></div>
            <div><span>Manipulation</span><strong>{tier2?.forensics?.manipulation_score ?? '-'}</strong></div>
          </div>
          {topQuality.length > 0 && (
            <>
              <div className={styles.subTitle} style={{ marginTop: 8 }}>Quality Scores</div>
              <div className={styles.tags}>
                {topQuality.map(([label, score]) => (
                  <span key={label} className={styles.tag}>{label}: {Number(score).toFixed(2)}</span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {showInternalCvDetails && (triggeredBy?.length || playbook) && (
        <div className={styles.playbook}>
          <div className={styles.subTitle}>Playbook Preview</div>
          {triggeredBy?.length ? (
            <div className={styles.tags}>
              {triggeredBy.map((tag: string) => (
                <span key={tag} className={styles.tag}>{tag}</span>
              ))}
            </div>
          ) : (
            <div className={styles.empty}>No evidence tags detected.</div>
          )}
          {playbook ? (
            <div className={styles.playbookBody}>
              <div><strong>{playbook.title || playbook.id}</strong></div>
              {playbook.id && <div className={styles.meta}>ID: {playbook.id}</div>}
              {playbook.risk_band_min && <div className={styles.meta}>Min Risk Band: {playbook.risk_band_min}</div>}
              {playbook.checks?.length ? (
                <div className={styles.list}>
                  <div className={styles.listTitle}>Checks</div>
                  <ul>
                    {playbook.checks.map((c: string, i: number) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              ) : null}
              {playbook.actions?.length ? (
                <div className={styles.list}>
                  <div className={styles.listTitle}>Actions</div>
                  <ul>
                    {playbook.actions.map((a: string, i: number) => <li key={i}>{a}</li>)}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : (
            <div className={styles.empty}>No playbook selected.</div>
          )}
        </div>
      )}
    </div>
  );
}
