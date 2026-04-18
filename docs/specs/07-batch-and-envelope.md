# 07 — Batch & Dossier Envelope

## Goal

Add three new endpoints to the inkprint backend that support the bastion "dossier" flow:

1. `POST /certificates/batch` — atomic bulk issuance of N certificates in one request.
2. `POST /dossiers/envelope` — sign a C2PA-aligned *dossier envelope* manifest over a bundle of evidence certificate IDs, a debate transcript hash, and a perf receipt hash.
3. `POST /verify/batch` — batch verify N certificate signatures + fingerprints in one request (used by the dossier re-verify flow).

The three endpoints share one design principle: **the request is the transactional unit**. Batch certificate issuance is all-or-nothing. Envelope signing either finds every referenced certificate or rejects the entire bundle. Batch verify accepts shape-valid input and produces per-item results (individual unknown IDs are reported inline rather than failing the whole envelope).

## Modules

New:
- `src/inkprint/api/routers/batch.py`
- `src/inkprint/api/routers/dossiers.py`
- `src/inkprint/services/batch_service.py`
- `src/inkprint/services/envelope_service.py`
- `src/inkprint/provenance/envelope_builder.py`
- `src/inkprint/schemas/batch.py`
- `src/inkprint/schemas/envelope.py`
- `alembic/versions/0002_dossier_envelopes.py`

Modified:
- `src/inkprint/main.py` (register new routers)

## Layering

```
routers/batch.py        → services/batch_service.py   → services/certificate_service.py (existing)
routers/dossiers.py     → services/envelope_service.py → provenance/envelope_builder.py (pure)
                                                       → provenance/signer.py (existing)
                                                       → services/certificate_service.py (existing)
```

- **Routers are thin** — shape validation via Pydantic, pull app state (keys), delegate to services, map service errors to HTTP status codes.
- **Services orchestrate** — they call the pure domain layer (provenance/envelope_builder, signer, canonicalize) plus the existing certificate store.
- **`envelope_builder.py` is pure** — no I/O, no signing, no DB. Given inputs, returns a canonical-byte representation AND a C2PA-aligned manifest dict. 100% unit-testable without fixtures.

## Endpoints

### `POST /certificates/batch`

Issue N certificates atomically.

**Request**
```json
{
  "items": [
    {
      "text": "string (1..1_000_000 chars)",
      "author": "string (min 1 char)",
      "metadata": { "k": "v" }    // optional
    }
  ]                               // list length: 1..50
}
```

**Response 200**
```json
{
  "certificates": [
    {
      "certificate_id": "uuid",
      "manifest": { ... C2PA v2.2 manifest ... },
      "fingerprints": {
        "sha256": "hex...",
        "simhash": 1234567890,
        "embedding_id": "uuid"    // per-certificate handle for the stored embedding
      }
    }
  ]
}
```

Items in the response appear in the **same order as the request**.

**Atomicity**

The endpoint issues `len(items)` certificates inside a single logical transaction. If any step fails — shape validation, embedding API failure, manifest schema validation — no certificates from this request are retained. In the current in-memory-store implementation, this means the service builds records into a local list first and only commits them to the store on full success. In a database-backed implementation the same logic uses `session.begin()`.

**Failure modes**

| Condition | Status | Body |
|---|---|---|
| Empty `items` list | 422 | Pydantic validation error |
| > 50 items | 422 | Pydantic validation error |
| Item with empty text | 422 | Pydantic validation error |
| Item with text > 1_000_000 chars | 422 | Pydantic validation error |
| Embedding API failure mid-batch | 503 | `{"detail": "Embedding service unavailable"}` — no partial commit |

### `POST /dossiers/envelope`

Sign a dossier-envelope manifest over a bundle.

**Request**
```json
{
  "dossier_id": "uuid",
  "evidence_cert_ids": ["uuid", "..."],    // length 1..50
  "debate_transcript_hash": "64-char lower hex",
  "perf_receipt_hash": "64-char lower hex",
  "metadata": { "k": "v" }                 // optional
}
```

**Response 200**
```json
{
  "envelope_id": "uuid",            // == dossier_id
  "envelope_manifest": { ... C2PA manifest ... },
  "envelope_signature": "base64",
  "created_at": "iso8601"
}
```

