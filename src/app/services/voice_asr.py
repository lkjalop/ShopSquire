from __future__ import annotations

import base64
import binascii
import os
from typing import Optional, Dict

import httpx

from src.app.security.provider_boundary import require_provider_transfer


class ASRAdapter:
    """Base ASR adapter interface."""

    name: str = "base"

    def transcribe_chunk(
        self, audio_bytes: bytes, lang_hint: Optional[str] = None,
        format_hint: str = "webm",
    ) -> Dict:
        """Transcribe a single audio chunk.

        Returns {"text": str, "confidence": float}
        """
        raise NotImplementedError


class WhisperLocalASRAdapter(ASRAdapter):
    """Bounded Whisper-compatible ASR adapter."""

    name: str = "whisper-local"

    def __init__(self) -> None:
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")
        try:
            configured = float(os.getenv("VOICE_PROVIDER_TIMEOUT_SECONDS", "12") or 12)
        except Exception:
            configured = 12.0
        self.timeout_seconds = min(15.0, max(1.0, configured))

    def _transcribe_openai(
        self, audio_bytes: bytes, lang_hint: Optional[str] = None,
        format_hint: str = "webm",
    ) -> Dict:
        if not (self.openai_api_key and audio_bytes):
            return {
                "text": "", "confidence": 0.0, "provider": "none",
                "status": "unavailable",
            }
        require_provider_transfer("openai", data_categories=["voice_audio"])
        media = {
            "wav": ("wav", "audio/wav"),
            "mp3": ("mp3", "audio/mpeg"),
            "mpeg": ("mpeg", "audio/mpeg"),
            "ogg": ("ogg", "audio/ogg"),
            "webm": ("webm", "audio/webm"),
        }.get(str(format_hint or "").lower(), ("webm", "audio/webm"))
        files = {"file": (f"audio.{media[0]}", audio_bytes, media[1])}
        data = {"model": self.openai_model}
        if lang_hint:
            data["language"] = str(lang_hint)[:16]
        headers = {"authorization": f"Bearer {self.openai_api_key}"}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(
                    f"{self.openai_base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
                if resp.status_code >= 300:
                    return {
                        "text": "", "confidence": 0.0, "provider": "openai",
                        "status": "error",
                    }
                payload = resp.json() if resp.content else {}
            text = str((payload or {}).get("text") or "").strip()
            if not text:
                return {
                    "text": "", "confidence": 0.0, "provider": "openai",
                    "status": "silence",
                }
            return {
                "text": text, "confidence": 0.92, "provider": "openai",
                "status": "ready",
            }
        except Exception:
            return {
                "text": "", "confidence": 0.0, "provider": "openai",
                "status": "error",
            }

    def transcribe_chunk(
        self, audio_bytes: bytes, lang_hint: Optional[str] = None,
        format_hint: str = "webm",
    ) -> Dict:
        if not audio_bytes or len(audio_bytes) < 32:
            return {
                "text": "", "confidence": 0.0, "provider": "local-boundary",
                "status": "silence",
            }
        cloud = self._transcribe_openai(
            audio_bytes, lang_hint=lang_hint, format_hint=format_hint,
        )
        if cloud.get("text"):
            return cloud
        # Never fabricate a transcript. The browser transcript remains
        # authoritative when the optional correction provider is unavailable.
        return cloud


def decode_base64_audio(b64: str, *, max_bytes: Optional[int] = None) -> bytes:
    if not b64:
        return b""
    if "," in b64 and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    compact = "".join(str(b64).split())
    if max_bytes is not None and len(compact) > ((int(max_bytes) + 2) // 3) * 4 + 8:
        raise OverflowError("audio_too_large")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid_audio") from exc
    if max_bytes is not None and len(decoded) > int(max_bytes):
        raise OverflowError("audio_too_large")
    return decoded
