# Research refresh and application decisions

Checked 5 October 2026. These are research-informed experiment choices, not measured improvements in ShopSquire. Keep deterministic identity, authorization, freshness and transaction safeguards separate from model proposals.

| Research | What the source establishes | Application to ShopSquire |
| --- | --- | --- |
| [LongMemEval-V2, May 2026](https://arxiv.org/abs/2605.12493) | A benchmark for agent memory over accumulated experience, including multimodal web-agent histories; it introduces retrieval and file-based memory approaches. | Extend memory evaluation beyond fact recall: changing requirements, exception handling, learned procedures and later actions. Compare current SQL case state plus retrieval against a memory challenger. Measure current-fact correctness, evidence attribution, isolation, latency and storage. A passing image-correction test is only a small local analogue, not a LongMemEval score. |
| [Chronos-2, October 2025](https://www.amazon.science/blog/introducing-chronos-2-from-univariate-to-universal-forecasting) | A forecasting foundation model supporting univariate, multivariate and covariate-informed tasks. | Optional isolated forecasting challenger after reconciled event histories and cutoff-safe covariates exist. Keep the current mean/EWMA baselines. Score operational cost, stockouts and excess stock with identical information and budgets; include loading time and memory. Do not feed future realized supplier delays or retrospective news into past forecasts. |
| [BenchmarkQED, June 2025](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/) | Evaluation distinguishes local and global query classes; the reported relative strengths vary by retrieval method and query class. | Freeze merchant questions before choosing infrastructure. Exact SKU/ETA questions start with scoped SQL and lexical/dense retrieval. Only benchmark a graph for demonstrated multi-hop/global questions such as shared supplier exposure. Include indexing and query costs, provenance, tenant filtering and stale-evidence rejection. Synthesized questions still need independent relevance review. |
| [Anthropic browser prompt-injection defenses, November 2025](https://www.anthropic.com/research/prompt-injection-defenses) | Reports progress and remaining vulnerability in browser-agent prompt-injection defenses; it does not claim immunity. | Test hostile pages, supplier replies, OCR and memory separately from direct requests. Score durable unauthorized effects and canary disclosure, not just refusal wording. Retain benign controls and repeated/adaptive attempts. Model defenses supplement exact-effect authorization and untrusted-source handling; they cannot grant permission. |

These recommendations are my application of the sources to the observed platform gaps. The papers do not demonstrate that ShopSquire needs a graph, larger context, a new recommendation version or a particular winning model.

## Applied during this execution

- Preserved literal facts separately from committed case facts and tested corrections across model/image turns.
- Added a live consented discovery browser run with fixtures disabled, unchanged commerce effects and truthful withheld qualification.
- Added cross-tenant canaries and complete-row effect fingerprints across tenants, so an update to an existing record cannot hide behind an unchanged row count.
- Kept forecasting challengers unpromoted because the existing synthetic comparison does not establish operational improvement.
- Repaired actual integration/resource defects before expanding model infrastructure: metric label cardinality, SQLite identity replacement, stale workflow writes, uncertain ERP receipts and terminal budget/quantity disagreement.

## Still experiments, not delivered results

Independent benchmark review, a Chronos-2 comparison, graph-versus-hybrid evaluation, distributed memory recovery and comprehensive OCR/memory injection evaluation remain open. No model weights or graph infrastructure were installed as a consequence of this review.
