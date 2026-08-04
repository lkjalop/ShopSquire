import { useRef, useState, useCallback, useEffect } from 'react';

interface DualSTTResult {
  /** Current best transcript (browser or Whisper, whichever arrived last) */
  transcript: string;
  /** Whether the mic is actively recording */
  isRecording: boolean;
  /** Source of current transcript, or null before voice is used */
  source: 'browser' | 'whisper' | null;
  /** Whisper confidence score (0-1) if available */
  whisperConfidence: number | null;
  /** Whether Whisper is still processing */
  whisperPending: boolean;
  /** Whether a correction was applied (Whisper replaced browser transcript) */
  corrected: boolean;
  /** Start recording */
  start: () => void;
  /** Stop recording */
  stop: () => void;
  /** Toggle recording */
  toggle: () => void;
  /** Error message if any */
  error: string | null;
}

interface UseDualSTTOptions {
  /** API base URL for Whisper ASR endpoint */
  apiUrl?: string;
  /** API key header value */
  apiKey?: string;
  /** Language hint for Whisper (auto-detect if not set) */
  language?: string;
  /** Authenticated tenant context; never accepted from transcript content */
  tenantId?: string;
  /** Hard recording bound for pilot push-to-talk */
  maxDurationMs?: number;
  /** Callback when final transcript is ready */
  onFinalTranscript?: (text: string, source: 'browser' | 'whisper') => void;
}

/**
 * Dual-path speech-to-text hook: runs browser SpeechRecognition for instant
 * interim transcripts AND streams audio to Whisper backend for high-accuracy
 * correction. Browser transcript appears instantly; Whisper replaces it if different.
 */
export function useDualSTT(options: UseDualSTTOptions = {}): DualSTTResult {
  const {
    apiUrl = '', apiKey = '', language, tenantId = 'default',
    maxDurationMs = 30_000, onFinalTranscript,
  } = options;

  const [transcript, setTranscript] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [source, setSource] = useState<'browser' | 'whisper' | null>(null);
  const [whisperConfidence, setWhisperConfidence] = useState<number | null>(null);
  const [whisperPending, setWhisperPending] = useState(false);
  const [corrected, setCorrected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const browserTranscriptRef = useRef('');
  const onFinalRef = useRef(onFinalTranscript);
  const recordingTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    onFinalRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  const sendToWhisper = useCallback(async (audioBlob: Blob) => {
    setWhisperPending(true);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12_000);
    try {
      const reader = new FileReader();
      const base64 = await new Promise<string>((resolve, reject) => {
        reader.onloadend = () => {
          const result = reader.result as string;
          resolve(result.split(',')[1] || result);
        };
        reader.onerror = reject;
        reader.readAsDataURL(audioBlob);
      });

      const body: Record<string, unknown> = { audio_b64: base64, format: 'webm' };
      if (language) body.language = language;

      const resp = await fetch(`${apiUrl}/api/v1/voice/asr`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'x-api-key': apiKey } : {}),
          'X-Tenant-Id': tenantId,
        },
        credentials: 'include',
        signal: controller.signal,
        body: JSON.stringify(body),
      });

      if (resp.ok) {
        const data = await resp.json();
        const whisperText = (data.text || data.transcript || '').trim();
        const conf = typeof data.confidence === 'number' ? data.confidence : null;
        setWhisperConfidence(conf);

        if (whisperText && whisperText !== browserTranscriptRef.current) {
          setTranscript(whisperText);
          setSource('whisper');
          setCorrected(true);
          onFinalRef.current?.(whisperText, 'whisper');
        }
      }
    } catch {
      // Whisper unavailable — browser transcript stands
    } finally {
      window.clearTimeout(timeoutId);
      setWhisperPending(false);
    }
  }, [apiUrl, apiKey, language, tenantId]);

  const start = useCallback(async () => {
    setError(null);
    setCorrected(false);
    setTranscript('');
    setSource(null);
    setWhisperConfidence(null);
    browserTranscriptRef.current = '';
    audioChunksRef.current = [];

    // --- Path 1: Browser SpeechRecognition ---
    const SpeechRecognitionAPI =
      (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (SpeechRecognitionAPI) {
      const recognition = new SpeechRecognitionAPI();
      recognition.continuous = false;
      recognition.interimResults = true;
      if (language) recognition.lang = language;
      recognition.onresult = (event: any) => {
        let interim = '';
        let final_ = '';
        for (let i = 0; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            final_ += result[0].transcript;
          } else {
            interim += result[0].transcript;
          }
        }
        const text = (final_ || interim).trim();
        if (text) {
          browserTranscriptRef.current = text;
          setTranscript(text);
          setSource('browser');
        }
      };
      recognition.onerror = (e: any) => {
        if (e.error !== 'no-speech') setError(`Speech recognition: ${e.error}`);
      };
      recognition.onend = () => {
        if (browserTranscriptRef.current) {
          onFinalRef.current?.(browserTranscriptRef.current, 'browser');
        }
      };
      recognition.start();
      recognitionRef.current = recognition;
    }

    // --- Path 2: MediaRecorder for Whisper ---
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const preferredMime = 'audio/webm;codecs=opus';
        const recorder = MediaRecorder.isTypeSupported?.(preferredMime)
          ? new MediaRecorder(stream, { mimeType: preferredMime })
          : new MediaRecorder(stream);
        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunksRef.current.push(e.data);
        };
        recorder.onstop = () => {
          stream.getTracks().forEach(t => t.stop());
          if (audioChunksRef.current.length > 0) {
            const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
            sendToWhisper(blob);
          }
        };
        recorder.start();
        mediaRecorderRef.current = recorder;
        recordingTimeoutRef.current = window.setTimeout(() => {
          try { recognitionRef.current?.stop(); } catch { /* ignore */ }
          if (mediaRecorderRef.current?.state !== 'inactive') {
            try { mediaRecorderRef.current?.stop(); } catch { /* ignore */ }
          }
          setIsRecording(false);
        }, Math.min(60_000, Math.max(1_000, maxDurationMs)));
    } catch {
      // Microphone access denied — browser STT may still work
    }

    setIsRecording(true);
  }, [language, maxDurationMs, sendToWhisper]);

  const stop = useCallback(() => {
    if (recordingTimeoutRef.current !== null) {
      window.clearTimeout(recordingTimeoutRef.current);
      recordingTimeoutRef.current = null;
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
      recognitionRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try { mediaRecorderRef.current.stop(); } catch { /* ignore */ }
      mediaRecorderRef.current = null;
    }
    setIsRecording(false);
  }, []);

  const toggle = useCallback(() => {
    if (isRecording) stop();
    else start();
  }, [isRecording, start, stop]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (recognitionRef.current) try { recognitionRef.current.stop(); } catch { /* */ }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        try { mediaRecorderRef.current.stop(); } catch { /* */ }
      }
      if (recordingTimeoutRef.current !== null) {
        window.clearTimeout(recordingTimeoutRef.current);
      }
    };
  }, []);

  return {
    transcript,
    isRecording,
    source,
    whisperConfidence,
    whisperPending,
    corrected,
    start,
    stop,
    toggle,
    error,
  };
}
