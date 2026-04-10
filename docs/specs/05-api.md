# 05 — API

## Goal

Define the exact HTTP routes, request/response schemas, status codes, and middleware for the inkprint backend. All routes follow MVC layering: routers delegate to services, services orchestrate domain logic, repositories handle persistence.

## Modules

- `src/inkprint/api/routers/certificates.py`
- `src/inkprint/api/routers/verify.py`
- `src/inkprint/api/routers/diff.py`
- `src/inkprint/api/routers/leak.py`
- `src/inkprint/api/routers/search.py`
- `src/inkprint/platform/health.py`
- `src/inkprint/platform/middleware.py`
- `src/inkprint/main.py`

## Routes

```
POST   /certificates                  201 → Certificate
GET    /certificates/{id}             200 → Certificate
GET    /certificates/{id}/manifest    200 → C2PA manifest JSON
GET    /certificates/{id}/qr          200 → image/png
GET    /certificates/{id}/download    200 → original text (from R2)
POST   /verify                        200 → VerifyResult
POST   /diff                          200 → DiffResult
POST   /leak-scan                     202 → LeakScanJob (async)
GET    /leak-scan/{id}                200 → LeakScanResult (poll)
GET    /leak-scan/{id}/stream         200 → SSE (text/event-stream)
GET    /search?text=...&mode=...      200 → CertificateList
GET    /public-key.pem                200 → text/plain
GET    /health                        200 → HealthResponse
GET    /version                       200 → {commit_sha}
GET    /metrics                       200 → Prometheus text
```

## Request/Response schemas (Pydantic)

### `POST /certificates`
```
Body: { text: str, author: str, metadata?: dict }
Response 201: {
  id: uuid, author: str, content_hash: str, simhash: int,
  content_len: int, language: str|null, issued_at: datetime,
  signature: str, manifest: dict, storage_key: str|null
}
```

### `POST /verify`
```
Body: { manifest: dict, text?: str }
Response 200: {
  valid: bool,
  checks: { signature: bool, hash: bool, timestamp: bool },
  warnings: [str]
}
```

### `POST /diff`
```
Body: { parent_id: uuid, text: str }
Response 200: {
  hamming: int, cosine: float, verdict: str,
  overlap_pct: int, changed_spans: [{start, end, type}]
}
```

### `POST /leak-scan`
```
Body: { certificate_id: uuid, corpora?: [str] }
Response 202: { scan_id: uuid, status: "pending" }
```

### `GET /search`
```
Query: text (required), mode ("semantic"|"exact", default "semantic")
Response 200: { results: [Certificate], total: int }
```

## Middleware (platform module)

- `X-Request-Id`: generate UUID if absent, echo in response, inject into structlog context.
- `X-Platform-Token`: JWT validator (bastion integration). In `DEMO_MODE=true`, accept any token with warning log.
- CORS: allowlist `inkprint-frontend.vercel.app`, `bastion.vercel.app`, `localhost:3000`.
- `MAX_TEXT_BYTES` enforced in Pydantic schema validators, not just at middleware.

## Test cases

### Certificates
- [ ] `TC-A-01`: `POST /certificates` with valid body returns 201 with all required fields.
- [ ] `TC-A-02`: `POST /certificates` with missing `text` returns 422.
- [ ] `TC-A-03`: `POST /certificates` with text > MAX_TEXT_BYTES returns 413.
- [ ] `TC-A-04`: `POST /certificates` with empty `author` returns 422.
- [ ] `TC-A-05`: `GET /certificates/{id}` for existing cert returns 200.
- [ ] `TC-A-06`: `GET /certificates/{id}` for non-existent ID returns 404.
- [ ] `TC-A-07`: `GET /certificates/{id}/manifest` returns valid C2PA JSON.
- [ ] `TC-A-08`: `GET /certificates/{id}/qr` returns `image/png` with content.
- [ ] `TC-A-09`: `GET /certificates/{id}/download` returns original text.

### Verify
- [ ] `TC-A-10`: `POST /verify` with valid manifest + matching text returns `{valid: true}`.
- [ ] `TC-A-11`: `POST /verify` with tampered manifest returns `{valid: false}`.
- [ ] `TC-A-12`: `POST /verify` with manifest only (no text) verifies signature structure only.
- [ ] `TC-A-13`: `POST /verify` with empty body returns 422.

### Diff
- [ ] `TC-A-14`: `POST /diff` with existing parent_id and modified text returns verdict + spans.
- [ ] `TC-A-15`: `POST /diff` with non-existent parent_id returns 404.
- [ ] `TC-A-16`: `POST /diff` with identical text returns verdict `"identical"`.

### Leak scan
- [ ] `TC-A-17`: `POST /leak-scan` returns 202 with scan_id.
- [ ] `TC-A-18`: `GET /leak-scan/{id}` returns current scan status/results.
- [ ] `TC-A-19`: `GET /leak-scan/{id}/stream` returns SSE content type.
- [ ] `TC-A-20`: `POST /leak-scan` with non-existent certificate_id returns 404.

### Search
- [ ] `TC-A-21`: `GET /search?text=hello&mode=semantic` returns results ordered by similarity.
- [ ] `TC-A-22`: `GET /search?text=hello&mode=exact` returns exact hash matches.
- [ ] `TC-A-23`: `GET /search` without `text` param returns 422.

### Platform
- [ ] `TC-A-24`: `GET /health` returns 200 with `{status: "ok", version, db}`.
- [ ] `TC-A-25`: `GET /public-key.pem` returns PEM-encoded Ed25519 public key.
- [ ] `TC-A-26`: Response includes `X-Request-Id` header.
- [ ] `TC-A-27`: CORS preflight for allowed origin succeeds.
- [ ] `TC-A-28`: CORS preflight for disallowed origin is rejected.

### Security
- [ ] `TC-A-29`: Non-UUID path parameter returns 422, not 500.
- [ ] `TC-A-30`: Request body > 1 MB is rejected (FastAPI default + explicit limit).

## Acceptance criteria

- [ ] All routes from the spec are implemented and return correct status codes.
- [ ] Pydantic models enforce all input constraints.
- [ ] MVC layering: routers never touch DB directly.
- [ ] Platform middleware installed (request ID, CORS, JWT validator).
- [ ] All test cases pass.