**Behaviour**

1. The service verifies **every** `evidence_cert_id` exists in the certificate store. The first missing ID triggers a 422 with body `{"detail": "Unknown certificate: <id>"}`.
2. The pure builder canonicalizes a bundle JSON containing `{ dossier_id, evidence_cert_ids, debate_transcript_hash, perf_receipt_hash, metadata, issued_at }`. Canonicalization is: sort keys, UTF-8 encode, `ensure_ascii=False`, no extra whitespace. The same inputs always produce the same bytes.
3. The service SHA-256 hashes the canonical bytes and signs with the existing Ed25519 private key via `provenance/signer.sign`.
4. The service calls the pure builder a second time to assemble a C2PA-aligned manifest:
   - `claim_generator = "bastion/dossier-envelope"`
   - `assertions`:
     - one `c2pa.ingredient.v2` assertion per `evidence_cert_id` with `url: "/certificates/{id}/manifest"`
     - one `bastion.debate_transcript_hash` assertion with the hex hash
     - one `bastion.perf_receipt_hash` assertion with the hex hash
   - `signature.value` = the base64 Ed25519 signature produced in step 3.
5. The service writes a row to `dossier_envelopes` and returns the response. The row uses `dossier_id` as its primary key.

**Idempotency**

Re-submitting the same `dossier_id` with the **same inputs** returns 200 with the original `envelope_id`, manifest, and signature (idempotent read-back from storage). Re-submitting the same `dossier_id` with **different inputs** returns 409 `{"detail": "Dossier already envelope-signed with different bundle"}`.

**Failure modes**

| Condition | Status | Body |
|---|---|---|
| Unknown evidence cert id | 422 | `{"detail": "Unknown certificate: <id>"}` |
| Empty `evidence_cert_ids` | 422 | Pydantic validation |
| > 50 evidence ids | 422 | Pydantic validation |
| `debate_transcript_hash` not 64 hex chars | 422 | Pydantic validation |
| `perf_receipt_hash` not 64 hex chars | 422 | Pydantic validation |
| Duplicate dossier_id with different bundle | 409 | see above |

### `POST /verify/batch`

Batch signature + fingerprint verification.

**Request**
```json
{
  "items": [
    {
      "certificate_id": "uuid",
      "text": "string (optional)"
    }
  ]                                 // length 1..50
}
```

**Response 200**
```json
{
  "results": [
    {
      "certificate_id": "uuid",
      "valid": true,
      "checks": {
        "signature": true,
        "hash": true,
        "simhash": true,            // only present when text supplied
        "embedding": true           // only present when text supplied
      },
      "reason": null
    }
  ]
}
```

Results preserve request order.

**Per-item behaviour**

- `text` omitted → verify signature and hash against the stored manifest. `simhash` / `embedding` keys are absent.
- `text` supplied → additionally re-derive SimHash + embedding from `text`, compare against stored fingerprints. `simhash` and `embedding` keys are booleans.
- `certificate_id` does not resolve → item emits `{ valid: false, checks: {}, reason: "unknown_certificate" }`. Other items continue.

**Failure modes**

Only envelope-shape errors (empty list, >50 items, malformed UUID, text > 1_000_000 chars) produce 422. Everything else is per-item.

## Pydantic schemas

All request/response models are:
- `model_config = ConfigDict(extra="forbid", frozen=True)`.
- UUIDs typed as `UUID` (Pydantic v2 auto-converts strings).
- Lengths enforced by `Field(min_length=..., max_length=...)`.
- Hex hashes typed with `pattern=r"^[a-f0-9]{64}$"`.
- Frozen so that invariant violations can't be introduced by mutation.

`src/inkprint/schemas/batch.py`:
- `BatchCertificateItem`
- `BatchCertificateCreateRequest`
- `BatchFingerprints`
- `BatchCertificateRecord`
- `BatchCertificateResponse`
- `BatchVerifyItem`
- `BatchVerifyRequest`
- `BatchVerifyItemResult`
- `BatchVerifyResponse`

