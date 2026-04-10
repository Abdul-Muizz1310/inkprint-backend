# 04 — Leak Scanner

## Goal

Given a signed certificate, query public AI training corpora (Common Crawl, HuggingFace datasets, The Stack v2) for near-duplicate text. Return a confidence score and hit details. The scan runs asynchronously — the API returns a job ID, the client polls or subscribes via SSE.

## Modules

- `src/inkprint/leak/scanner.py` — orchestrates scans across corpora
- `src/inkprint/leak/common_crawl.py` — CDX API client
- `src/inkprint/leak/huggingface.py` — HuggingFace datasets search API
- `src/inkprint/leak/the_stack.py` — BigCode/The Stack v2 index API
- `src/inkprint/leak/score.py` — aggregate hits into a confidence score

## Inputs

### `scan(certificate_id: UUID, corpora: list[str]) -> LeakScanResult`
- `certificate_id` — existing certificate with stored text in R2
- `corpora` — subset of `["common_crawl", "huggingface", "the_stack_v2"]`

### Per-corpus clients
- Common Crawl: CDX index query with title-like n-grams, WARC fetch, SimHash comparison
- HuggingFace: datasets search API query
- The Stack v2: BigCode index API (gated, requires HF auth token)

## Outputs

- `LeakScanResult` — persisted to `leak_scans` table:
  - `id`, `certificate_id`, `corpus`, `snapshot`, `hit_count`, `confidence`, `hits` (JSON array of `{url, excerpt, score}`), `scanned_at`

## Invariants

1. **Graceful degradation** — if The Stack v2 is unavailable (no HF token, rate limit, TOS not accepted), skip it with a warning; do not fail the entire scan.
2. **Common Crawl rate limit** — max 1 request/second to CDX API. Use `asyncio.Semaphore` or token bucket.
3. **Cache** — results per `(content_hash, corpus, snapshot)` are cached for 7 days. Re-scanning the same text against the same snapshot returns cached results.
4. **Confidence scoring** — `score()` aggregates hits across corpora:
   - 0 hits → confidence 0.0
   - 1-2 hits → confidence 0.3-0.5 (low, could be coincidence)
   - 3-5 hits → confidence 0.6-0.8 (moderate)
   - 6+ hits → confidence 0.9-1.0 (high)
   - Weighted by SimHash Hamming distance of each hit (closer = higher weight)
5. **Scan is async** — returns immediately with a job ID; results accumulate as corpora return.
6. **SSE streaming** — `/leak-scan/{id}/stream` emits events as each corpus completes.

## Test cases

### Happy path
- [ ] `TC-L-01`: Scan with `["common_crawl"]` on a known Wikipedia lead (e.g., "Albert Einstein was a German-born theoretical physicist...") returns >= 1 hit. (Integration, marked `@pytest.mark.slow`.)
- [ ] `TC-L-02`: Scan with all three corpora on original text returns 0 hits and confidence 0.0. (Integration, marked `@pytest.mark.slow`.)
- [ ] `TC-L-03`: Score function with 0 hits returns confidence 0.0.
- [ ] `TC-L-04`: Score function with 4 hits returns confidence in [0.6, 0.8].
- [ ] `TC-L-05`: Score function with 10 hits returns confidence >= 0.9.
- [ ] `TC-L-06`: SSE stream emits one event per corpus completion. (Mocked corpora.)

### Edge cases
- [ ] `TC-L-07`: Scan with empty corpora list returns immediately with 0 hits.
- [ ] `TC-L-08`: Scan with unknown corpus name raises `ValueError`.
- [ ] `TC-L-09`: Common Crawl returns 0 results for novel text — confidence 0.0 for that corpus.
- [ ] `TC-L-10`: Cache hit — re-scanning same text+corpus+snapshot returns cached result without API call.

### Failure cases
- [ ] `TC-L-11`: The Stack v2 unavailable (no HF token) — scan completes for other corpora with a warning, result includes `the_stack_v2: "skipped"`.
- [ ] `TC-L-12`: Common Crawl CDX timeout (mocked at 30s) — that corpus returns error, others continue.
- [ ] `TC-L-13`: HuggingFace API returns 429 — retry once, then mark that corpus as `"rate_limited"`.
- [ ] `TC-L-14`: Certificate ID not found — raises 404 before starting scan.
- [ ] `TC-L-15`: R2 download fails (text blob missing) — raises clear error with certificate_id context.

### Security
- [ ] `TC-L-16`: Scan request with non-UUID certificate_id is rejected at schema validation.

## Acceptance criteria

- [ ] Known-in-Common-Crawl passages hit >= 18/20 in eval suite.
- [ ] Original sentences produce <= 2/20 false positives.
- [ ] The Stack v2 fails gracefully when HF token is absent.
- [ ] Common Crawl respects 1 req/s rate limit.
- [ ] Results are cached for 7 days.
- [ ] All test cases pass.
