# /suggest golden corpus (V2 Phase 0 characterization oracle)

Recorded request→response→narration snapshots of the LIVE legacy `suggest()`, used as the
diff oracle for the V2 `recommendation_core` shadow run (see
`docs/SHOPSQUIRE_V2_GREENFIELD_ROADMAP_2026-07-10.md`).

- **Recorder:** `python tests/characterization/record_suggest_corpus.py` (API must be up;
  auth from `MERCHANT_API_KEY`). Each run uses a fresh session-uid tag so re-recording never
  inherits stale Redis session memory.
- **Battery:** `tests/characterization/batteries/starter_battery.json` — add cases there,
  not files here by hand.
- **Report:** `python tests/characterization/summarize_corpus.py`.
- **Differ:** `src/app/services/recommend_parity_full.py` compares any two payloads
  (BLOCKER/MAJOR/MINOR/INFO ladder + Phase-5 promotion gates).
- **known_wrong:** battery entries may tag recorded behavior as a bug (with the desired
  behavior). V2 must match the corpus EXCEPT where known_wrong says otherwise. Never
  "fix" a recorded file by hand — retag in the battery and re-record.

Regenerate only on a deliberately chosen commit (the corpus is pinned to a git SHA in each
file's `meta`); recording on a dirty tree makes the oracle unreproducible.
