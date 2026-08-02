# Eval Report — inkprint v0.1.0

Date: 2026-04-10

> Hand-authored. `run_evals.py` never writes this file — it writes its metric dump
> to `evals/last-run.md` (gitignored). Reproduce the numbers below with
> `uv run python evals/run_evals.py --skip-live-cc` and compare; what lives here
> that a generator cannot produce is *what is measured versus deferred, and why*.

## Fingerprint robustness (SimHash-only baseline)

- **Dataset:** 100 text pairs (60 similar, 40 unrelated)
- **Method:** SimHash Hamming distance, threshold = 28
- **Result:** 86/100 = **86% accuracy**
- **Target:** >= 85% (SimHash-only)
- **Status:** PASS

The SimHash-only classifier peaks at 86% on this dataset.

### Combined SimHash + embedding: NOT MEASURED

The hypothesis is that adding cosine similarity over Voyage `voyage-3-lite`
embeddings pushes accuracy past 90%, because cosine similarity should correctly
classify paraphrases that share semantic meaning but differ in surface-level
n-grams. **That number has never been measured.** There is no combined
evaluator: `src/inkprint/evals/fingerprint_eval.py` is the only fingerprint
evaluator and computes SimHash Hamming distance alone; nothing under
`src/inkprint/evals/` calls `compute_embedding` or `cosine`. Running the combined
suite needs a Voyage API key and an evaluator that does not exist yet, so >= 90%
is a **design target**, not a result.

## Tamper resilience

- **Dataset:** 50 tampered C2PA manifests
- **Distribution:** 10 corrupted_signature, 10 wrong_hash, 10 changed_author, 10 shifted_timestamp, 5 wrong_key_id, 5 missing_signature
- **Result:** 50/50 = **100% rejected**
- **Target:** 50/50
- **Status:** PASS

## Leak detection (Common Crawl)

- **Dataset:** 20 known-in-corpus + 20 original sentences
- **Method:** Common Crawl CDX index query
- **Target:** >= 18/20 true positives, <= 2/20 false positives
- **Status:** DEFERRED (requires live Common Crawl access; run via `uv run python evals/run_evals.py`)

## Summary

| Suite | Result | Target | Status |
|---|---|---|---|
| Fingerprint (SimHash) | 86% | >= 85% | PASS |
| Fingerprint (SimHash + embedding) | not measured | >= 90% | NOT IMPLEMENTED — no combined evaluator |
| Tamper resilience | 50/50 | 50/50 | PASS |
| Leak detection | deferred | 18/20 TP, <= 2 FP | DEFERRED — needs live Common Crawl access |
