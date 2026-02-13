// Lightweight TraceClient adapter for SSE + polling. Export a singleton for reuse.
class TraceClient {
  constructor() {
    this.summaryEs = null;
    this.traceEs = null;
    this.poller = null;
    this.traceRetries = 0;
    this.summaryRetries = 0;
    this.maxRetries = 6; // ~ backoff up to ~60s
  }

  startSummary(url, onMessage) {
    try { this.stopSummary(); } catch (e) {}
    try {
      this.summaryEs = new EventSource(url);
      this.summaryEs.onmessage = (evt) => { try { onMessage(JSON.parse(evt.data || '{}')); this.summaryRetries = 0; } catch (e) {} };
      this.summaryEs.onerror = () => {
        try { if (this.summaryEs) this.summaryEs.close(); } catch (e) {}
        this.summaryEs = null;
        if (this.summaryRetries < this.maxRetries) {
          const delay = Math.min(1000 * Math.pow(2, this.summaryRetries), 15000);
          this.summaryRetries += 1;
          setTimeout(() => this.startSummary(url, onMessage), delay);
        }
      };
    } catch (e) {}
  }

  stopSummary() {
    try { if (this.summaryEs) this.summaryEs.close(); } catch (e) {}
    this.summaryEs = null;
  }

  startTrace(url, onMessage, pollFn = null, pollInterval = 4000) {
    try { this.stopTrace(); } catch (e) {}
    try {
      this.traceEs = new EventSource(url);
      this.traceEs.onmessage = (evt) => { try { onMessage(JSON.parse(evt.data || '[]')); this.traceRetries = 0; } catch (e) {} };
      this.traceEs.onerror = () => {
        try { if (this.traceEs) this.traceEs.close(); } catch (e) {}
        this.traceEs = null;
        // Exponential backoff reconnect; fallback to polling-only after max retries
        if (this.traceRetries < this.maxRetries) {
          const delay = Math.min(1000 * Math.pow(2, this.traceRetries), 15000);
          this.traceRetries += 1;
          setTimeout(() => this.startTrace(url, onMessage, pollFn, pollInterval), delay);
        } else {
          // Stop trying SSE; rely on poller
          this.traceRetries = 0;
        }
      };
    } catch (e) {}
    if (pollFn) {
      this.poller = setInterval(async () => { try { await pollFn(); } catch (e) {} }, pollInterval);
    }
  }

  stopTrace() {
    try { if (this.traceEs) this.traceEs.close(); } catch (e) {}
    this.traceEs = null;
    if (this.poller) clearInterval(this.poller);
    this.poller = null;
  }
}

const client = new TraceClient();
export default client;

// Also expose a global hook for non-module embed contexts
try {
  if (typeof window !== 'undefined' && !window.ShopSquireTraceClient) {
    window.ShopSquireTraceClient = client;
  }
} catch (e) {}
