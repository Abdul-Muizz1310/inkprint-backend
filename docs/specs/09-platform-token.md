# 09 — Platform token (contract v2)

## Goal

inkprint's copy of the workspace platform contract v2 (`docs/specs/platform-contract-v2.md` in the
workspace meta-repo; decision DR-0033). Every caller of a non-public route proves itself with an
EdDSA JWT minted by **bastion** or by **inkprint-frontend** (DR-0030: the frontend's server proxies
browser calls and signs each one). Verification surfaces stay public so anyone can check a
certificate without asking us.

This replaces the v1 middleware, which failed **open** with no key configured, bypassed everything in
`DEMO_MODE` (default `true`), checked neither `aud` nor `iss`, and read `os.environ` directly, so
`Settings.bastion_public_key_url` was ignored.

## Modules

| Concern | Module |
|---|---|
| Public-route policy (pure) | `src/inkprint/platform/public_routes.py` |
| Token verification (pure) | `src/inkprint/platform/token_verifier.py` |
| Trusted-key resolution (env + cached URL fetch) | `src/inkprint/platform/trusted_keys.py` |
| Middleware (imperative shell) | `src/inkprint/platform/platform_token.py` |
| Rate-limit identity | `src/inkprint/platform/rate_limit.py` |
| CORS and middleware order | `src/inkprint/platform/middleware.py`, `src/inkprint/main.py` |
| Settings | `src/inkprint/core/config.py` |

## 1. Configuration (Settings, never `os.environ` directly)

| Setting (env) | Default | Meaning |
|---|---|---|
| `BASTION_SIGNING_KEY_PUBLIC` | `""` | bastion's Ed25519 key, base64 SPKI DER. Wins over the URL. |
| `BASTION_PUBLIC_KEY_URL` | `https://bastion-six.vercel.app/api/public-key` | Fetched (JSON field `publicKey`, base64 SPKI DER) when the env key is empty. Cached 1 h; a failed fetch is retried after 60 s, not on every request. |
| `INKPRINT_FRONTEND_SIGNING_KEY_PUBLIC` | `""` | inkprint-frontend's Ed25519 key, base64 SPKI DER. |
| `DEMO_MODE` | `false` | Tolerates a **missing** token only (logged). |
| `APP_ENV` | `development` | `test` is the test settings: see §3. |

Key values are parsed at the boundary: a leading byte-order mark and edge whitespace are stripped
(workspace lesson: invisible bytes in deployed env values); a value that is not strict base64 of an
Ed25519 SPKI key is logged once by **name** (never value) and treated as absent. The URL response is
parsed with a Pydantic model; anything else is a failed fetch.

## 2. Verification

The service id is the constant `"inkprint"`. A token is read from `X-Platform-Token`, else from
`Authorization: Bearer <token>`. Empty or whitespace-only values count as no token. A token is
**authenticated** iff, in order:

1. its header parses and `alg == "EdDSA"` (`none`, `HS256`, anything else ⇒ `algorithm`);
2. its signature verifies against a trusted key (none does ⇒ `signature`); the key decides the
   issuer policy, never the claim:
   - bastion's key ⇒ `iss == "bastion"` (else `issuer`);
   - the frontend key ⇒ `iss == "inkprint-frontend"` (else `issuer`) and `role == "frontend"`
     (else `role`);
   if more than one key verifies (the same key configured twice), the token is accepted when any
   verifying key's policy holds;
3. `aud == "inkprint"`, a string (missing, another id, or a list ⇒ `audience`);
4. `exp` and `iat` are integers (else `claims`), `exp + 10 > now` (else `expired`),
   `iat - 10 <= now` (else `not_yet_valid`), `0 < exp - iat <= 300` (else `lifetime`);
5. `sub` is a non-empty string (else `claims`) — rate limiting keys on it.

The rejection reason is logged at WARNING with the method and path. The token is never logged.

## 3. Request outcomes (non-public routes)

| Condition | Answer |
|---|---|
| No trusted key **source** configured, `APP_ENV != test` | `503 {"detail":"platform_auth_unconfigured"}` (fail closed), WARNING |
| No trusted key source configured, `APP_ENV == test` | proceeds (the test settings) |
| No token, `DEMO_MODE=false` | `401 {"detail":"missing_platform_token"}` |
| No token, `DEMO_MODE=true` | proceeds as anonymous, WARNING |
| Token present, sources configured but no key resolvable (bad value, fetch failed) | `503 {"detail":"platform_auth_unconfigured"}`, WARNING |
| Token present and rejected (any check) — also under `DEMO_MODE=true` | `401 {"detail":"invalid_platform_token"}`, WARNING naming the check |
| Token authenticated | proceeds; the principal `(iss, sub, role)` is attached to the request |

Only authentication: inkprint does not gate on `role` beyond the frontend-key rule above.

## 4. Public routes (never require a token; a token is ignored)

Any method: `/health`, `/version`, `/docs` (and `/docs/…`), `/redoc`, `/openapi.json`, `/metrics`.
Method-bound verification surfaces:

| Method | Path |
|---|---|
| `GET` | `/certificates/{id}`, `/certificates/{id}/manifest`, `/certificates/{id}/qr`, `/certificates/{id}/download` |
| `POST` | `/verify`, `/verify/batch` |
| `GET` | `/public-key.pem` |

Everything else needs a token — notably `POST /certificates`, `POST /certificates/batch`,
`POST /diff`, `GET /search`, `POST /leak-scan`, `GET /leak-scan/{id}`, `GET /leak-scan/{id}/stream`
and `POST /dossiers/envelope`. A path is matched exactly (`{id}` is one non-empty segment without
`/`); a trailing slash, an extra segment or another method is not public.

