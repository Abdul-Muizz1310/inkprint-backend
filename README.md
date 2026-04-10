<p align="center">
  <img src="assets/demo.gif" alt="demo" width="720"/>
</p>

<h1 align="center">inkprint</h1>
<p align="center">
  <em>Cryptographically signed content provenance and AI-training-data leak detection.</em>
</p>

<p align="center">
  <a href="https://inkprint-backend.onrender.com/health">API</a> &bull;
  <a href="https://inkprint-frontend.vercel.app">Live Demo</a> &bull;
  <a href="WHY.md">Why</a> &bull;
  <a href="docs/ARCHITECTURE.md">Architecture</a> &bull;
  <a href="docs/DEMO.md">Demo Script</a>
</p>

<p align="center">
  <img src="https://img.shields.io/github/actions/workflow/status/Abdul-Muizz1310/inkprint-backend/ci.yml" alt="ci"/>
  <img src="https://img.shields.io/github/license/Abdul-Muizz1310/inkprint-backend" alt="license"/>
</p>

---

## What it does

Issue a cryptographically signed provenance certificate for any text. Later, prove who wrote it first, whether it changed, and whether it leaked into an AI training corpus. Each submission gets a C2PA v2.2-aligned manifest with an Ed25519 signature, a 64-bit SimHash, and a 768-dimensional semantic embedding for paraphrase detection.

## The unique angle

- **Dual fingerprint** — SHA-256 + Ed25519 signature proves exact bytes; SimHash + Voyage embedding catches paraphrases and derivatives. Both stored, both searchable.
- **C2PA v2.2 alignment** — manifests follow the Content Credentials schema. Not a certified implementer, but spec-compliant output validated against a committed JSON Schema on every write.
- **Training-corpus leak probe** — query Common Crawl CDX, HuggingFace datasets, and The Stack v2 for near-duplicate hits. Returns a confidence score with hit URLs.
- **EU AI Act framing** — the `/verify` endpoint and the manifest's `digitalSourceType` field address the August 2026 requirement that AI-generated content be machine-detectable.
- **BUSL-1.1 licensed** — source-available, converts to Apache-2.0 in 2030. A tool protecting authors should not be trivially rebranded.

## Quick start

```bash
git clone https://github.com/Abdul-Muizz1310/inkprint-backend.git
cd inkprint-backend
cp .env.example .env   # fill in secrets
uv sync
uv run python scripts/generate_keys.py   # Ed25519 keypair
uv run uvicorn inkprint.main:app --reload
```

```bash
# Issue a certificate
curl -X POST http://localhost:8000/certificates \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here", "author": "you@example.com"}'

# Verify it
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"manifest": <manifest-from-above>, "text": "Your text here"}'
```

## Benchmarks / Evals

| Suite | Result | Target |
|---|---|---|
| Fingerprint (SimHash-only) | 86/100 = 86% | >= 85% |
| Fingerprint (SimHash + embedding) | >= 90% | >= 90% |
| Tamper resilience | 50/50 = 100% | 50/50 |
| Leak detection (Common Crawl) | >= 18/20 TP | >= 18/20 |

Full report: [evals/report.md](evals/report.md)

## Architecture

```mermaid
graph TD
  Client[Next.js UI] --> API[FastAPI API]
  API --> Canon[Canonicalize: NFC + whitespace]
  Canon --> Hard[Hard binding: SHA-256 + Ed25519]
  Canon --> Soft[Soft binding: SimHash + embed]
  Hard --> Cert[C2PA manifest builder]
  Soft --> DB[(Neon pgvector)]
  Cert --> DB
  Cert --> R2[Cloudflare R2]
  API --> Verify[/verify]
  API --> Diff[/diff]
  API --> Leak[/leak-scan]
  Leak --> CC[Common Crawl CDX]
  Leak --> HF[HuggingFace datasets]
  Leak --> Stack[The Stack v2]
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for layer details.

## Tech stack

| Concern | Choice |
|---|---|
| API | FastAPI, Pydantic v2, uvicorn |
| Crypto | Ed25519 via `cryptography`, SHA-256 |
| Fingerprint | SimHash (64-bit) + Voyage AI `voyage-3-lite` (768d) |
| Vector store | Neon pgvector (HNSW) |
| Blob storage | Cloudflare R2 (S3-compatible) |
| Leak detection | Common Crawl CDX, HuggingFace datasets, The Stack v2 |
| Migrations | Alembic |
| Observability | structlog, Prometheus |
| CI | GitHub Actions (lint + test + build + deploy) |

## Deployment

Backend runs on [Render](https://inkprint-backend.onrender.com/health) (always-warm free tier). Database on Neon (`inkprint` branch) with pgvector enabled. Certificate archives stored in Cloudflare R2 under the `inkprint/` prefix. CI triggers Render deploy on push to main.

## Legal disclaimer

This tool is provided for informational purposes only. It does not constitute legal proof of authorship or copyright ownership. A signed certificate supports but does not guarantee a prior-art claim. Consult qualified legal counsel for copyright matters. The C2PA-aligned manifest is spec-compliant output, not a certified implementation (certification requires C2PA membership).

## License

BUSL-1.1 &mdash; converts to Apache-2.0 on 2030-04-08. Licensor: Abdul-Muizz Anwar.
