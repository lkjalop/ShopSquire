# Dependency worker request context

Three new real-thread controls fail on repair base `e336fc66`: worker identity is absent, a completed retry retains a worker mutation instead of the caller identity, and two concurrent caller identities are lost. Copying the caller context separately for each submitted attempt repairs those unchanged expectations.

The first combined selection records eight passes and one failure: the old cancellation-control mock accepted only `submit(fn)`. Its fixture now accepts the real executor's additional arguments; the timeout/cancellation assertions are unchanged. The final selection passes **9/9**, with zero errors/skips or resource-limit violation, in the fresh exact 127-package API/test/bootstrap environment. Six controls overlap the earlier timeout cohort and must not be added as six more distinct contracts.

The helper and cancellation fixture match the implementation already present in the frozen C23 candidate. This commit coherently integrates that previously local dependency into the public repair branch; the new context test file is separately qualified, not retroactively included in C23's test count.

The [Python context contract](https://docs.python.org/3.11/library/contextvars.html#contextvars.copy_context) is the mechanism used. It preserves ContextVar bindings; it does not make captured mutable objects or SQLAlchemy Sessions safe for concurrent use. Transport deadlines, worker-local database sessions, backlog admission and lifecycle-generation ownership remain separate requirements. No new framework or dependency is introduced.
