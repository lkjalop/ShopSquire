# Shared local-demo admission policy

25 October 2026. Follow-up found the incident guard contract duplicated differently in the merchant dashboard and query-cluster analytics routes. Host-based/local override paths could still bypass admission there. One shared environment-and-transport-peer policy replaces the duplicated decisions; endpoint role checks remain enabled.

The new cross-surface and HTTP controls reproduced **13 failures among 35 controls** on `32a39bbd`. The unchanged expectations plus existing incident/UI, query-cluster and metrics controls pass **50 tests, zero failures/errors/skips** on the independently assembled cohort.

An override is accepted only in recognized local/development/test environments and for an actual loopback peer. Test mode requires explicit enablement. Production, unknown/unset environments, remote peers and unrecognized non-empty toggle values cannot acquire this demo privilege. Host/forwarded text does not establish peer identity. A denied analytics demo request must pass normal authentication before any dataset read. Local positive controls are retained.

This removes duplicated admission decisions; it does not qualify trusted-proxy deployments, all merchant-page policy, multi-tenant analytics storage or semantic clustering quality. The selected existing query-cluster metric test still takes about 28 seconds on a cold full environment. Its passing volume counter does not establish embedding readiness, latency or semantic accuracy. The legacy analytics dataset and embedding cache need separate tenant/retention and provider contracts; those gaps remain open.
