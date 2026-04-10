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

## Talking points

- "Every certificate is a C2PA v2.2 content credential with an Ed25519 signature."
- "The dual fingerprint — hard binding for exact match, soft binding for paraphrases — is what makes this more than a hash."
- "The leak scanner queries real public indices: Common Crawl, HuggingFace, The Stack."
- "BUSL-1.1 because a copyright protection tool should not be trivially rebranded."
- "The EU AI Act's August 2026 detectability deadline is the policy hook."
