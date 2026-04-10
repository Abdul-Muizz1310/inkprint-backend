# 03 — Fingerprint (SimHash + Embeddings)

## Goal

Produce a dual fingerprint for every piece of text: a 64-bit SimHash (hard, bitwise) and a 768-dimensional semantic embedding (soft, cosine). Together these enable both exact-match detection and paraphrase/derivative detection. Comparison functions score the distance between two fingerprints and return a verdict.

## Modules

- `src/inkprint/fingerprint/simhash.py` — compute 64-bit SimHash
- `src/inkprint/fingerprint/embed.py` — Voyage AI embeddings (768d)
- `src/inkprint/fingerprint/compare.py` — Hamming distance, cosine similarity, verdict mapper

## Inputs

### `compute_simhash(text: str) -> int`
- Raw text (not canonical bytes — SimHash operates on token shingles of the original text)

### `compute_embedding(text: str) -> list[float]`
- Raw text, sent to Voyage AI `voyage-3-lite` (or configured model)
- Returns 768-dimensional vector

### `compare(parent_simhash: int, parent_embedding: list[float], child_simhash: int, child_embedding: list[float]) -> CompareResult`
- Returns `CompareResult(hamming: int, cosine: float, verdict: str, overlap_pct: int)`
- `verdict` is one of: `"identical"`, `"near-duplicate"`, `"derivative"`, `"inspired"`, `"unrelated"`

## Outputs

- SimHash: 64-bit integer
- Embedding: list of 768 floats
- CompareResult: typed dataclass with hamming, cosine, verdict, overlap_pct

## Invariants

1. **SimHash determinism** — same text always produces the same 64-bit hash.
2. **Hamming distance** — identical text = 0; paraphrased = low (< `DERIVATIVE_HAMMING_THRESHOLD`); unrelated = high.
3. **Cosine similarity** — identical text = 1.0; paraphrased > `DERIVATIVE_COSINE_THRESHOLD`; unrelated < 0.5.
4. **Verdict mapping** — thresholds from config:
   - `identical`: hamming == 0 AND cosine >= 0.99
   - `near-duplicate`: hamming <= 3 OR cosine >= 0.95
   - `derivative`: hamming <= `DERIVATIVE_HAMMING_THRESHOLD` OR cosine >= `DERIVATIVE_COSINE_THRESHOLD`
   - `inspired`: cosine >= 0.70
   - `unrelated`: everything else
5. **Embedding calls are async** — Voyage API is external I/O.

## Test cases

### Happy path
- [ ] `TC-F-01`: SimHash of identical text produces distance 0.
- [ ] `TC-F-02`: SimHash of paraphrased text (same meaning, reworded) produces distance < 12.
- [ ] `TC-F-03`: SimHash of unrelated text produces distance > 20.
- [ ] `TC-F-04`: Embedding of identical text produces cosine similarity 1.0.
- [ ] `TC-F-05`: Compare identical texts returns verdict `"identical"`.
- [ ] `TC-F-06`: Compare a text with its paraphrase returns verdict `"near-duplicate"` or `"derivative"`.
- [ ] `TC-F-07`: Compare completely unrelated texts returns verdict `"unrelated"`.

### Edge cases
- [ ] `TC-F-08`: SimHash of empty string returns a consistent value (0 or defined sentinel).
- [ ] `TC-F-09`: SimHash of single word returns a valid 64-bit integer.
- [ ] `TC-F-10`: Embedding of very short text (< 10 chars) succeeds.
- [ ] `TC-F-11`: Embedding of text at MAX_TEXT_BYTES limit succeeds (Voyage may truncate; document behavior).
- [ ] `TC-F-12`: `overlap_pct` is 100 for identical, 0 for unrelated, proportional in between.

### Failure cases
- [ ] `TC-F-13`: Embedding call with invalid API key raises a clear error (not a silent fallback).
- [ ] `TC-F-14`: Embedding call timeout (mocked) raises within 30s.
- [ ] `TC-F-15`: SimHash with non-string input raises `TypeError`.

## Acceptance criteria

- [ ] SimHash + cosine correctly classify >= 90% of 100 text pairs (from `evals/fingerprint_pairs.yaml`).
- [ ] Verdict mapper uses configurable thresholds from settings.
- [ ] Embedding calls are async and respect timeout.
- [ ] All test cases pass.
