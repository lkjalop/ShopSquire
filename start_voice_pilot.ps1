# Start the normal demo with voice capabilities enabled only for the pilot.
# Hosted ASR/TTS still fail closed when provider credentials or transfer policy
# are absent; browser speech recognition remains the STT-only fallback.
$env:FEATURE_FLAGS_PATH = "config/feature_flags.voice-pilot.json"
$env:VOICE_PROVIDER_TIMEOUT_SECONDS = "12"
$env:VOICE_MAX_AUDIO_BYTES = "5242880"
# Cold start is governed by the readiness-gated router prewarm (main.py
# _prewarm_router_models) + the per-provider OCR probe; there is no separate
# voice cold-ceiling knob (the old VOICE_COLD_CEILING_SECONDS was never read).
$env:RECOMMEND_SUPPORT_HANDOFF_MODE = "on"
$env:RECOMMEND_INVENTORY_READ_MODE = "on"
$env:RECOMMEND_LEGACY_DELEGATE_ENABLED = "0"

& "$PSScriptRoot\start_demo.ps1"
