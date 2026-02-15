import { useEffect, useState } from 'react';
import { apiUrl, safeJson, cvAnalyze, cvIssueNonce, cvUpload } from '../lib/api';
import CVResultsPanel, { CVResult } from './CVResultsPanel';
import { fileToBase64, buildSanitizedImages } from '../utils/imageProcessing';
import CameraButton from './CameraButton';

type FAQItem = {
  id: string;
  intent: string;
  title: string;
  description: string;
  troubleshooting_steps: string[];
  evidence_requirements: string[];
  auto_approve_threshold_cents?: number;
};

type ImageConsistencyItem = {
  index: number;
  filename?: string;
  status?: 'match' | 'mismatch' | 'needs_better_image' | 'suspicious' | string;
  reasons?: string[];
  detected?: string[];
};

type ImageConsistencyResult = {
  status?: 'match' | 'mismatch' | 'needs_better_image' | string;
  mismatch_count?: number;
  suspicious_count?: number;
  needs_better_count?: number;
  prior_mismatch_count?: number;
  repeat_mismatch?: boolean;
  images?: ImageConsistencyItem[];
  prompt?: string | null;
};

type UIActions = {
  chat_with_admin?: boolean;
};

export type CVSubmitResult = {
  decision_id?: string;
  trace_id?: string;
  case_id?: string;
  analysis?: any;
  cv_tiered_analysis?: any;
  suggested_routing?: string;
  human_review?: { status: string; ticket_id?: string | null } | boolean;
  evidence_tags?: string[];
  playbook_preview?: any;
  image_consistency?: ImageConsistencyResult;
  order_validation?: { provided?: boolean; exists?: boolean | null; triggered_security?: boolean } | null;
  user_prompt?: string | null;
  ui_actions?: UIActions;
};

