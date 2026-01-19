from typing import Dict
from fastapi import APIRouter, HTTPException

from src.app.config import load_feature_flags, get_settings

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.post("/asr")
def asr_stub(audio_base64: str) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("asr"):
        raise HTTPException(status_code=503, detail="ASR disabled")
    # Stubbed transcription
    return {"transcript": "stub transcript"}


@router.post("/tts")
def tts_stub(text: str) -> Dict:
    flags = load_feature_flags(get_settings().feature_flags_path)
    cap = flags.get("CAPABILITIES", {}).get("voice", {"asr": False, "tts": False})
    if not cap.get("tts"):
        raise HTTPException(status_code=503, detail="TTS disabled")
    # Stubbed audio response
    return {"audio_base64": "U1RCRkFLRUFVSU8="}
