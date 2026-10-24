# Local incident demonstration admission

25 October 2026. The published guard trusted a caller-controlled Host prefix and checked the explicit demo override before rejecting production/unknown environments. A stricter implementation existed in local WIP but was not yet integrated. This cohort isolates the two guard functions; every other syntax node in the router is identical to its committed baseline.

Seven new controls reproduced **four failures** on `405ff0a6`: an override admitted production/unknown environments, and two remote-peer requests could claim a local Host. The repair requires a recognized development/test environment and an actual loopback transport peer. Production/unknown environments remain denied despite the override; changing Host cannot confer local admission.

The unchanged new expectations and existing UI/API contracts pass **12 tests, zero failures/errors/skips**. Positive controls retain IPv4/IPv6 loopback admission and actual incident creation/token/message contracts in explicitly enabled local test fixtures. Negative HTTP requests are rejected before incident creation. Existing local tests now supply an explicit transport peer and restore their environment overrides instead of leaking them across tests. The fixture supplies no runtime bypass.

These controls do not certify reverse-proxy deployment or all incident authorization. Behind a proxy the actual transport/trusted-proxy configuration needs separate qualification. The publicly exposed production incident workflow still requires a complete authenticated-user design; the local demonstration guard is not that design.
