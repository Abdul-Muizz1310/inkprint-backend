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

<!-- Fill in S6 -->

## The unique angle

<!-- Fill in S6 -->

## Quick start

```bash
git clone https://github.com/Abdul-Muizz1310/inkprint-backend.git
cd inkprint-backend
cp .env.example .env   # fill in secrets
uv sync
uv run uvicorn inkprint.main:app --reload
```

## Benchmarks / Evals

<!-- Fill in S6 -->

## Architecture

<!-- Fill in S6 — embed Mermaid or link to docs/ARCHITECTURE.md -->

## Tech stack

| Concern | Choice |
|---|---|
| API | FastAPI |
| Crypto | Ed25519 via `cryptography`, SHA-256 |
| Fingerprint | SimHash (64-bit) + Voyage AI embeddings |
| Vector store | Neon pgvector (HNSW) |
| Blob storage | Cloudflare R2 |
| Leak detection | Common Crawl CDX, HuggingFace datasets, The Stack v2 |
| Observability | structlog, Prometheus |

## Deployment

Backend runs on Render (always-warm). Database on Neon (`inkprint` branch) with pgvector. Certificate archives stored in Cloudflare R2.

## License

BUSL-1.1 &mdash; converts to Apache-2.0 on 2030-04-08.