`src/inkprint/schemas/envelope.py`:
- `EnvelopeRequest`
- `EnvelopeResponse`

## `dossier_envelopes` table

Alembic revision `0002` creates:

| Column | Type | Constraints |
|---|---|---|
| `dossier_id` | UUID | PK |
| `envelope_manifest` | JSONB | NOT NULL |
| `envelope_signature` | TEXT | NOT NULL |
| `evidence_cert_ids` | UUID[] | NOT NULL |
| `debate_transcript_hash` | TEXT | NOT NULL |
| `perf_receipt_hash` | TEXT | NOT NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

The current codebase uses an in-memory store for tests; the migration file is the source of truth for the persistent schema. The envelope service stores records in an in-memory dict keyed by `dossier_id` (mirroring the pattern used by `certificate_service` and `leak_service`) so that unit and integration tests work without a live Postgres instance.

## Test cases

### `POST /certificates/batch`

| ID | Test |
|---|---|
| `TC-B-01` | Batch of 3 items → 200 with 3 certificates in input order, all unique IDs. |
| `TC-B-02` | Each returned certificate carries `fingerprints.sha256`, `fingerprints.simhash`, `fingerprints.embedding_id`. |
| `TC-B-03` | Single-item batch (len 1) works. |
| `TC-B-04` | 50-item batch works. |
| `TC-B-05` | Per-item metadata is reflected in the per-item manifest (visible via stored cert). |
| `TC-B-06` | Empty `items` list → 422. |
| `TC-B-07` | 51-item list → 422. |
| `TC-B-08` | Item with empty text → 422. |
| `TC-B-09` | Item with text > 1_000_000 chars → 422. |
| `TC-B-10` | Embedding API failure mid-batch → 503 AND no certificates committed (store size unchanged). |

### `POST /dossiers/envelope`

| ID | Test |
|---|---|
| `TC-B-11` | Valid request with 3 existing cert IDs → 200 with manifest + signature + envelope_id. |
| `TC-B-12` | Signature verifies against the app's Ed25519 public key over the canonical bundle bytes. |
| `TC-B-13` | Envelope written to the envelope store and retrievable by `dossier_id`. |
| `TC-B-14` | Canonicalization stable: same inputs → byte-identical signature across two calls to the builder. |
| `TC-B-15` | Unknown evidence cert id → 422 `{"detail": "Unknown certificate: <id>"}`. |
| `TC-B-16` | Empty `evidence_cert_ids` → 422. |
| `TC-B-17` | Malformed `debate_transcript_hash` (not 64 hex) → 422. |
| `TC-B-18` | Duplicate `dossier_id` with **different** bundle → 409. Duplicate with **same** bundle → 200 idempotent. |

### `POST /verify/batch`

| ID | Test |
|---|---|
| `TC-B-19` | 3 valid certs without text → all `valid: true` with signature + hash checks only. |
| `TC-B-20` | 1 valid cert + 1 cert with tampered text → first `valid: true`, second reports `simhash: false, embedding: false`. |
| `TC-B-21` | Unknown cert id alongside valid cert → unknown emits `valid: false, reason: "unknown_certificate"`; valid continues. |

### Pure builder (`envelope_builder.py`)

| ID | Test |
|---|---|
| `TC-B-22` | `canonical_bundle_bytes` is deterministic for identical inputs. |
| `TC-B-23` | Different metadata → different canonical bytes. |
| `TC-B-24` | `build_envelope_manifest` includes one `c2pa.ingredient.v2` assertion per evidence cert, plus the two `bastion.*_hash` assertions, and uses `claim_generator = "bastion/dossier-envelope"`. |

## Acceptance criteria

- [ ] All 24 test cases pass.
- [ ] Existing test suite (214 pass / 1 skip baseline) remains green.
- [ ] Line coverage stays at 100% for the new modules.
- [ ] `ruff check` clean.
- [ ] `mypy --strict` clean.
- [ ] Routers never touch the DB directly; the pure builder never imports DB/HTTP/signer symbols.
- [ ] Existing Ed25519 signer is reused — no new crypto primitives.
- [ ] Alembic migration `0002_dossier_envelopes` ships in `alembic/versions/`.
