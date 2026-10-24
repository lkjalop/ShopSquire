# Currency/workload boundary repair

A real authenticated browser trace for “I need 20 laptops for CAD work” incorrectly recorded commercial currency CAD. The acronym described a workload, not a money amount. The same helper's money-only path recognized prefix codes but lost a suffix such as “10,000 USD”, risking disagreement between commercial terms and confirmed chat budget state.

Currency recognition now requires an adjacent amount or an explicit currency declaration. A bare dollar sign still has no ISO identity; multiple explicit currencies remain ambiguous. The money-only mode excludes declarations without amounts. Prefix/suffix positives cover AUD, USD, EUR, CAD, GBP and JPY. AUD/USD/EUR controls also exercise the actual confirmed-slot projection with total-budget semantics. These are parser/projection controls, not tax, FX or checkout qualification.

The initial 21 new controls reproduced **nine failures**. Their expectations were retained. Four additional projection/workload controls were then added. The independent public repair baseline plus the two repair files passed **68 tests, zero failures/errors/skips**, including existing commercial quantity, ISO budget, budget parity and bulk-budget controls. Changed-file Ruff passed. Private receipts: `implementation-20261024-currency-boundaries-red` and `implementation-20261024-currency-independent-v1`.

This remains a bounded grammar, not an assertion that every ambiguous acronym/number utterance is resolved. Explicit currency and price comparisons still need the reviewed commercial basis described in [the pricing contract](../PRICING_ACCEPTANCE_AND_REGIONAL_GROUNDING_2026-10-25.md).
