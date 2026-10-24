# Explicit CI actors and distributed memory erasure

The V2 workflow now declares its test environment, local fixture roles, disabled model warmups and sandbox commercial transports. The PostgreSQL workflow uses the same bounded profile. This fixes test setup that previously encountered authentication rejection before its intended positive assertions; application authentication and rejection controls remain enabled. Normal test execution no longer receives Splunk connector secrets or posts an optional external event.

On an independently assembled checkout of the public repair branch plus these workflow/test files, the exact V2 workflow file selection produced **690 passes and five skips**. The skips retain their prerequisite meanings. This local result is not a hosted Linux CI result.

The PostgreSQL workflow selection plus the new privacy tests ran against disposable loopback PostgreSQL and Redis: **22 passes and two skips**, no failures/errors or resource violation. The two database-matrix cases lacked the native profile's matrix-engine admission and remain unqualified by this result. Both owned containers were removed. The HTTP money-race positives ran with actual authentication.

The two privacy controls start separate API processes sharing a database and explicit owned Redis. They verify erasure visibility, a partitioned backend's action-required result, an explicit retry from the second instance, repeat deletion, and preservation of another controller's data. Anonymous and merchant deletion remain rejected. Raw export remains rejected by PII-01; successful approved export is not qualified here.

Coverage is specifically indexed Redis memory/cache and the deletion-job ledger. Canonical shopping cases, attachments, derived multimodal evidence, historical business records and backups still need an explicit retention/erasure policy and verification. A legacy deletion job's completed state is not certification that every data plane was erased.

The integration workflow explicitly admits the new two-process privacy controls with its disposable Redis service. Private receipts: `implementation-20261024-ci-v2-profile-v1` and `implementation-20261024-ci-profile-native-v1`. No mail, payment, ERP or external telemetry effect was performed.
