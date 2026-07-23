# Start the normal demo with voice capabilities enabled only for the pilot.
# Hosted ASR/TTS still fail closed when provider credentials or transfer policy
# are absent; browser speech recognition remains the STT-only fallback.
$env:FEATURE_FLAGS_PATH = "config/feature_flags.voice-pilot.json"
$env:VOICE_PROVIDER_TIMEOUT_SECONDS = "12"
$env:VOICE_MAX_AUDIO_BYTES = "5242880"
$env:VOICE_COLD_CEILING_SECONDS = "20"

& "$PSScriptRoot\start_demo.ps1"
