# ShopSquire worktree reconciliation — 2026-08-10

This is an ownership and disposition inventory, not authorization to delete or
reset files. The source snapshot is `WORKTREE_RECONCILIATION_2026-08-10.csv`.

## Snapshot

- 198 dirty paths before these two reconciliation artifacts were added.
- 128 tracked modifications: preserve and review by bounded implementation slice.
- 70 untracked paths.
- 0 staged paths.

## Proposed dispositions

| Disposition | Count | Required action |
|---|---:|---|
| `preserve_review_required` | 128 | Inspect the tracked diff and assign an owner before staging any hunk. |
| `implementation_review` | 32 | Validate source/test/config dependency closure and commit only with focused tests. |
| `preserve_archive_review` | 34 | Decide whether each document is canonical, historical, superseded, or private working material. |
| `evidence_archive_candidate` | 3 | Curate named screenshots/artifacts into a dated evidence bundle before removing duplicates. |
| `generated_cleanup_candidate` | 1 | Verify process state and ownership, then request explicit cleanup approval. |

## Release boundary established in this run

- Storefront and admin dependency manifests are now committed on one Vite 8 / Vitest 4 toolchain.
- Both dependency audits report zero known npm vulnerabilities at the time of certification.
- Storefront: 265 tests and production build passed.
- Admin: 47 tests and production build passed.
- The supplier and commercial-decision slices were staged explicitly; no bulk staging was used.
- V2 compatibility tests remain part of the focused regression gate.

## Rules for the remaining tree

1. Never use `git add -A`, reset, or blanket cleanup.
2. Stage explicit files or reviewed hunks only.
3. Every source slice must include its focused tests and clean-checkout import/build proof.
4. Do not remove untracked documents, evidence, or scratchpad material without owner adjudication.
5. Generated caches may be removed only after resolving exact paths and confirming no live process owns them.

