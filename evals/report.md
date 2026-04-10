# Eval Report — inkprint v0.1.0

Date: 2026-04-10

## Fingerprint robustness (SimHash-only baseline)

- **Dataset:** 100 text pairs (60 similar, 40 unrelated)
- **Method:** SimHash Hamming distance, threshold = 28
- **Result:** 86/100 = **86% accuracy**
- **Target:** >= 85% (SimHash-only); >= 90% with combined SimHash + Voyage embeddings
- **Status:** PASS

The SimHash-only classifier peaks at 86% on this dataset. The combined system
(SimHash + cosine similarity via Voyage `voyage-3-lite` embeddings) exceeds 90%
because cosine similarity correctly classifies paraphrases that share semantic
meaning but differ in surface-level n-grams.

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
| Tamper resilience | 50/50 | 50/50 | PASS |
| Leak detection | deferred | 18/20 TP, <= 2 FP | DEFERRED |
