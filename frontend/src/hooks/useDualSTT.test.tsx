import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDualSTT } from './useDualSTT';


class FakeRecognition {
  continuous = false;
  interimResults = false;
  lang = '';
  onresult: ((event: any) => void) | null = null;
  onerror: ((event: any) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
}

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  state = 'inactive';
  mimeType = 'audio/webm;codecs=opus';
  ondataavailable: ((event: any) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(_stream: MediaStream, options?: MediaRecorderOptions) {
    this.mimeType = options?.mimeType || 'audio/webm';
  }

  start() {
    this.state = 'recording';
  }

  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['voice-bytes'], { type: 'audio/webm' }) });
    this.onstop?.();
  }
}

describe('useDualSTT', () => {
  let recognition: FakeRecognition;
  const stopTrack = vi.fn();

  beforeEach(() => {
    recognition = new FakeRecognition();
    (window as any).SpeechRecognition = vi.fn(() => recognition);
    (window as any).webkitSpeechRecognition = undefined;
    (globalThis as any).MediaRecorder = FakeMediaRecorder;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn(async () => ({
          getTracks: () => [{ stop: stopTrack }],
        })),
      },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).SpeechRecognition;
  });

  it('does not mark ordinary typed input as voice before recording', () => {
    const { result } = renderHook(() => useDualSTT());
    expect(result.current.source).toBeNull();
    expect(result.current.isRecording).toBe(false);
  });

  it('keeps the browser transcript when correction is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('provider unavailable');
    }));
    const { result } = renderHook(() => useDualSTT({ apiUrl: 'http://api.test' }));

    await act(async () => result.current.start());
    act(() => {
      recognition.onresult?.({
        results: [{ isFinal: true, 0: { transcript: 'twenty work laptops' } }],
      });
      recognition.onend?.();
      result.current.stop();
    });

    await waitFor(() => expect(result.current.whisperPending).toBe(false));
    expect(result.current.transcript).toBe('twenty work laptops');
    expect(result.current.source).toBe('browser');
  });

  it('accepts a bounded Whisper correction without dispatching a second query', async () => {
    const onFinal = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        transcript: 'twenty-five work laptops',
        confidence: 0.93,
        provider: 'test-asr',
        status: 'ready',
      }),
    })));
    const { result } = renderHook(() => useDualSTT({
      apiUrl: 'http://api.test',
      apiKey: 'test-key',
      tenantId: 'tenant-a',
      onFinalTranscript: onFinal,
    }));

    await act(async () => result.current.start());
    act(() => {
      recognition.onresult?.({
        results: [{ isFinal: true, 0: { transcript: 'twenty five work laptops' } }],
      });
      recognition.onend?.();
      result.current.stop();
    });

    await waitFor(() => expect(result.current.source).toBe('whisper'));
    expect(result.current.transcript).toBe('twenty-five work laptops');
    expect(result.current.whisperConfidence).toBe(0.93);
    expect(result.current.corrected).toBe(true);
    expect(onFinal).toHaveBeenCalledWith('twenty-five work laptops', 'whisper');
    expect(stopTrack).toHaveBeenCalled();
  });
});
