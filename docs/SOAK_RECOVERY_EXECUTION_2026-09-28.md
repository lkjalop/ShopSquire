# Soak investigation, recovery and demo evidence — 28 September 2026

## Observed failure

The September 27 eight-hour browser replay stopped on cycle 352 after 25,911.219 seconds
(7h11m51s). It completed 351 cycles of three journeys. Two journeys passed in the final cycle;
the fictional qualification journey failed while waiting for the requirement selector.

The retained Playwright trace records Chromium `net::ERR_NO_BUFFER_SPACE` for the contract GET.
The page showed `TypeError: Failed to fetch`. Another contract GET returned 200. The evidence
does not establish the underlying resource-exhaustion cause. No historical memory/socket/handle
measurements were collected by that runner. The original failure remains preserved under
`.artifacts/portfolio-journey-2026-09-27/overnight-browser/`.

## Implemented changes

- Requirement loading cancels obsolete reads on case change/unmount, including development
  effect cleanup. A failed initial read offers an explicit Retry button. Retrying performs a GET,
  does not select a contract, and clears the error after successful loading.
- Added a fault-injected Playwright test that aborts contract reads, then permits a real API retry
  and subsequent qualification. This verifies recovery; it does not reproduce OS buffer exhaustion.
- The soak records host available memory, TCP state counts and application-process RSS, thread
  and handle counts before, during and after cycles. It does not collect command lines or tokens.
  Application processes are discovered through the runner and the isolated service listeners.
- The harness fingerprints its own code and Playwright configuration in addition to application
  sources. Invocation exceptions produce an explicit failed status instead of leaving a running record.
- Added read-only synthetic inventory reconciliation: immutable fixture balances plus recorded
  reservation/shipment/return deltas are compared with canonical stock. Missing baseline, missing
  stock and drift cannot be reported as reconciled. It does not automatically repair stock or grant
  commerce authority, and does not replace accepted-order integration or reservation expiry.

## Verification

Artifacts: `.artifacts/soak-recovery-2026-09-28/`.

- `ui-red.log` → `ui-green.log`: two new failures demonstrated before repair; all three component tests pass.
- `reconciliation-red.log` → `reconciliation-green.log`: new reconciliation tests, plus inventory/history/scenario regressions; 27 pass.
- `harness-red.log` → `backend-final.log`: harness exception regression and combined inventory tests; 30 pass. Counts overlap previous runs.
- `browser-final.log`: four Playwright journeys pass against the real local API; only the new recovery journey deliberately injects a failed network read.
- `build.log`: frontend production build exits zero. Function-size and scoped Ruff F821 checks pass.
- `diagnostic-smoke/status.json`: three cycles pass over 43.531 measured seconds. Twelve resource
  samples have no collection errors; minimum observed available memory is 6,702,731,264 bytes,
  maximum application-process count is 10, peak TCP TIME_WAIT count is 253. These are short-run
  observations, not endurance thresholds or a causal explanation of the prior failure.

The final harness revision has a fresh eight-hour run launched around 06:48 Sydney time on
September 28. Status: `.artifacts/soak-recovery-2026-09-28/eight-hour-browser/status.json`.
Resource samples: `resources.jsonl` in that directory. The launcher PID is in `soak.pid`.
The diagnostic dependency is pinned in `scripts/requirements-soak.txt` (psutil 7.2.2).

The run retains the original three journeys, disables retries, stops on any failed cycle or source
change, and requires the full elapsed duration plus adequate cycle count. Resource measurements
are diagnostic; no resource-growth acceptance threshold has yet been justified from an endurance
baseline. A passed rerun alone would not establish that the original buffer-exhaustion cause was fixed.

## Next integration work

Accepted-order inventory holds, supplier conversations, accepted 30-to-40 amendments, authenticated
person enrollment/approval UI, operator renewal/recovery, bundles, attack evaluations, market
decisions, representative benchmarks and remote CI/release evidence remain open. The original
model/image/restart soak is distinct from this repeated browser/API run.

The [demo and hiring guide](DEMO_AND_HIRING_NARRATIVE_2026-09-28.md) provides a current six-minute
walkthrough, the intended full workflow, and evidence-qualified language for TDD, testing,
harness engineering, loop engineering, security and CI/CD. No real product was newly qualified.
