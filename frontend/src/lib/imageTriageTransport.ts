import {apiRequestHeaders, apiUrl, safeJson} from './api';

const IMAGE_FAST_TRIAGE_TIMEOUT_MS = 3000;
const IMAGE_DEEP_TRIAGE_TIMEOUT_MS = 30000;

function makeClientFastImageTriage(file: File, artifactId: string) {
    const filenameHint = file.name.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ').trim();
    const suspiciousName = /\b(ssn|qr|password|credential|token|secret|invoice|receipt)\b/i.test(filenameHint);
    return {
      _filename: file.name,
      filename: file.name,
      provider: 'client_fast_boundary',
      labels: filenameHint ? [filenameHint] : [],
      extracted_text: '',
      damage_score: 0,
      intent: 'visual_search',
      intent_routing: {
        intent: 'visual_search',
        confidence: 0.2,
        reason: 'client_safe_hint_before_deep_triage',
      },
      security: {
        clean: false,
        artifact_state: 'pending',
        commercial_authority: 'blocked',
        signals: {
          fast_triage_timeout: true,
          filename_suspicious: suspiciousName,
          analysis_pending: true,
        },
        analysis_stage: 'client_safe_hint',
        verdict: 'Image bytes are queued for background security inspection. The attachment cannot influence recommendations or commercial actions yet.',
      },
      artifact: { artifact_id: artifactId, state: 'pending', authority: 'blocked' },
      analysis_state: { analysis_pending: true, analysis_degraded: false, security_risk: suspiciousName },
    };
}

export async function fetchImageTriages(
    files: File[], fast = false, extractTextEvidence = false, priorResults: any[] = [],
  ) {
    const triagePromises = files.map(async (file, index) => {
      const artifactId = String((file as any).__shopsquireArtifactId || crypto.randomUUID());
      (file as any).__shopsquireArtifactId = artifactId;
      const prior = priorResults[index];
      // The caller supplies the fast result for the same ordered file batch.
      // Preserve its server namespace on transport failure, never for a different file.
      const fallbackArtifactId = prior?._filename === file.name
        && typeof prior?.artifact?.artifact_id === 'string' && prior.artifact.artifact_id.trim()
        ? prior.artifact.artifact_id : artifactId;
      const fd = new FormData();
      fd.append('image', file);
      const triageParams = new URLSearchParams({ artifact_id: artifactId });
      if (fast) triageParams.set('fast', '1');
      if (extractTextEvidence) triageParams.set('extract_text', '1');
      const triagePath = `/api/v1/vision/triage?${triageParams.toString()}`;
      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(),
        fast ? IMAGE_FAST_TRIAGE_TIMEOUT_MS : IMAGE_DEEP_TRIAGE_TIMEOUT_MS);
      try {
        const r = await fetch(apiUrl(triagePath), {
          method: 'POST',
          credentials: 'include',
          body: fd,
          signal: controller.signal,
          headers: {
            ...apiRequestHeaders(),
            'x-skip-observer': '1',
          },
        });
        const data = await safeJson(r);
        if (!r.ok) {
          const detail = data?.detail || {};
          const error = typeof detail === 'string'
            ? detail
            : String(detail?.error || `upload_rejected_${r.status}`);
          const message = typeof detail === 'object' && detail?.message
            ? String(detail.message)
            : 'This attachment was rejected and was not used.';
          return {
            _filename: file.name,
            filename: file.name,
            _upload_error: error,
            _http_status: r.status,
            labels: [],
            extracted_text: '',
            artifact: detail?.artifact || { artifact_id: fallbackArtifactId, state: 'quarantined', authority: 'blocked' },
            analysis_state: { analysis_pending: false, analysis_degraded: false, security_risk: true },
            security: {
              clean: false,
              artifact_state: 'quarantined',
              commercial_authority: 'blocked',
              verdict: message,
              reupload_needed: true,
              signals: { upload_rejected: true, upload_error: error },
            },
          };
        }
        if (!data) {
          return {
            _filename: file.name,
            filename: file.name,
            _upload_error: 'invalid_triage_response',
            labels: [],
            artifact: { artifact_id: fallbackArtifactId, state: 'degraded', authority: 'blocked' },
            analysis_state: { analysis_degraded: true, security_risk: false },
            security: {
              clean: false,
              artifact_state: 'degraded',
              commercial_authority: 'blocked',
              verdict: 'Inspection did not return a valid result. The attachment was not used.',
              signals: { analysis_degraded: true, invalid_triage_response: true },
            },
          };
        }
        data._filename = file.name;
        return data;
      } catch {
        if (fast) return makeClientFastImageTriage(file, artifactId);
        return {
          _filename: file.name,
          filename: file.name,
          _upload_error: 'triage_unavailable',
          labels: [],
          artifact: { artifact_id: fallbackArtifactId, state: 'degraded', authority: 'blocked' },
          analysis_state: { analysis_degraded: true, security_risk: false },
          security: {
            clean: false,
            artifact_state: 'degraded',
            commercial_authority: 'blocked',
            verdict: 'Image inspection is unavailable. The attachment was not used.',
            signals: { analysis_degraded: true, triage_unavailable: true },
          },
        };
      } finally {
        if (timeoutId != null) window.clearTimeout(timeoutId);
      }
    });
    return (await Promise.all(triagePromises)).filter(Boolean);
}
