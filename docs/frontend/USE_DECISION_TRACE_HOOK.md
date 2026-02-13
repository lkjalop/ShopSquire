# useDecisionTrace Hook Migration

## Why migrate
- Single source of truth for SSE wiring and filters
- Reusable across panels; consistent lifecycle handling
- Easier testing and evolution (retry/backoff, auth headers)

## Trade-offs
- Slight indirection vs bespoke per-panel SSE
- May require hook options if panels diverge in behavior

## Usage
- Import and call in your component:
- Example:

  ```jsx
  import useDecisionTrace from '../../src/hooks/useDecisionTrace';

  export default function DevTracePanel() {
    const { events, filtered, isConnected, error, setShowQueuedOnly } = useDecisionTrace({ showQueuedOnly: true });
    // render from `filtered` or `events`
  }
  ```

## Migration steps
- Replace legacy SSE code in components with the hook
- If needed, extend hook props for custom filters or auth
- Validate with the decisions SSE endpoint(s) and trace event streams

## Debugging
- Verify server URL and CORS; check `isConnected`/`error`
- Confirm events include `cv_job_queued` / `fraud_job_queued` when filtering