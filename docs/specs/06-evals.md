# 06 — Evals

## Goal

Quantitative evaluation suite that proves the three core claims: fingerprint robustness, leak detection accuracy, and tamper resilience. Results are committed to `evals/report.md` and surfaced in the README.

## Modules

- `evals/run_evals.py` — orchestrates all eval suites
- `evals/fingerprint_pairs.yaml` — 100 text pairs (original + paraphrase)
- `evals/leak_probe.yaml` — 20 known-in-corpus + 20 original sentences
- `evals/tamper_tests.yaml` — 50 tampered manifests
- `evals/report.md` — **hand-authored** narrative report: method, targets, what is
  measured versus deferred, and why. Committed, linked from the README, and never
  written by the runner.
- `evals/last-run.md` — machine-generated dump of the most recent run. This is what
  `run_evals.py` writes.

### Why two report files

`_write_report` emits a terse `suite: metric` dump. `evals/report.md` carries the
parts that cannot be auto-generated — that the combined SimHash + embedding number
was never measured, that leak detection is deferred pending live Common Crawl
access, and the reasoning behind both. Defaulting the runner's output at
`evals/report.md` meant that running the very command the README cites as the
reproduction step silently destroyed those caveats and replaced them with numbers
that look complete. The generated artifact therefore gets its own path, and
overwriting the curated file requires an explicit `-o evals/report.md`.

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

**Status — the >= 0.90 target is aspirational, and the shipped evaluator does not
measure it.** The method above describes SimHash *plus* cosine similarity, but
`src/inkprint/evals/fingerprint_eval.py` computes SimHash Hamming distance alone;
nothing under `src/inkprint/evals/` calls `compute_embedding` or `cosine`. What
the runner enforces is the SimHash-only baseline, `FINGERPRINT_TARGET = 0.85`.
Closing the gap needs a combined evaluator plus a Voyage API key; until then
>= 0.90 must be reported as a design target, never as a result. See
`evals/report.md` and spec 03's unchecked criterion.

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
- [x] `TC-E-04`: A report is written to the requested output path with scores and pass/fail.
- [x] `TC-E-14`: A default run (`uv run python evals/run_evals.py --skip-live-cc`, no `-o`)
      leaves `evals/report.md` **byte-identical**. The curated narrative is not a runner output.
- [x] `TC-E-15`: A default run writes the generated dump to `evals/last-run.md`.
- [x] `TC-E-16`: `-o <path>` still writes wherever it is pointed, including at
      `evals/report.md` — clobbering the curated file stays possible, but only on request.
- [x] `TC-E-17`: The CLI's exit code is the report's exit code (0 on pass, 1 on any missed target).

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
