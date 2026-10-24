# Supplier-price privacy assertion specificity

25 October 2026. C18's full Python run reported a supplier-price privacy failure because the substring `700` appeared inside a valid microsecond timestamp. The finding and narration contained the quoted lead time, not the supplier wholesale price. Removing provenance to satisfy that assertion would have been incorrect.

The fixture now deterministically includes the same digits in an admitted observation timestamp. The old assertion fails reproducibly. Its replacement rejects a standalone money/minor-unit value (including currency-prefixed values) and rejects wholesale-price fields in the delivered finding, while preserving the valid source timestamp and lead-time positive. This is a test false-positive repair; the literal assertion changed, and no application privacy behavior was relaxed.

The independent market/quote/task cohort passes **95 tests, zero failures/errors/skips** after the deterministic single-test reproduction. C18's original failure remains in its receipt. This evidence does not qualify arbitrary PII removal or all narration schemas.