## 5. Rate limiting

The address below is `request.client.host`: the leftmost `X-Forwarded-For` entry, because the
container runs uvicorn with `--proxy-headers --forwarded-allow-ips '*'` (spec 05). Buckets key on:

| Caller | Bucket |
|---|---|
| authenticated with bastion's key | `"bastion:{sub}"` (the visitor pseudonym, wherever it connects from) |
| authenticated with the frontend key | `"inkprint-frontend:{address}"` — the frontend's `sub` is constant, so keying on it would put every visitor of the site in one bucket; its proxy forwards exactly one address |
| not authenticated | the bare address |

Public routes are not authenticated, so they key on the address. The token middleware runs
**before** the limiter. (Contract v2 as amended 2026-10-20; the first draft keyed every
authenticated request on `iss:sub`.)

## 6. CORS and middleware order

Outer to inner: CORS → request id → platform token → rate limit → routes. CORS outermost answers
preflights itself and decorates 401/503 answers, so a browser sees the real status. Allowed request
headers: `content-type`, `x-platform-token`, `x-request-id`, `authorization`, `last-event-id`.

## Test cases

`tests/unit/test_platform_token.py` (conformance, against the real app built with explicit Settings),
`tests/unit/test_token_verifier.py`, `tests/unit/test_trusted_keys.py`,
`tests/unit/test_public_routes.py`, `tests/unit/test_rate_limit.py`.

### Conformance (contract §3)

- **PT-1** valid bastion token, `aud = "inkprint"` ⇒ authenticated (and the route runs: `POST
  /certificates` answers 201).
- **PT-2** `aud` = another service's id (`paper-trail`, `magpie`, `inkthread`, `slowquery`,
  `feathers-demo`) ⇒ 401 invalid.
- **PT-3** `aud` missing ⇒ 401 invalid; `aud` a list (even `["inkprint"]`) ⇒ 401 invalid.
- **PT-4** `iss = "bastion"` signed with the frontend key ⇒ 401 invalid; `iss =
  "inkprint-frontend"` signed with bastion's key ⇒ 401 invalid.
- **PT-5** frontend-key token with `role != "frontend"` (or no role) ⇒ 401 invalid.
- **PT-6** expired 5 s ago ⇒ authenticated; expired 15 s ago ⇒ 401 invalid.
- **PT-7** `iat` 5 s in the future ⇒ authenticated; 15 s ⇒ 401 invalid.
- **PT-8** `alg = none` or `HS256` (keyed with the public key's bytes) ⇒ 401 invalid.
- **PT-9** tampered payload (or signature) ⇒ 401 invalid.
- **PT-10** no token, `DEMO_MODE=false` ⇒ 401 missing; no token, `DEMO_MODE=true` ⇒ proceeds, WARNING
  logged.
- **PT-11** present-but-invalid token with `DEMO_MODE=true` ⇒ still 401 invalid.
- **PT-12** no trusted key configured (non-test settings) ⇒ 503 on a protected route (with or
  without a token), 200 on `/health`.
- **PT-13** every public route answers without a token (not 401/503), with no key configured and
  with keys configured; every protected route listed in §4 answers 401 without a token.
- **PT-14** the rate-limit key is `bastion:{sub}` for a bastion token (two subs from one address get
  two buckets; one sub from two addresses shares one) and `inkprint-frontend:{address}` for a
  frontend token (two visitors through the frontend — one socket peer, distinct leftmost
  `X-Forwarded-For` — land in different buckets; the same visitor twice shares one).

### Further pass cases

- **PT-15** a valid frontend token (`iss "inkprint-frontend"`, `role "frontend"`) ⇒ authenticated.
- **PT-16** the token is read from `Authorization: Bearer` when `X-Platform-Token` is absent;
  `X-Platform-Token` wins when both are present.
- **PT-17** bastion's key from `BASTION_PUBLIC_KEY_URL` (Settings, not `os.environ`): fetched once,
  cached; the env key wins over the URL without a fetch.
- **PT-18** keys with a BOM and a trailing CRLF parse.
- **PT-19** the CORS preflight from an allowed origin allows `x-platform-token`; a 401 carries
  `access-control-allow-origin` for an allowed origin.
- **PT-20** `DEMO_MODE` defaults to `false`; `Settings` exposes the three key settings.

### Further failure cases (negative space)

- **PT-21** `exp - iat > 300` ⇒ 401; `exp <= iat` ⇒ 401; `exp`/`iat` missing or not integers (a
  string, a float, a bool) ⇒ 401.
- **PT-22** `sub` missing or empty ⇒ 401.
- **PT-23** a token that is not three base64url parts, or whose payload is not a JSON object ⇒ 401.
- **PT-24** a malformed key value (not base64, an RSA key, an X25519 key) is ignored with one
  WARNING naming the variable, never its value; with no other key ⇒ 503 for a present token.
- **PT-25** a failed URL fetch (network error, non-2xx, a body without `publicKey`) ⇒ no bastion key,
  WARNING; a second request within 60 s does not refetch.
- **PT-26** the public-route policy refuses near misses: `POST /certificates`, `POST
  /certificates/batch`, `GET /certificates/{id}/qr/x`, `GET /certificates/`, `GET /verify`, `PUT
  /verify`, `/healthz`, `/docsx`.
- **PT-27** the rejection WARNING names the reason and never contains the token.
