# Timeout retry ownership repair

On repair base `3c17fe54`, four new controls reproduce two failures: an already-running timed-out function is automatically invoked again, and a function reporting uncertain provider acceptance is retried. Two completed-failure/breaker controls already pass. The unchanged new controls and two existing lifecycle/cancellation controls then pass **6/6** in the fresh exact 127-package API/test/bootstrap environment, with no errors/skips or resource-limit violation.

The helper now makes timeout terminal for automatic retry, still records breaker failure, and retains retry for a completed non-timeout failure. This is a conservative retry policy: a timeout does not establish whether an effect happened. It does not cancel running work, add external-effect idempotency or prove every completed exception is retry-safe. Native event/thread controls release and join their own workers.

[Python's executor contract](https://docs.python.org/3.11/library/concurrent.futures.html#concurrent.futures.Future.cancel) explains that cancellation cannot stop an already-running callable and that non-waiting shutdown does not end it. Transport-level deadlines, bounded admission, dependency isolation, executor generations and real provider reconciliation remain necessary.

A separate owned C22 diagnostic filled all eight workers with controlled blocked functions: a healthy call timed out, 41 cancelled work items remained queued after additional submissions, and non-waiting shutdown followed by recreation briefly had nine workers across generations. All owned threads were released/joined and source hashes were unchanged. These are controlled measurements, not a demonstrated production hang. This repair stops automatic timeout duplication; it does **not** close the separate admission/backlog/generation findings.

The larger C23 follow-up preserves the local ContextVar propagation change independently of this public cohort. C22 full/browser results predate the repair; later full/broad results require their own exact source and receipts.
