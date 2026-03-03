import { useRef, useState, useCallback, useEffect } from 'react';

interface DualSTTResult {
  /** Current best transcript (browser or Whisper, whichever arrived last) */
  transcript: string;
  /** Whether the mic is actively recording */
  isRecording: boolean;
  /** Source of current transcript: 'browser' | 'whisper' | 'none' */
  source: 'browser' | 'whisper' | 'none';
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
  /** Callback when final transcript is ready */
  onFinalTranscript?: (text: string, source: 'browser' | 'whisper') => void;
}

/**
 * Dual-path speech-to-text hook: runs browser SpeechRecognition for instant
 * interim transcripts AND streams audio to Whisper backend for high-accuracy
 * correction. Browser transcript appears instantly; Whisper replaces it if different.
 */
export function useDualSTT(options: UseDualSTTOptions = {}): DualSTTResult {
  const { apiUrl = '', apiKey = '', language, onFinalTranscript } = options;

  const [transcript, setTranscript] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [source, setSource] = useState<'browser' | 'whisper' | 'none'>('none');
  const [whisperConfidence, setWhisperConfidence] = useState<number | null>(null);
  const [whisperPending, setWhisperPending] = useState(false);
  const [corrected, setCorrected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const browserTranscriptRef = useRef('');
  const onFinalRef = useRef(onFinalTranscript);

  useEffect(() => {
    onFinalRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  const sendToWhisper = useCallback(async (audioBlob: Blob) => {
    if (!apiUrl) return;
    setWhisperPending(true);
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
        },
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
      setWhisperPending(false);
    }
  }, [apiUrl, apiKey, language]);

  const start = useCallback(async () => {
    setError(null);
    setCorrected(false);
    setTranscript('');
    setSource('none');
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
    if (apiUrl) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
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
      } catch {
        // Microphone access denied — browser STT may still work
      }
    }

    setIsRecording(true);
  }, [apiUrl, language, sendToWhisper]);

  const stop = useCallback(() => {
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
