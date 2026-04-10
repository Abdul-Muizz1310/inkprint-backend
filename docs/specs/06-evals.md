# 06 — Evals

## Goal

Quantitative evaluation suite that proves the three core claims: fingerprint robustness, leak detection accuracy, and tamper resilience. Results are committed to `evals/report.md` and surfaced in the README.

## Modules

- `evals/run_evals.py` — orchestrates all eval suites
- `evals/fingerprint_pairs.yaml` — 100 text pairs (original + paraphrase)
- `evals/leak_probe.yaml` — 20 known-in-corpus + 20 original sentences
- `evals/tamper_tests.yaml` — 50 tampered manifests
- `evals/report.md` — generated results

## Eval suites

### 1. Fingerprint robustness (target: >= 90%)

**Dataset:** 100 text pairs in `fingerprint_pairs.yaml`. Each pair has:
- `original`: source text
- `variant`: paraphrased, lightly edited, or unrelated text
- `expected`: `"similar"` or `"unrelated"`

**Method:** Compute SimHash + cosine similarity for each pair. Use the verdict mapper from spec 03. A pair is correctly classified if:
- `expected == "similar"` and verdict is `"identical"`, `"near-duplicate"`, or `"derivative"`
- `expected == "unrelated"` and verdict is `"unrelated"`

**Metric:** accuracy = correct / 100. Target >= 0.90.

### 2. Leak detection accuracy (target: >= 18/20 true positives, <= 2/20 false positives)

**Dataset:** `leak_probe.yaml` with two sections:
- `known_leaked` (20 entries): famous Wikipedia opening paragraphs, public-domain text known to be in Common Crawl.
- `clean` (20 entries): original sentences written for this eval, never published.

**Method:** For each entry, run `scan(corpora=["common_crawl"])`. Check:
- `known_leaked`: expect `hit_count >= 1`
- `clean`: expect `hit_count == 0`

**Metrics:**
- True positive rate: hits on known_leaked / 20. Target >= 18/20.
- False positive rate: hits on clean / 20. Target <= 2/20.

### 3. Tamper resilience (target: 50/50)

**Dataset:** `tamper_tests.yaml` with 50 entries. Each is a valid manifest with one specific tampering:
- 10: `signature.value` corrupted (random base64)
- 10: `c2pa.hash.data.hash` changed to wrong SHA-256
- 10: `author` field changed after signing
- 10: `issued_at` shifted by 1 second
- 5: `key_id` changed to unknown key
- 5: entire `signature` block removed

**Method:** For each tampered manifest, call `verify()`. Every single one must return `valid: false`.

**Metric:** rejection rate = rejected / 50. Target = 50/50 (100%).

## Test cases

### Runner
- [ ] `TC-E-01`: `run_evals.py` exits 0 when all targets met.
- [ ] `TC-E-02`: `run_evals.py` exits 1 when any target missed.
- [ ] `TC-E-03`: `run_evals.py --skip-live-cc` skips leak detection suite (fast mode).
- [ ] `TC-E-04`: Report is written to `evals/report.md` with date, scores, and pass/fail.

### Fingerprint eval
- [ ] `TC-E-05`: YAML file has exactly 100 pairs.
- [ ] `TC-E-06`: Each pair has `original`, `variant`, `expected` fields.
- [ ] `TC-E-07`: Accuracy >= 0.90 on the full set.

### Leak eval
- [ ] `TC-E-08`: YAML file has 20 known_leaked + 20 clean entries.
- [ ] `TC-E-09`: True positive rate >= 18/20.
- [ ] `TC-E-10`: False positive rate <= 2/20.

### Tamper eval
- [ ] `TC-E-11`: YAML file has exactly 50 tampered manifests.
- [ ] `TC-E-12`: Each manifest has a `tamper_type` label.
- [ ] `TC-E-13`: Rejection rate = 50/50.

## Acceptance criteria

- [ ] `evals/report.md` committed with all three scores meeting targets.
- [ ] `run_evals.py` is runnable standalone: `uv run python evals/run_evals.py`.
- [ ] Fast mode (`--skip-live-cc`) completes in < 60s.
- [ ] Full mode completes in < 10 min (Common Crawl rate limit is the bottleneck).
- [ ] All test cases pass.
