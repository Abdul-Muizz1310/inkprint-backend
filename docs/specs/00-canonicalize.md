# 00 — Canonicalize

## Goal

Provide a single, deterministic function that converts arbitrary text into canonical bytes for hashing and signing. Every path that produces bytes-for-signing or bytes-for-verification must go through `canonicalize()`. This is the biggest source of verify failures — if two callers produce different byte sequences from the same logical text, signatures will not match.

## Module

`src/inkprint/provenance/canonicalize.py`

## Inputs

- `text: str` — arbitrary Unicode string (may contain mixed whitespace, combining characters, BOM, zero-width joiners, etc.)

## Outputs

- `bytes` — deterministic UTF-8 encoded byte sequence

## Invariants

1. **NFC normalization** — all Unicode is normalized to NFC before any other processing.
2. **Whitespace collapse** — all contiguous whitespace (spaces, tabs, newlines, NBSP, etc.) is collapsed to a single ASCII space.
3. **Strip** — leading and trailing whitespace is removed after collapse.
4. **UTF-8 encode** — the resulting string is encoded to UTF-8 bytes.
5. **Idempotency** — `canonicalize(canonicalize(text).decode("utf-8")) == canonicalize(text)`.
6. **No side effects** — pure function, no I/O.

## Test cases

### Happy path
- [ ] `TC-C-01`: ASCII text with single spaces passes through unchanged (after encode).
- [ ] `TC-C-02`: Text with tabs, newlines, and multiple spaces collapses to single spaces.
- [ ] `TC-C-03`: Leading/trailing whitespace is stripped.
- [ ] `TC-C-04`: Unicode combining characters (e.g., `e\u0301` = e + combining acute) are normalized to precomposed form (`\u00e9`).
- [ ] `TC-C-05`: Non-breaking space (`\u00a0`) is collapsed like regular whitespace.

### Edge cases
- [ ] `TC-C-06`: Empty string returns `b""`.
- [ ] `TC-C-07`: Whitespace-only string returns `b""`.
- [ ] `TC-C-08`: Single character returns that character's UTF-8 bytes.
- [ ] `TC-C-09`: BOM (`\ufeff`) at start is preserved after NFC (NFC does not strip BOM). Decide: strip BOM explicitly? If yes, document.
- [ ] `TC-C-10`: Zero-width joiner (`\u200d`) and zero-width space (`\u200b`) — decide treatment. If kept, document; if stripped, add to normalize step.
- [ ] `TC-C-11`: Very long text (500 KB, the `MAX_TEXT_BYTES` boundary) produces output without error.
- [ ] `TC-C-12`: Idempotency — `canonicalize(canonicalize(text).decode()) == canonicalize(text)` for a corpus of 20 diverse inputs.

### Failure cases
- [ ] `TC-C-13`: `None` input raises `TypeError` (not silently returns empty).
- [ ] `TC-C-14`: Non-string input (e.g., `int`, `bytes`) raises `TypeError`.

## Acceptance criteria

- [ ] `canonicalize()` is the sole path for producing signing/verification bytes in the entire codebase.
- [ ] All test cases above pass.
- [ ] Function is pure — no global state, no I/O, no config dependency.
