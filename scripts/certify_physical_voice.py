"""Capture a short physical microphone sample and exercise hosted ASR/TTS adapters.

Raw microphone bytes are hashed for evidence and deleted after the provider check.
No transcript or audio payload is retained in the certification artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import wave

import numpy as np
import sounddevice as sd

REPO_ROOT = str(Path(__file__).resolve().parents[1])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.app.services.voice_asr import WhisperCloudASRAdapter  # noqa: E402
from src.app.services.voice_tts import ElevenLabsTTSAdapter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--output", default="tmp/physical_voice_certification.json")
    args = parser.parse_args()
    duration = min(5.0, max(1.0, args.seconds))
    devices = sd.query_devices()
    default_input = sd.default.device[0]
    input_device = sd.query_devices(default_input, "input")
    capture_started = time.perf_counter()
    frames = sd.rec(
        int(duration * args.sample_rate),
        samplerate=args.sample_rate,
        channels=1,
        dtype="int16",
        device=default_input,
    )
    sd.wait()
    capture_ms = int((time.perf_counter() - capture_started) * 1000)
    samples = np.asarray(frames, dtype=np.int16).reshape(-1)
    peak = int(np.max(np.abs(samples.astype(np.int32)))) if samples.size else 0
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))) if samples.size else 0.0

    temp_path: Path | None = None
    audio_bytes = b""
    try:
        with tempfile.NamedTemporaryFile(prefix="shopsquire-mic-", suffix=".wav", delete=False) as handle:
            temp_path = Path(handle.name)
        with wave.open(str(temp_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(args.sample_rate)
            wav.writeframes(samples.tobytes())
        audio_bytes = temp_path.read_bytes()
        asr = WhisperCloudASRAdapter().transcribe_chunk(audio_bytes, lang_hint="en", format_hint="wav")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    tts = ElevenLabsTTSAdapter().synthesize(
        "ShopSquire physical voice certification response.", voice="alloy"
    )
    asr_summary = {
        "provider": asr.get("provider"),
        "status": asr.get("status"),
        "transcript_present": bool(asr.get("text")),
        "transcript_retained": False,
    }
    tts_summary = {
        "provider": tts.get("provider"),
        "status": tts.get("status"),
        "audio_present": bool(tts.get("audio_base64")),
        "audio_retained": False,
        "mime_type": tts.get("mime_type"),
    }
    capture_passed = bool(samples.size and peak > 0 and rms > 0)
    hosted_passed = asr.get("status") == "ready" and tts.get("status") == "ready"
    artifact = {
        "schema_version": "physical-voice-cert-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "input_device": {
            "index": int(default_input),
            "name": str(input_device.get("name") or ""),
            "hostapi": int(input_device.get("hostapi") or 0),
            "max_input_channels": int(input_device.get("max_input_channels") or 0),
        },
        "available_device_count": len(devices),
        "capture": {
            "duration_seconds": duration,
            "sample_rate": args.sample_rate,
            "capture_ms": capture_ms,
            "wav_bytes": len(audio_bytes),
            "sha256": hashlib.sha256(audio_bytes).hexdigest(),
            "peak_int16": peak,
            "rms": round(rms, 3),
            "raw_audio_retained": False,
            "passed": capture_passed,
        },
        "hosted_asr": asr_summary,
        "hosted_tts": tts_summary,
        "physical_microphone_passed": capture_passed,
        "hosted_asr_tts_passed": hosted_passed,
        "passed": capture_passed and hosted_passed,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "physical_microphone_passed": capture_passed,
        "hosted_asr_status": asr_summary["status"],
        "hosted_tts_status": tts_summary["status"],
        "hosted_asr_tts_passed": hosted_passed,
        "raw_audio_retained": False,
        "output": str(output),
    }, indent=2))
    return 0 if artifact["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