export default function RightPanelExtras({
  mode,
  onEscalate,
  onTraceId,
  initialImages,
  onResult,
}: {
  mode: 'faq' | 'cv';
  onEscalate?: (payload: any) => void;
  onTraceId?: (traceId: string | null) => void;
  initialImages?: File[];
  onResult?: (result: CVResult | null) => void;
}) {
  const [faq, setFaq] = useState<FAQItem[]>([]);
  const [images, setImages] = useState<File[]>([]);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [orderId, setOrderId] = useState('');
  const [issueType, setIssueType] = useState('refund');
  const [description, setDescription] = useState('');
  const [playbookOverride, setPlaybookOverride] = useState('');
  const [cvPlaybooks, setCvPlaybooks] = useState<any[]>([]);
  const [forceTier2, setForceTier2] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<CVSubmitResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const role = (localStorage.getItem('role') || '').toLowerCase();
  const isAdmin = role === 'admin' || role === 'merchant_admin' || role === 'security_admin';
  const showAdvancedCvControls = isAdmin && (
    ((import.meta as any).env?.VITE_CV_ADVANCED_UI === '1')
    || (localStorage.getItem('cv_debug_ui') === '1')
  );

  useEffect(() => {
    if (mode === 'faq') {
      fetch('/ui/faq_kb.json')
        .then(r => r.json())
        .then(setFaq)
        .catch(() => setFaq([]));
    }
  }, [mode]);

  useEffect(() => {
    if (mode !== 'cv' || !showAdvancedCvControls) return;
    fetch(apiUrl('/api/v1/security/playbooks/cv'), {
      headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
    })
      .then(r => safeJson(r))
      .then((data) => {
        if (data && Array.isArray(data.playbooks)) setCvPlaybooks(data.playbooks);
      })
      .catch(() => setCvPlaybooks([]));
  }, [mode, showAdvancedCvControls]);

  useEffect(() => {
    const urls = images.map(img => URL.createObjectURL(img));
    setImageUrls(urls);
    return () => urls.forEach(u => URL.revokeObjectURL(u));
  }, [images]);

  useEffect(() => {
    if (initialImages && initialImages.length > 0) {
      setImages(initialImages);
    }
  }, [initialImages]);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    setImages(files);
  };

  const imageStatusByIndex = new Map<number, ImageConsistencyItem>(
    ((result?.image_consistency?.images || []) as ImageConsistencyItem[]).map((item: ImageConsistencyItem) => [item.index, item]),
  );
  const showChatWithAdmin = Boolean(
    result?.ui_actions?.chat_with_admin
    || result?.suggested_routing === 'security_review'
    || (typeof result?.human_review !== 'boolean' && result?.human_review?.status === 'pending')
    || Boolean((result as any)?.qr_prompt_injection)
    || (result?.evidence_tags || []).some((t: string) =>
      ['qr_url_present', 'prompt_injection_text_suspected', 'manipulation_detected', 'qr_url_suspicious', 'ocr_prompt_injection', 'fraud_score_high'].includes(t),
    ),
  );

  const statusMeta = (rawStatus?: string) => {
    const status = (rawStatus || 'pending').toLowerCase();
    if (status === 'match') return { label: 'match', bg: '#e8f5e9', fg: '#1b5e20' };
    if (status === 'needs_better_image') return { label: 'needs better image', bg: '#fff8e1', fg: '#8a6100' };
    if (status === 'mismatch') return { label: 'mismatch', bg: '#ffebee', fg: '#8b0000' };
    if (status === 'suspicious') return { label: 'suspicious', bg: '#fce4ec', fg: '#880e4f' };
    if (status === 'not_analyzed') return { label: 'not analyzed', bg: '#eef2ff', fg: '#3730a3' };
    return { label: 'pending', bg: '#f3f4f6', fg: '#374151' };
  };

  const remediationHint = (reason?: string) => {
    const r = (reason || '').toLowerCase();
    if (r.includes('unrelated_object_detected')) return 'Upload only product photos tied to this return.';
    if (r.includes('no_laptop_signal_detected')) return 'Capture the full laptop body/keyboard and damaged area.';
    if (r.includes('low_visual_evidence')) return 'Retake in bright light, close focus, and steady framing.';
    if (r.includes('invalid_or_unsupported_image')) return 'Use JPG/PNG/WebP under size limits and re-upload.';
    if (r.includes('ocr_prompt_pattern_detected')) return 'Remove overlays, text stickers, or encoded instructions.';
    if (r.includes('ocr_unrelated_overlay_detected')) return 'Avoid stock photos or images with overlay text/stickers; upload a real photo of the item.';
    if (r.includes('qr_external_url_detected')) return 'Remove QR codes/external links; upload a clean photo of the item and damage (no codes or overlays).';
    if (r.includes('qr_code_detected')) return 'Upload a new photo without any QR codes or overlays.';
    if (r.includes('order_id_not_visible_or_mismatch')) return 'Add receipt/invoice photo showing the same order ID.';
    return 'Provide a clearer product-focused image for verification.';
  };

  const submitCV = async () => {
    setSubmitting(true);
    setError(null);
    setResult(null);
    onResult?.(null);
    try {
      let traceId: string | null = null;
      try {
        const imageB64s = images.length > 0 ? await Promise.all(images.map(fileToBase64)) : [];
        const orchResp = await fetch(apiUrl('/api/v1/orchestrate'), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key',
          },
          body: JSON.stringify({
            uid: localStorage.getItem('uid') || 'demo-user',
            cart_total_cents: 0,
            query: description || 'Customer complaint/return request',
            complaint_intent: true,
            images: imageB64s,
          }),
        });
        if (orchResp.ok) {
          const orchJson = await safeJson(orchResp);
          if (!orchJson) {
            throw new Error('orchestrate_empty_response');
          }
          traceId = orchJson.decision_trace_id || orchJson.trace_id || null;
          onTraceId?.(traceId);
        }
      } catch {
        // Orchestrator is best-effort; continue with CV submit.
      }

      const fd = new FormData();
      fd.append('order_id', orderId);
      fd.append('issue_type', issueType);
      fd.append('description', description);
      if (showAdvancedCvControls && playbookOverride) fd.append('playbook_override', playbookOverride);
      if (showAdvancedCvControls && forceTier2) fd.append('force_tier2', 'true');
      images.forEach((f) => fd.append('images', f));
      const r = await fetch(apiUrl('/api/v1/support/complaints/submit'), {
        method: 'POST',
        body: fd,
        headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
      });
      const j = await safeJson(r);
      if (!r.ok || !j) {
        throw new Error((j && j.detail) ? j.detail : `submit_failed (${r.status})`);
      }
      const resolvedTraceId = traceId || j.decision_trace_id || j.trace_id || j.decision_id || j.case_id || null;
      onTraceId?.(resolvedTraceId);
      setResult({
        decision_id: j.decision_id,
        trace_id: resolvedTraceId || undefined,
        case_id: j.case_id,
        analysis: j.analysis,
        cv_tiered_analysis: j.cv_tiered_analysis,
        suggested_routing: j.suggested_routing,
        human_review: j.human_review,
        evidence_tags: j.evidence_tags,
        playbook_preview: j.playbook_preview,
        image_consistency: j.image_consistency,
        order_validation: j.order_validation,
        user_prompt: j.user_prompt,
        ui_actions: j.ui_actions,
      });
      onResult?.({
        decision_id: j.decision_id,
        case_id: j.case_id,
        suggested_routing: j.suggested_routing,
        analysis: j.analysis,
        cv_tiered_analysis: j.cv_tiered_analysis,
        human_review: j.human_review,
        evidence_tags: j.evidence_tags,
        playbook_preview: j.playbook_preview,
        image_consistency: j.image_consistency,
        order_validation: j.order_validation,
        user_prompt: j.user_prompt,
        ui_actions: j.ui_actions,
      });
    } catch (e: any) {
      setError(e?.message || 'Submit failed');
    } finally {
      setSubmitting(false);
    }
  };

  const analyzeSafely = async () => {
    setSubmitting(true);
    setError(null);
    setResult(null);
    onResult?.(null);
    try {
      const sanitized = await buildSanitizedImages(images);
      const imageB64s = images.length > 0 ? await Promise.all(images.map(fileToBase64)) : [];
      const resp = await cvAnalyze({
        images: sanitized,
        images_b64: imageB64s,
        order_id: orderId,
        description,
        issue_type: issueType,
      });
      const resolvedTraceId = (resp as any)?.trace_id || resp.case_id || null;
      const ic = (resp as any)?.image_consistency || null;
      const cvRes: CVSubmitResult = {
        decision_id: undefined,
        trace_id: resolvedTraceId || undefined,
        case_id: resp.case_id,
        analysis: resp.cv_analysis,
        cv_tiered_analysis: undefined,
        suggested_routing: (resp as any)?.suggested_routing || undefined,
        human_review: false,
        evidence_tags: [],
        playbook_preview: undefined,
        image_consistency: ic || {
          status: 'not_analyzed',
          mismatch_count: 0,
          suspicious_count: 0,
          needs_better_count: 0,
          repeat_mismatch: false,
          images: imageUrls.map((_, idx) => ({ index: idx, status: 'not_analyzed', reasons: [] })),
          prompt: null,
        },
        order_validation: null,
        user_prompt: ic?.prompt || null,
        ui_actions: (resp as any)?.ui_actions || { chat_with_admin: false },
      };
      onTraceId?.(resolvedTraceId);
      setResult(cvRes);
      onResult?.({
        decision_id: cvRes.decision_id,
        case_id: cvRes.case_id,
        suggested_routing: cvRes.suggested_routing,
        analysis: cvRes.analysis,
        cv_tiered_analysis: cvRes.cv_tiered_analysis,
        human_review: cvRes.human_review,
        evidence_tags: cvRes.evidence_tags,
        playbook_preview: cvRes.playbook_preview,
        image_consistency: cvRes.image_consistency,
        order_validation: cvRes.order_validation,
        user_prompt: cvRes.user_prompt,
        ui_actions: cvRes.ui_actions,
        qr_prompt_injection: (resp as any)?.qr_prompt_injection,
      });
    } catch (e: any) {
      setError(e?.message || 'Analyze failed');
    } finally {
      setSubmitting(false);
    }
  };

  const agree = () => {
    // If auto_process suggested, fetch return label
    if (result?.case_id) {
      fetch(apiUrl(`/api/v1/support/complaints/${encodeURIComponent(result.case_id)}/return-label`), {
        headers: { 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
      }).then(() => {}).catch(() => {});
    }
  };

  const disagree = () => {
    // Open support conversation stub
    fetch(apiUrl('/api/v1/support/answer'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': localStorage.getItem('x-api-key') || 'local-merchant-key' },
      body: JSON.stringify({ question: `Disagree with verdict. Case=${result?.case_id}` }),
    }).then(() => {}).catch(() => {});
  };

  const escalate = async () => {
    try {
      const resp = await fetch(apiUrl('/api/v1/incidents/escalate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          case_id: result?.case_id,
          trace_id: result?.trace_id,
          reason: 'buyer_requested_human_review',
          context: { decision_id: result?.decision_id, evidence_tags: result?.evidence_tags },
        }),
      });
      const data = await safeJson(resp);
      if (data?.ok && data?.incident_id) {
        onEscalate?.({
          case_id: result?.case_id,
          decision_id: result?.decision_id,
          incident_id: data.incident_id,
          buyer_token: data.buyer_token,
        });
        return;
      }
    } catch {
      // Fallback: open escalation room with case_id as incident proxy
    }
    onEscalate?.({ case_id: result?.case_id, decision_id: result?.decision_id });
  };

  const uploadWithNonce = async () => {
    setSubmitting(true);
    setError(null);
    try {
      if (!images || images.length === 0) throw new Error('no_images_selected');
      const nonceRes = await cvIssueNonce();
      if (!nonceRes?.nonce) throw new Error('nonce_issue_failed');
      const first = images[0];
      const up = await cvUpload({
        file: first,
        nonce: nonceRes.nonce,
        order_id: orderId || undefined,
        issue_type: issueType || undefined,
        description: description || undefined,
      });
      const resolvedTraceId = (up as any)?.case_id || (up as any)?.trace_id || null;
      onTraceId?.(resolvedTraceId);
      const actions = (up as any)?.next_actions || [];
      setResult({
        decision_id: (up as any)?.case_id,
        trace_id: resolvedTraceId || undefined,
        case_id: (up as any)?.case_id,
        analysis: (up as any)?.cv_tier2 || (up as any)?.cv_analysis,
        cv_tiered_analysis: (up as any)?.cv_tier2 ? { tier2: (up as any)?.cv_tier2 } : undefined,
        suggested_routing: actions.includes('human_review') ? 'security_review' : 'standard_queue',
        human_review: actions.includes('human_review') ? { status: 'pending', ticket_id: null } : false,
        evidence_tags: (up as any)?.evidence_tags || [],
        playbook_preview: undefined,
        image_consistency: undefined,
        order_validation: null,
        user_prompt: null,
        ui_actions: { chat_with_admin: actions.includes('human_review') },
      });
      onResult?.({
        decision_id: (up as any)?.case_id,
        case_id: (up as any)?.case_id,
        suggested_routing: actions.includes('human_review') ? 'security_review' : 'standard_queue',
        analysis: (up as any)?.cv_tier2 || (up as any)?.cv_analysis,
        cv_tiered_analysis: (up as any)?.cv_tier2 ? { tier2: (up as any)?.cv_tier2 } : undefined,
        human_review: actions.includes('human_review') ? { status: 'pending', ticket_id: null } : false,
        evidence_tags: (up as any)?.evidence_tags || [],
        playbook_preview: undefined,
        image_consistency: undefined,
        order_validation: null,
        user_prompt: null,
        ui_actions: { chat_with_admin: actions.includes('human_review') },
      });
    } catch (e: any) {
      setError(e?.message || 'Upload via nonce failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (mode === 'faq') {
    return (
      <div style={{ padding: 12 }}>
        <h3 style={{ margin: '8px 0' }}>FAQ & Troubleshooting</h3>
        {faq.length === 0 && <div>Loading FAQs...</div>}
        {faq.map(item => (
          <div key={item.id} style={{ marginBottom: 12, borderBottom: '1px solid #eee', paddingBottom: 12 }}>
            <div style={{ fontWeight: 600 }}>{item.title}</div>
            <div style={{ color: '#555', margin: '4px 0 8px' }}>{item.description}</div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Steps:</div>
              <ul style={{ paddingLeft: 18 }}>
                {item.troubleshooting_steps.map((s, i) => <li key={i} style={{ fontSize: 13 }}>{s}</li>)}
              </ul>
            </div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              Evidence: {item.evidence_requirements.join(', ')}
            </div>
          </div>
        ))}
      </div>
    );
  }

  // CV mode UI
  return (
    <div style={{ padding: 12 }}>
      <h3 style={{ margin: '8px 0' }}>Upload Photos (CV Triage)</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <input type="text" placeholder="Order ID" value={orderId} onChange={e => setOrderId(e.target.value)} style={{ flex: 1 }} />
        <select value={issueType} onChange={e => setIssueType(e.target.value)}>
          <option value="refund">Refund</option>
          <option value="return">Return</option>
          <option value="warranty">Warranty</option>
        </select>
      </div>
      {showAdvancedCvControls && (
        <>
          <div style={{ marginBottom: 8 }}>
            <select value={playbookOverride} onChange={e => setPlaybookOverride(e.target.value)} style={{ width: '100%' }}>
              <option value="">Playbook override (auto)</option>
              {cvPlaybooks.map((pb) => (
                <option key={pb.id} value={pb.id}>{pb.id} - {pb.title}</option>
              ))}
            </select>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 6 }}>
            <input
              type="checkbox"
              checked={forceTier2}
              onChange={(e) => setForceTier2(e.target.checked)}
            />
            Force Tier 2 (demo)
          </label>
        </>
      )}
      <textarea placeholder="Describe the issue" value={description} onChange={e => setDescription(e.target.value)} rows={3} style={{ width: '100%', marginBottom: 8 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <CameraButton
          onFiles={(fs) => setImages(fs)}
          title="Take photo or choose from library"
        />
        <span style={{ fontSize: 12, color: '#6b7280' }}>Capture or select multiple photos</span>
      </div>
      {imageUrls.length > 0 && (
        <div style={{ marginTop: 10, border: '1px solid #d6e0ec', borderRadius: 8, padding: 8, background: '#f7fafc' }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Evidence Rail</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 260, overflowY: 'auto', paddingRight: 4 }}>
            {imageUrls.map((u, i) => {
              const hasIc = Boolean(result?.image_consistency && Array.isArray((result as any).image_consistency?.images));
              const evidence = hasIc ? imageStatusByIndex.get(i) : undefined;
              const badge = statusMeta(hasIc ? evidence?.status : 'not_analyzed');
              const reason = hasIc
                ? (evidence?.reasons && evidence.reasons.length > 0 ? evidence.reasons[0] : 'awaiting verification')
                : 'not analyzed yet';
              const hint = hasIc ? remediationHint(reason) : 'Click Analyze or Submit to validate these photos.';
              return (
                <div
                  key={i}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '72px 1fr',
                    gap: 8,
                    alignItems: 'center',
                    border: '1px solid #e5e7eb',
                    borderRadius: 8,
                    padding: 6,
                    background: '#fafafa',
                  }}
                >
                  <img
                    src={u}
                    alt={`upload-${i + 1}`}
                    style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #ddd' }}
                  />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                      <div style={{ fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {images[i]?.name || `upload_${i + 1}.jpg`}
                      </div>
                      <span
                        style={{
                          fontSize: 11,
                          padding: '2px 7px',
                          borderRadius: 999,
                          background: badge.bg,
                          color: badge.fg,
                          fontWeight: 700,
                          textTransform: 'uppercase',
                        }}
                      >
                        {badge.label}
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: '#4b5563', marginTop: 4 }}>
                      {hasIc ? `Why flagged: ${reason.replaceAll('_', ' ')}` : `Status: ${reason}`}
                    </div>
                    <div style={{ fontSize: 11, color: '#065f46', marginTop: 2 }}>
                      How to fix: {hint}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <button onClick={submitCV} disabled={submitting}>{submitting ? 'Submitting...' : 'Submit (upload)'}</button>
        <button onClick={uploadWithNonce} disabled={submitting}>{submitting ? 'Uploading...' : 'Upload (nonce)'}</button>
        <button onClick={analyzeSafely} disabled={submitting}>{submitting ? 'Analyzing...' : 'Analyze (no upload)'}</button>
        {result && (
          <>
            <button onClick={agree}>Agree</button>
            <button onClick={disagree}>Disagree</button>
            {showChatWithAdmin && <button onClick={escalate}>Chat with Admin</button>}
          </>
        )}
      </div>
      {error && <div style={{ color: 'crimson', marginTop: 8 }}>{error}</div>}
      {result && (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          <div><strong>Verdict:</strong> {result.suggested_routing || '-'}</div>
          <div><strong>Decision:</strong> {result.decision_id || '-'}</div>
          <div><strong>Case:</strong> {result.case_id || '-'}</div>
          {result.user_prompt && (
            <div style={{ marginTop: 8, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e', borderRadius: 8, padding: '8px 10px' }}>
              <strong>Verify photos:</strong> {result.user_prompt}
            </div>
          )}
          {result.image_consistency && (
            <div style={{ marginTop: 8, background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 10px' }}>
              <div><strong>Mismatch attempts:</strong> {(result.image_consistency.prior_mismatch_count || 0) + ((result.image_consistency.mismatch_count || 0) > 0 ? 1 : 0)}</div>
              <div><strong>Escalation rule:</strong> Escalate on 2nd mismatch</div>
              {result.image_consistency.repeat_mismatch && (
                <div style={{ color: '#991b1b', marginTop: 4 }}>
                  Repeated mismatch detected. Escalated for security/human verification.
                </div>
              )}
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            <strong>Next Steps:</strong> {result.human_review && typeof result.human_review !== 'boolean' ? result.human_review.status : '-'}
          </div>
        </div>
      )}
      {result && <CVResultsPanel result={result} />}
    </div>
  );
}
