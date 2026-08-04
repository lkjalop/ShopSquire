"""Bounded voice-adapter contracts.

Voice is an input/output adapter around the typed chat path. These contracts do
not carry tenant identity or action authority; both come from authenticated
request context and the recommendation facade.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


VoiceStatus = Literal["ready", "silence", "unavailable", "error"]


class VoiceASRRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    audio_b64: str = Field(
        min_length=4,
        validation_alias=AliasChoices("audio_b64", "audio_base64"),
    )
    format: Literal["webm", "wav", "mp3", "mpeg", "ogg"] = "webm"
    language: Optional[str] = Field(default=None, min_length=2, max_length=16)


class VoiceASRResponse(BaseModel):
    transcript: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provider: str = "none"
    status: VoiceStatus = "unavailable"
    latency_ms: float = Field(default=0.0, ge=0.0)


class VoiceTTSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    voice: Optional[str] = Field(default=None, max_length=80)


class VoiceTTSResponse(BaseModel):
    audio_base64: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provider: str = "none"
    mime_type: Optional[str] = None
    status: VoiceStatus = "unavailable"
    latency_ms: float = Field(default=0.0, ge=0.0)
