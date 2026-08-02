# Demo Script

Step-by-step walkthrough for interviews and live demos.

## Prerequisites

- Backend live at `https://inkprint-backend.onrender.com` (check `/health`)
- A terminal with `curl` and `python` (for JSON formatting)

## 1. Issue a certificate (10 seconds)

```bash
curl -s -X POST https://inkprint-backend.onrender.com/certificates \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The quick brown fox jumps over the lazy dog. This sentence was written by me on April 10, 2026.",
    "author": "demo@inkprint.dev"
  }' | python -m json.tool
```

**What to show:** the response includes an `id`, `content_hash` (SHA-256), `simhash` (64-bit), `signature` (Ed25519 base64), and a full C2PA v2.2 `manifest` with `@context`, assertions, and signed fields.

## 2. Verify the certificate (5 seconds)

Copy the `manifest` from step 1 and verify it:

```bash
curl -s -X POST https://inkprint-backend.onrender.com/verify \
  -H "Content-Type: application/json" \
  -d '{"manifest": <paste-manifest>, "text": "The quick brown fox..."}' | python -m json.tool
```

**What to show:** `{"valid": true, "checks": {"hash": true, "signature": true}}`.

`checks` has exactly these two keys. If asked why there is no simhash/embedding
verdict here: the C2PA manifest carries no such fields, so `/verify` verifies what
the manifest actually binds. Paraphrase comparison is step 5 (`/diff`) and step 8
(`/verify/batch` with `text`).

## 3. Tamper detection (5 seconds)

Same manifest, different text:

```bash
curl -s -X POST https://inkprint-backend.onrender.com/verify \
  -H "Content-Type: application/json" \
  -d '{"manifest": <same-manifest>, "text": "TAMPERED TEXT"}' | python -m json.tool
```

**What to show:** `{"valid": false}` — the hash no longer matches.

## 4. Get the QR code

```bash
curl -s https://inkprint-backend.onrender.com/certificates/{id}/qr -o cert-qr.png
```

**What to show:** a QR code PNG that links to the verification URL.

## 5. Diff / derivative detection

```bash
curl -s -X POST https://inkprint-backend.onrender.com/diff \
  -H "Content-Type: application/json" \
  -d '{"parent_id": "<cert-id>", "text": "The quick brown fox leaps over the sleepy dog. This sentence was rewritten."}' \
  | python -m json.tool
```

**What to show:** `hamming` distance, `cosine` similarity, `verdict` (e.g. "derivative"), `overlap_pct`.

## 6. Public key endpoint

```bash
curl -s https://inkprint-backend.onrender.com/public-key.pem
```

**What to show:** anyone can download the public key and verify signatures independently — no trust in the inkprint server required.

## 7. Leak scan across public training corpora

```bash
SCAN=$(curl -s -X POST https://inkprint-backend.onrender.com/leak-scan \
  -H "Content-Type: application/json" \
  -d '{"certificate_id": "<cert-id>"}' | python -c "import json,sys; print(json.load(sys.stdin)['scan_id'])")

# Poll the job
curl -s https://inkprint-backend.onrender.com/leak-scan/$SCAN | python -m json.tool
```

**What to show:** `POST` returns `202 {scan_id, status: "pending"}` immediately — the
scan is a real background task, not a blocking call. The poll returns per-corpus
results (Common Crawl CDX, HuggingFace datasets, The Stack v2) with a confidence
score and hit URLs. Re-scanning the same text hits the 7-day cache
(`leak_scan_cache`) instead of re-querying the corpora.

### 7b. Watch it live over SSE

```bash
curl -N https://inkprint-backend.onrender.com/leak-scan/$SCAN/stream
```

**What to show:** `text/event-stream` progress events as each corpus reports in.

## 8. Batch issue and batch verify

```bash
curl -s -X POST https://inkprint-backend.onrender.com/certificates/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [
        {"text": "First original paragraph.",  "author": "demo@inkprint.dev"},
        {"text": "Second original paragraph.", "author": "demo@inkprint.dev"}
      ]}' | python -m json.tool
```

**What to show:** N certificates issued atomically — if any item fails (bad shape,
embedding backend down, manifest that fails schema validation), *none* are
persisted. Then verify them together, supplying `text` to get the paraphrase
verdicts `/verify` cannot give:

```bash
curl -s -X POST https://inkprint-backend.onrender.com/verify/batch \
  -H "Content-Type: application/json" \
  -d '{"items": [{"certificate_id": "<id-1>", "text": "First original paragraph."}]}' \
  | python -m json.tool
```

**What to show:** per-item `checks` with `signature`, `hash`, **and** `simhash` +
`embedding`; an unknown id fails softly with `reason: "unknown_certificate"`
rather than failing the whole request.

## 9. Dossier envelope

```bash
curl -s -X POST https://inkprint-backend.onrender.com/dossiers/envelope \
  -H "Content-Type: application/json" \
  -d '{
    "dossier_id": "<uuid>",
    "evidence_cert_ids": ["<id-1>", "<id-2>"],
    "debate_transcript_hash": "'"$(python -c "print('a'*64)")"'",
    "perf_receipt_hash": "'"$(python -c "print('b'*64)")"'"
  }' | python -m json.tool
```

**What to show:** one signed C2PA-aligned manifest binding a whole bundle of
evidence certificates. Re-submitting the same bundle is idempotent (same
signature back); submitting a *different* bundle under the same `dossier_id`
returns `409`. This is the integration surface bastion consumes.

## 10. Semantic and exact search

```bash
curl -s "https://inkprint-backend.onrender.com/search?text=The%20quick%20brown%20fox&mode=exact" | python -m json.tool
curl -s "https://inkprint-backend.onrender.com/search?text=a%20fast%20auburn%20fox&mode=semantic" | python -m json.tool
```

**What to show:** exact mode matches the canonical SHA-256; semantic mode ranks by
embedding cosine similarity. Semantic ranking is only meaningful with a real
Voyage key configured — without one, embeddings are zero vectors and semantic
search deliberately returns nothing rather than arbitrary noise.

## 11. Operational surface

```bash
curl -s https://inkprint-backend.onrender.com/health   | python -m json.tool
curl -s https://inkprint-backend.onrender.com/metrics  | head -20
curl -sD - -o /dev/null https://inkprint-backend.onrender.com/health | grep -i x-request-id
```

**What to show:** `/health` reports `db` connectivity and the deployed
`commit_sha`; `/metrics` is Prometheus text (request latency, counts); every
response carries an `X-Request-ID`.

## Negative case worth showing

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://inkprint-backend.onrender.com/certificates \
  -H "Content-Type: application/json" \
  -d '{"text": "   ", "author": "demo@inkprint.dev"}'
```

**What to show:** `422`. Whitespace-only text canonicalizes to zero bytes; signing
that would hand out certificates that all share the hash of the empty string and
prove nothing. The signer refuses empty input as well, so the guard holds even if
a caller bypasses the HTTP layer.

## Talking points

- "Every certificate is a C2PA v2.2 content credential with an Ed25519 signature, validated against a committed JSON Schema before it is stored — certificates and dossier envelopes each against their own schema."
- "The dual fingerprint — hard binding for exact match, soft binding for paraphrases — is what makes this more than a hash. `/verify` reports what the manifest binds (signature + hash); `/diff` and `/verify/batch` are where the soft binding is compared."
- "The leak scanner queries real public indices: Common Crawl, HuggingFace, The Stack — as a background job with SSE progress and a 7-day result cache."
- "BUSL-1.1 because a copyright protection tool should not be trivially rebranded."
- "The EU AI Act's August 2026 detectability deadline is the policy hook."
