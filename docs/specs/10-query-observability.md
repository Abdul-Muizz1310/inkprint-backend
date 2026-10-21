# 10 — Query observability (slowquery-detective 0.2)

## Goal

bastion's dossier "measure" stage asks every service it called which queries a request caused:
`GET /_slowquery/queries?request_id=<R>` (interface I-2 of the bastion v2 rollout plan; the library's
own spec is slowquery-detective `docs/specs/07-fleet-observability.md`). inkprint installs
`slowquery-detective[fastapi,postgres]>=0.2,<0.3` so every statement a request tagged
`X-Request-Id: R` runs — in the route, its services, a background task — is counted against R and
kept in inkprint's own Postgres.

## Wiring (`src/inkprint/platform/query_observability.py`, called from `main.create_app`)

`install(app, engine, service="inkprint", store_url=…, authorize=authorize_bastion)`:

- **engine**: the process-wide engine (`core.db.get_engine()`), which every repository uses. It exists
  at install time (creating it opens no connection).
- **store_url**: the engine's own URL when it is Postgres (`postgresql…`), so the store lives in the
  service's own database; `None` otherwise (SQLite: tests and the local default), which selects the
  in-memory store. Derived from the engine rather than re-read from the environment, so the store
  and the observed queries can never point at different databases.
- **authorize**: `True` only for a request the contract-v2 middleware (spec 09) authenticated with
  **bastion's** key (`iss == "bastion"`). A frontend-key token, an anonymous `DEMO_MODE` request or
  anything else is `False` ⇒ 403. A missing or invalid token never reaches the hook: `/_slowquery` is
  not a public route, so the token middleware answers 401 (or 503 with no key configured) first.

### Middleware order (outer → inner)

CORS → slowquery's request-id tagger → Prometheus → request id → platform token → rate limit →
routes. The tagger is added after every middleware that could run a statement, so the host's own
work is attributed; CORS is added last, so it stays outermost (spec 09 §6).

### Coexistence with the migrated schema

The library creates schema `slowquery` and its six tables at startup (`CREATE … IF NOT EXISTS` under
an advisory lock). Alembic owns the default schema (`certificates`, `leak_*`, `dossier_envelopes`,
`alembic_version`) and the `vector` extension; neither touches the other. `alembic upgrade head`
after the `slowquery` schema exists is a no-op, and the store starting on a migrated pgvector
database leaves the extension and the head revision as they were.

Tests stay hermetic: `tests/conftest.py` blanks `DATABASE_URL`, so the module-level app never builds a
store against a developer's real database.

## Test cases

### Unit (in-memory store, SQLite) — `tests/unit/test_query_observability.py`

- **QO-1** `POST /certificates` with `X-Request-Id: R` and a bastion token, then
  `GET /_slowquery/queries?request_id=R` with a bastion token ⇒ 200, a row whose fingerprint inserts
  into `certificates`, `call_count >= 1`, percentiles `null`.
- **QO-2** the same read without a token ⇒ 401 `missing_platform_token`.
- **QO-3** with a frontend token ⇒ 403; anonymous under `DEMO_MODE=true` ⇒ 403.
- **QO-4** with an invalid token ⇒ 401 `invalid_platform_token`.
- **QO-5** another request id sees none of R's rows; the measure call itself adds nothing to R.
- **QO-6** `authorize_bastion`: no principal ⇒ False; frontend principal ⇒ False; bastion ⇒ True.
- **QO-7** `store_url_for`: `postgresql+asyncpg://…` and `postgresql://…` ⇒ the URL with its password;
  `sqlite+aiosqlite://…` ⇒ `None`.
- **QO-8** `create_app` on SQLite ⇒ the in-memory store; on a Postgres engine ⇒ the Postgres store
  (no connection made at install).
- **QO-9** middleware order: CORS outermost, the slowquery tagger directly inside it.
- **QO-10** `/_slowquery/queries` and `/_slowquery/queries/{id}` are not public routes (spec 09 §4).

### Integration (real Postgres, `pgvector/pgvector:pg17`) — `tests/integration/test_postgres_tier.py`

- **QO-11** on the Alembic-migrated database, with the app's lifespan running: QO-1 holds with the
  Postgres store, and the answer comes from the `slowquery.request_stats` table.
- **QO-12** schema `slowquery` holds its six tables; the `vector` extension and the Alembic head are
  unchanged; `alembic upgrade head` afterwards succeeds.
