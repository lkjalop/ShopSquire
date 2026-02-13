from __future__ import annotations

import base64
import os
from typing import Dict

import httpx


class TTSAdapter:
    """Base TTS adapter interface."""

    name: str = "base"

    def synthesize(self, text: str, voice: str | None = None) -> Dict:
        """Synthesize text to audio.

        Returns {"audio_base64": str, "confidence": float}
        """
        raise NotImplementedError


class ElevenLabsTTSAdapter(TTSAdapter):
    """TTS adapter with ElevenLabs/OpenAI support and deterministic fallback."""

    name: str = "tts"

    def __init__(self) -> None:
        self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self.elevenlabs_base_url = os.getenv("ELEVENLABS_API_BASE_URL", "https://api.elevenlabs.io/v1").rstrip("/")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

    def _to_b64(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii") if data else ""

    def _synthesize_elevenlabs(self, text: str) -> Dict:
        if not (self.elevenlabs_api_key and text):
            return {"audio_base64": "", "confidence": 0.0}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{self.elevenlabs_base_url}/text-to-speech/{self.elevenlabs_voice_id}",
                    headers={
                        "xi-api-key": self.elevenlabs_api_key,
                        "accept": "audio/mpeg",
                        "content-type": "application/json",
                    },
                    json={
                        "text": text[:800],
                        "model_id": "eleven_multilingual_v2",
                        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
                    },
                )
            if resp.status_code >= 300:
                return {"audio_base64": "", "confidence": 0.0}
            return {"audio_base64": self._to_b64(resp.content), "confidence": 0.9}
        except Exception:
            return {"audio_base64": "", "confidence": 0.0}

    def _synthesize_openai(self, text: str, voice: str | None = None) -> Dict:
        if not (self.openai_api_key and text):
            return {"audio_base64": "", "confidence": 0.0}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"{self.openai_base_url}/audio/speech",
                    headers={
                        "authorization": f"Bearer {self.openai_api_key}",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.openai_model,
                        "voice": (voice or "alloy"),
                        "input": text[:1000],
                        "format": "mp3",
                    },
                )
            if resp.status_code >= 300:
                return {"audio_base64": "", "confidence": 0.0}
            return {"audio_base64": self._to_b64(resp.content), "confidence": 0.88}
        except Exception:
            return {"audio_base64": "", "confidence": 0.0}

    def synthesize(self, text: str, voice: str | None = None) -> Dict:
        if not text:
            return {"audio_base64": "", "confidence": 0.0}
        out = self._synthesize_elevenlabs(text)
        if out.get("audio_base64"):
            return out
        out = self._synthesize_openai(text, voice=voice)
        if out.get("audio_base64"):
            return out
        # Deterministic fallback payload for local environments without provider keys.
        payload = f"LOCAL_TTS:{(voice or 'default')}:{text[:32]}".encode("utf-8")
        return {"audio_base64": base64.b64encode(payload).decode("ascii"), "confidence": 0.6}


# Backward compatibility import alias.
ElevenLabsStubTTS = ElevenLabsTTSAdapter
