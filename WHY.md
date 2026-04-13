# Why inkprint?

## The obvious version

The obvious version of a "document diff" tool is a text compare. Hash the text, store the hash, diff later. Everyone who builds one stops there: SHA-256, maybe a timestamp, a database row. No standard, no portability, no way to detect if someone paraphrased your work or fed it into a training pipeline. It answers "did these exact bytes change?" but not the question authors actually care about: "has my writing been absorbed without my consent?"

## Why I built it differently

By April 2026, the interesting question is not "what changed in this document" but "can you prove you wrote it first, and has your writing already been absorbed into a model's training data without your permission?" The EU AI Act requires AI-generated content to be detectable starting August 2026, C2PA v2.2 gave us a standard for content credentials, and Common Crawl's CDX index is free and public — but nobody has stitched these together into a single tool a person can actually use. inkprint is that stitch. Each submission gets a **dual fingerprint**: a *hard binding* (SHA-256 + Ed25519 signature wrapped in a C2PA-aligned manifest) that proves exact bytes have not been tampered with and can be independently verified by any C2PA-compatible tool, and a *soft binding* (SimHash for structural similarity + a 768-dimensional Voyage embedding for semantic proximity) that catches paraphrases, translations, and derivatives that would slip past a byte-level hash. The C2PA alignment is deliberate — rather than inventing a proprietary format, the manifest structure follows the Coalition for Content Provenance and Authenticity standard so that inkprint fingerprints are interoperable with the broader content-credentials ecosystem Adobe, Microsoft, and the BBC are building. The leak scanner then queries Common Crawl, HuggingFace datasets, and The Stack v2 to check whether your text has already surfaced in public AI training corpora. I chose BUSL-1.1 over MIT because a tool aimed at protecting authors should not itself be trivially rebranded and resold.

## What I'd change if I did it again

The in-memory store served testing well but delayed real persistence. If I started over, I would wire SQLAlchemy repositories from day one and use Testcontainers for every integration test, so the gap between "tests pass" and "production works" would be zero. I would also cache Common Crawl CDX results aggressively in Upstash — the 1 req/s rate limit is the real bottleneck for the leak scanner, and a 7-day content-hash cache would eliminate most repeated scans.
