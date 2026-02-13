from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
import json
import uuid
import time

from src.app.config import load_feature_flags, get_settings
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.voice_asr import WhisperLocalASRAdapter, decode_base64_audio
from src.app.services.voice_tts import ElevenLabsTTSAdapter
from src.app.services.voice_session import VoiceSessionManager
from src.app.services.memory import Memory
from src.app.security.firewall import TransactionFirewall
from src.app.services.orchestrator import Orchestrator
from src.app.services.decision_log import log_trace_event
try:
    # For voice→escalation handoff, reuse the room append helper
    from src.app.routers.escalation_room import _append_chat as _append_escalation_chat
except Exception:
    _append_escalation_chat = None

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.post("/asr")
def asr(audio_base64: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("asr"):
        raise HTTPException(status_code=503, detail="ASR disabled")
    audio = decode_base64_audio(audio_base64)
    asr = WhisperLocalASRAdapter()
    out = asr.transcribe_chunk(audio)
    return {"transcript": out.get("text") or "", "confidence": out.get("confidence") or 0.0}


@router.post("/tts")
def tts(text: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("tts"):
        raise HTTPException(status_code=503, detail="TTS disabled")
    tts = ElevenLabsTTSAdapter()
    out = tts.synthesize(text)
    return {"audio_base64": out.get("audio_base64") or "", "confidence": out.get("confidence") or 0.0}


@router.websocket("/stream")
async def voice_stream(ws: WebSocket):
    """Bi-directional voice stream (ASR + orchestrator + TTS).

    Client protocol (JSON frames):
      - {"type":"init", "session_id":"...", "tenant_id":"..."}
      - {"type":"audio", "data":"<base64>"}
      - {"type":"commit"}  # triggers orchestration + TTS

    Server frames:
      - {"type":"transcript", "text":"...", "confidence":0.7}
      - {"type":"response", "trace_id":"...", "proposal":{...}}
      - {"type":"audio", "audio_base64":"..."}
    """
    await ws.accept()
    # Feature flags gate
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not (cap.get("asr") and cap.get("tts")):
        await ws.send_text(json.dumps({"type": "error", "detail": "voice_disabled"}))
        await ws.close(code=1003)
        return

    # Prepare adapters and session state
    asr = WhisperLocalASRAdapter()
    tts = ElevenLabsTTSAdapter()
    mem = Memory()
    firewall = TransactionFirewall()
    orch = Orchestrator(memory=mem, firewall=firewall, flags=get_settings().feature_flags)
    vsm = VoiceSessionManager(redis_client=getattr(mem, "redis", None), ttl_seconds=900)
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    transcript_accum: str = ""

    try:
        while True:
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                # binary frame fallback
                try:
                    data_bytes = await ws.receive_bytes()
                    raw = data_bytes.decode("utf-8", errors="ignore")
                except Exception:
                    await ws.send_text(json.dumps({"type": "error", "detail": "invalid_frame"}))
                    continue
            try:
                msg = json.loads(raw)
            except Exception:
                await ws.send_text(json.dumps({"type": "error", "detail": "invalid_json"}))
                continue

            mtype = msg.get("type")
            if mtype == "init":
                session_id = msg.get("session_id") or str(uuid.uuid4())
                tenant_id = msg.get("tenant_id")
                await ws.send_text(json.dumps({"type": "init_ack", "session_id": session_id}))
                continue

            if mtype == "audio":
                audio_b64 = msg.get("data") or ""
                blob = decode_base64_audio(audio_b64)
                tr = asr.transcribe_chunk(blob)
                transcript_accum = vsm.append_transcript(session_id or "default", tr.get("text") or "").get("transcript")
                await ws.send_text(json.dumps({"type": "transcript", "text": tr.get("text"), "confidence": tr.get("confidence")}))
                continue

            if mtype == "commit":
                # Build payload and run orchestrator
                trace_id = str(uuid.uuid4())
                payload = {
                    "query": transcript_accum,
                    "tenant_id": tenant_id,
                    "multi_turn": True,
                    "trace_id": trace_id,
                }
                t0 = time.time()
                result = orch.run(uid=session_id or "anonymous", payload=payload, simulate_only=False, use_rules=False)
                dt_ms = int((time.time() - t0) * 1000.0)
                try:
                    log_trace_event(
                        trace_id=trace_id,
                        event_type="voice_commit",
                        source_type="voice",
                        source_id="voice_stream",
                        target_type=None,
                        target_id=None,
                        payload={"latency_ms": dt_ms, "session_id": session_id, "tenant_id": tenant_id},
                    )
                except Exception:
                    pass
                await ws.send_text(json.dumps({"type": "response", "trace_id": trace_id, "proposal": result.proposal, "timings": result.timings}))
                # If policy requires approval or proposal flags human review, hand off to escalation room
                try:
                    needs_review = False
                    try:
                        pg = result.firewall.get("policy_gate") if isinstance(result.firewall, dict) else None
                        needs_review = bool(result.firewall.get("approval_required")) or (isinstance(pg, dict) and pg.get("verdict") == "escalate")
                    except Exception:
                        needs_review = bool(result.firewall.get("approval_required")) if isinstance(result.firewall, dict) else False
                    try:
                        if isinstance(result.proposal, dict) and result.proposal.get("needs_human_review"):
                            needs_review = True
                    except Exception:
                        pass
                    if needs_review and _append_escalation_chat is not None:
                        incident_id = None
                        try:
                            tickets = result.proposal.get("tickets") if isinstance(result.proposal, dict) else None
                            if isinstance(tickets, list) and tickets:
                                incident_id = str(tickets[0].get("id")) if isinstance(tickets[0], dict) else None
                        except Exception:
                            incident_id = None
                        # Fallback to trace_id when ticket not yet created
                        incident_id = incident_id or trace_id
                        summary_msg = "Voice session escalated: manual review required"
                        meta = {
                            "trace_id": trace_id,
                            "session_id": session_id,
                            "tenant_id": tenant_id,
                            "reason": (result.firewall.get("policy_gate", {}).get("reason") if isinstance(result.firewall, dict) else None),
                            "evidence_tags": (result.proposal.get("evidence_tags") if isinstance(result.proposal, dict) else None),
                        }
                        try:
                            _append_escalation_chat(incident_id, role="assistant", message=summary_msg, meta=meta)
                        except Exception:
                            pass
                        # Notify client to optionally join the room
                        try:
                            await ws.send_text(json.dumps({"type": "escalation", "incident_id": incident_id, "trace_id": trace_id}))
                        except Exception:
                            pass
                except Exception:
                    pass
                # Synthesize TTS for the top response line or summary
                text = (result.proposal.get("reason") or "Here is the recommendation.") if isinstance(result.proposal, dict) else "Response ready."
                audio = tts.synthesize(text)
                await ws.send_text(json.dumps({"type": "audio", "audio_base64": audio.get("audio_base64"), "confidence": audio.get("confidence")}))
                continue

            # Unknown message type
            await ws.send_text(json.dumps({"type": "error", "detail": "unknown_type"}))
    finally:
        try:
            await ws.close()
        except Exception:
            pass
