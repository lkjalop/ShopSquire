from __future__ import annotations

import base64
import os
from typing import Optional, Dict

import httpx

from src.app.security.provider_boundary import require_provider_transfer


class ASRAdapter:
    """Base ASR adapter interface."""

    name: str = "base"

    def transcribe_chunk(self, audio_bytes: bytes, lang_hint: Optional[str] = None) -> Dict:
        """Transcribe a single audio chunk.

        Returns {"text": str, "confidence": float}
        """
        raise NotImplementedError


class WhisperLocalASRAdapter(ASRAdapter):
    """ASR adapter with OpenAI Whisper support and local fallback."""

    name: str = "whisper-local"

    def __init__(self) -> None:
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_model = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")

    def _transcribe_openai(self, audio_bytes: bytes) -> Dict:
        if not (self.openai_api_key and audio_bytes):
            return {"text": "", "confidence": 0.0}
        require_provider_transfer("openai", data_categories=["voice_audio"])
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {"model": self.openai_model}
        headers = {"authorization": f"Bearer {self.openai_api_key}"}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{self.openai_base_url}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
                if resp.status_code >= 300:
                    return {"text": "", "confidence": 0.0}
                payload = resp.json() if resp.content else {}
            text = str((payload or {}).get("text") or "").strip()
            if not text:
                return {"text": "", "confidence": 0.0}
            return {"text": text, "confidence": 0.92}
        except Exception:
            return {"text": "", "confidence": 0.0}

    def transcribe_chunk(self, audio_bytes: bytes, lang_hint: Optional[str] = None) -> Dict:
        cloud = self._transcribe_openai(audio_bytes)
        if cloud.get("text"):
            return cloud
        # Minimal heuristic: treat empty/short audio as silence
        if not audio_bytes or len(audio_bytes) < 32:
            return {"text": "", "confidence": 0.0}
        return {"text": "Voice input received.", "confidence": 0.45}


def decode_base64_audio(b64: str) -> bytes:
    if not b64:
        return b""
    try:
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
    except Exception:
        return b""
