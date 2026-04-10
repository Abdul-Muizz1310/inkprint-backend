# 02 — Manifest (C2PA v2.2)

## Goal

Build a C2PA v2.2-aligned content credential manifest for each certificate. The manifest is a JSON-LD document following the C2PA Content Credentials schema. Every generated manifest must validate against a committed JSON Schema (`src/inkprint/provenance/c2pa_schema.json`). This is not a certified C2PA implementation (requires membership) but the output is spec-compliant.

## Module

`src/inkprint/provenance/manifest.py`

## Inputs

```python
def build_manifest(
    *,
    certificate_id: UUID,
    author: str,
    content_hash: str,       # sha-256 hex
    signature_b64: str,       # Ed25519 base64
    key_id: str,
    content_length: int,
    language: str | None,
    issued_at: datetime,
) -> dict:
```

## Outputs

- `dict` — JSON-serializable manifest conforming to C2PA v2.2 schema

## Invariants

1. Manifest always contains `@context`, `version` ("2.2"), `instance_id` (URN from certificate_id).
2. `claim_generator` is `"inkprint/0.1.0"`.
3. Assertions include `c2pa.actions.v2` (action = `c2pa.created`), `c2pa.hash.data` (alg = `sha256`), and `stds.schema-org.CreativeWork`.
4. `signature` block includes `alg: "Ed25519"`, `key_id`, `value` (base64 sig), and `signed_assertions` listing which assertions are covered.
5. `digitalSourceType` field is set to `http://cv.iptc.org/newscodes/digitalsourcetype/humanEdits`.
6. Every manifest validates against the committed C2PA JSON Schema.
7. `legal_notice` field is present in the manifest with disclaimer text.

## Test cases

### Happy path
- [ ] `TC-M-01`: `build_manifest()` with valid inputs returns a dict with all required top-level keys.
- [ ] `TC-M-02`: Generated manifest validates against `c2pa_schema.json` (jsonschema).
- [ ] `TC-M-03`: `instance_id` matches `urn:uuid:{certificate_id}`.
- [ ] `TC-M-04`: `claim_generator` is `"inkprint/0.1.0"`.
- [ ] `TC-M-05`: `c2pa.hash.data` assertion contains the correct hash value.
- [ ] `TC-M-06`: `stds.schema-org.CreativeWork` assertion contains the correct author and date.
- [ ] `TC-M-07`: `signature.value` matches the provided `signature_b64`.

### Edge cases
- [ ] `TC-M-08`: `language=None` produces `"und"` in the manifest.
- [ ] `TC-M-09`: Very long author string (500 chars) does not break schema validation.
- [ ] `TC-M-10`: `issued_at` with timezone info serializes to ISO 8601 with offset.
- [ ] `TC-M-11`: `issued_at` as UTC serializes with `+00:00` or `Z`.

### Failure cases
- [ ] `TC-M-12`: Missing required field (e.g., `content_hash=""`) raises `ValueError` before building.
- [ ] `TC-M-13`: Invalid `certificate_id` (not a UUID) raises `TypeError`.
- [ ] `TC-M-14`: Tampered manifest (change hash after build) fails schema validation.

### Schema validation
- [ ] `TC-M-15`: C2PA JSON Schema file exists at expected path and is valid JSON.
- [ ] `TC-M-16`: A hand-crafted invalid manifest (missing `@context`) fails validation.

## Acceptance criteria

- [ ] All generated manifests validate against the committed C2PA JSON Schema.
- [ ] Manifest structure matches the exact template from the authoritative spec.
- [ ] `legal_notice` field is present.
- [ ] All test cases pass.
