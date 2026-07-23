"""Voice input/output adapters for the canonical typed chat path."""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket

from src.app.contracts.voice import (
    VoiceASRRequest,
    VoiceASRResponse,
    VoiceTTSRequest,
    VoiceTTSResponse,
)
from src.app.feature_flags import get_flags as _ff_get_flags
from src.app.security.auth import (
    ROLE_DEVELOPER,
    ROLE_MERCHANT,
    ROLE_OWNER,
    require_role,
)
from src.app.services.decision_log import log_trace_event
from src.app.services.voice_asr import WhisperLocalASRAdapter, decode_base64_audio
from src.app.services.voice_tts import ElevenLabsTTSAdapter

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])
_VOICE_ROLES = [ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]


def _max_audio_bytes() -> int:
    try:
        configured = int(os.getenv("VOICE_MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))
    except Exception:
        configured = 5 * 1024 * 1024
    return min(10 * 1024 * 1024, max(32, configured))


def _tenant(value: Optional[str]) -> str:
    tenant = str(value or "default").strip()
    if not tenant or len(tenant) > 128:
        raise HTTPException(status_code=400, detail="invalid_tenant")
    return tenant


@router.post("/asr", response_model=VoiceASRResponse)
def asr(
    request: VoiceASRRequest,
    role: str = Depends(require_role(_VOICE_ROLES)),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
) -> VoiceASRResponse:
    """Transcribe bounded audio. The resulting text still enters through /chat/stream."""
    flags = _ff_get_flags()
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("asr"):
        raise HTTPException(status_code=503, detail="ASR disabled")
    tenant_id = _tenant(x_tenant_id)
    try:
        audio = decode_base64_audio(request.audio_b64, max_bytes=_max_audio_bytes())
    except OverflowError:
        raise HTTPException(status_code=413, detail="audio_too_large")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_audio")

    started = time.monotonic()
    adapter = WhisperLocalASRAdapter()
    out = adapter.transcribe_chunk(
        audio, lang_hint=request.language, format_hint=request.format,
    )
    latency_ms = round((time.monotonic() - started) * 1000.0, 1)
    try:
        log_trace_event(
            trace_id=None,
            event_type="voice_asr",
            source_type="connector",
            source_id=str(out.get("provider") or adapter.name),
            target_type="stage",
            target_id="chat_input",
            payload={
                "tenant_id": tenant_id,
                "role": role,
                "audio_bytes": len(audio),
                "format": request.format,
                "status": str(out.get("status") or "unavailable"),
                "confidence": float(out.get("confidence") or 0.0),
                "latency_ms": latency_ms,
            },
        )
    except Exception:
        # Telemetry cannot make a read-only adapter unavailable.
        pass
    return VoiceASRResponse(
        transcript=str(out.get("text") or "")[:4000],
        confidence=float(out.get("confidence") or 0.0),
        provider=str(out.get("provider") or adapter.name),
        status=str(out.get("status") or ("ready" if out.get("text") else "unavailable")),
        latency_ms=latency_ms,
    )


@router.post("/tts", response_model=VoiceTTSResponse)
def tts(
    request: VoiceTTSRequest,
    role: str = Depends(require_role(_VOICE_ROLES)),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
) -> VoiceTTSResponse:
    """Synthesize optional playback without fabricating audio when providers are absent."""
    flags = _ff_get_flags()
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("tts"):
        raise HTTPException(status_code=503, detail="TTS disabled")
    _tenant(x_tenant_id)
    started = time.monotonic()
    adapter = ElevenLabsTTSAdapter()
    out = adapter.synthesize(request.text, voice=request.voice)
    return VoiceTTSResponse(
        audio_base64=str(out.get("audio_base64") or ""),
        confidence=float(out.get("confidence") or 0.0),
        provider=str(out.get("provider") or "none"),
        mime_type=out.get("mime_type"),
        status=str(out.get("status") or ("ready" if out.get("audio_base64") else "unavailable")),
        latency_ms=round((time.monotonic() - started) * 1000.0, 1),
    )


@router.websocket("/stream")
async def voice_stream(ws: WebSocket) -> None:
    """Retired compatibility route.

    Pilot voice uses ASR as an adapter and submits the transcript through
    /chat/stream, preserving single-flight, typed-facade and action gates.
    """
    await ws.accept()
    await ws.send_json({
        "type": "error",
        "detail": "legacy_voice_stream_disabled_use_chat_stream",
    })
    await ws.close(code=1008)
