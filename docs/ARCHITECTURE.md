# Architecture

<!-- Fill in S6 with real Mermaid diagram -->

```mermaid
graph TD
  Client[Next.js UI] --> API[FastAPI API]
  API --> Canonicalize[Canonicalize text]
  Canonicalize --> Hard[Hard binding: SHA-256 + Ed25519]
  Canonicalize --> Soft[Soft binding: SimHash + embed]
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

## Layers

- **API** (`src/inkprint/api/`) — FastAPI routers, request/response schemas
- **Services** (`src/inkprint/services/`) — business logic orchestration
- **Provenance** (`src/inkprint/provenance/`) — canonicalization, hashing, signing, manifest building
- **Fingerprint** (`src/inkprint/fingerprint/`) — SimHash, embeddings, comparison
- **Leak** (`src/inkprint/leak/`) — corpus scanners, scoring
- **Core** (`src/inkprint/core/`) — config, DB, R2 client, key loading
- **Models** (`src/inkprint/models/`) — SQLAlchemy models
- **Schemas** (`src/inkprint/schemas/`) — Pydantic DTOs
