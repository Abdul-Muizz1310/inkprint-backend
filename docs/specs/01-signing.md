# 01 — Signing

## Goal

Ed25519 sign/verify roundtrip over canonicalized text. The signer produces a base64-encoded signature; the verifier checks it against the public key and canonical bytes. Keys are loaded from environment variables (base64-encoded PEM).

## Modules

- `src/inkprint/provenance/signer.py` — sign and verify functions
- `src/inkprint/core/keys.py` — load Ed25519 keypair from env

## Inputs

### `sign(canonical_bytes: bytes, private_key: Ed25519PrivateKey) -> str`
- `canonical_bytes` — output of `canonicalize()`
- `private_key` — Ed25519 private key object

### `verify(canonical_bytes: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool`
- `canonical_bytes` — output of `canonicalize()`
- `signature_b64` — base64-encoded Ed25519 signature
- `public_key` — Ed25519 public key object

### `load_signing_keys() -> tuple[Ed25519PrivateKey, Ed25519PublicKey, str]`
- Reads `INKPRINT_SIGNING_KEY_PRIVATE`, `INKPRINT_SIGNING_KEY_PUBLIC`, `INKPRINT_KEY_ID` from env
- Returns (private_key, public_key, key_id)

## Outputs

- `sign()` returns base64-encoded signature string
- `verify()` returns `True` if valid, `False` if invalid (never raises on bad signature)
- `load_signing_keys()` returns the keypair + key_id

## Invariants

1. `verify(data, sign(data, priv), pub)` is always `True` for a matching keypair.
2. `verify(tampered_data, sign(data, priv), pub)` is always `False`.
3. `verify(data, sign(data, wrong_priv), pub)` is always `False`.
4. Private key bytes are never logged, serialized to JSON, or included in any response.
5. Key ID is derived as first 16 chars of `base64(sha256(public_key_der))` — stable and reveals nothing.

## Test cases

### Happy path
- [ ] `TC-S-01`: Sign then verify with matching keypair returns `True`.
- [ ] `TC-S-02`: Signature is a valid base64 string of expected length (88 chars for 64-byte Ed25519 sig).
- [ ] `TC-S-03`: Same input + same key produces the same signature (Ed25519 is deterministic).
- [ ] `TC-S-04`: `load_signing_keys()` with valid env vars returns usable key objects.

### Edge cases
- [ ] `TC-S-05`: Sign empty bytes (`b""`) succeeds and verifies.
- [ ] `TC-S-06`: Sign very large input (500 KB) succeeds and verifies.
- [ ] `TC-S-07`: Key ID derivation is stable across multiple calls.

### Failure cases
- [ ] `TC-S-08`: Verify with tampered data returns `False`.
- [ ] `TC-S-09`: Verify with wrong public key returns `False`.
- [ ] `TC-S-10`: Verify with corrupted signature (flip one character) returns `False`.
- [ ] `TC-S-11`: Verify with empty signature string returns `False`.
- [ ] `TC-S-12`: `load_signing_keys()` with missing env vars raises a clear startup error.
- [ ] `TC-S-13`: `load_signing_keys()` with malformed base64 raises a clear error.

## Acceptance criteria

- [ ] Roundtrip sign/verify works for all test inputs.
- [ ] Tampered inputs never pass verification.
- [ ] Private key never appears in logs or API responses.
- [ ] Key loading fails fast at startup if env vars are missing/malformed.
