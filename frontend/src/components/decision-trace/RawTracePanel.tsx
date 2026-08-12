type TraceEvent = Record<string, any>;

export default function RawTracePanel({
  trace,
  events,
  traceId,
  replay,
  replayLoading,
  classNames,
}: {
  trace: unknown;
  events: TraceEvent[];
  traceId: string;
  replay: unknown;
  replayLoading: boolean;
  classNames: { muted: string; sectionTitle: string; rawJson: string };
}) {
  const payload = trace || {
    trace_id: traceId,
    snapshot_status: 'unavailable',
    retained_normalized_events: events,
  };
  return (
    <>
      {replayLoading && <div className={classNames.muted}>Loading replay payload...</div>}
      {replay && (
        <>
          <div className={classNames.sectionTitle}>Replay</div>
          <pre className={classNames.rawJson}>{JSON.stringify(replay, null, 2)}</pre>
        </>
      )}
      <div className={classNames.sectionTitle}>Trace Payload</div>
      <pre className={classNames.rawJson}>{JSON.stringify(payload, null, 2)}</pre>
    </>
  );
}
