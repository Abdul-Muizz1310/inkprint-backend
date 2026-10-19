# 08 — Storage health (R2 archival)

## Goal

Certificate archival to Cloudflare R2 is best-effort: a failed or unconfigured upload never blocks
certificate creation (`storage_key` falls back to the logical `certificates/{id}.json`). That made
failures invisible: `archive_text` swallowed them at `DEBUG`, so a dead R2 token went unnoticed in
production. This spec makes the failure loud in the logs and visible on `/health`, without making
`/health` touch the network.

## Modules

- `src/inkprint/core/storage_health.py` — pure state: the outcome of the last R2 operation.
- `src/inkprint/core/r2.py` — the R2 client; records every operation's outcome; startup probe.
- `src/inkprint/platform/health.py` — `/health` reads the recorded state.
- `src/inkprint/main.py` — the lifespan schedules the startup probe.

## Behaviour

### Status

`/health` gains `storage: "ok" | "degraded"`:

| R2 configured (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` all non-empty) | Last R2 operation | `storage` |
|---|---|---|
| no | (any) | `degraded` |
| yes | none yet | `ok` |
| yes | succeeded | `ok` |
| yes | failed | `degraded` |

`status` stays `"ok"`: the service serves certificates either way, and Render's health check reads
the HTTP status, not the body. `/health` reads only in-process state: it never builds an S3 client
and never makes a network call, however often it is probed.

### Operations that record an outcome

- `put_object` (`upload_text`, reached through `archive_text` by the single and batch paths);
- `get_object` (`download_text`);
- `list_objects_v2` (the startup probe).

`generate_presigned_url` signs locally and makes no request, so it records nothing.

### Logging

A failed operation logs at **WARNING**: the operation name, the R2 key or bucket it addressed, the
exception class, and for a botocore `ClientError` its error code (e.g. `Unauthorized`,
`AccessDenied`). Never the exception message (it can echo request URLs) and never a credential.
`archive_text` still swallows the error and returns `None` (archival stays non-fatal);
`download_text` re-raises after recording.

R2 being unconfigured is not an operation failure: archival returns `None` silently per call, and the
startup logs one WARNING that archival is disabled.

### Startup probe

Render's free instance sleeps after 15 idle minutes, so "the last operation" would otherwise reset on
every wake and report `ok` until somebody issued a certificate. When R2 is configured, the lifespan
schedules one `list_objects_v2(Bucket, Prefix="inkprint/", MaxKeys=1)` in a worker thread (object-read
permission, which an object-scoped token has; `head_bucket` needs bucket permission). It is not
awaited: a slow R2 never delays startup. The client uses short timeouts (connect 3 s, read 5 s, one
attempt) so a hung endpoint cannot pin the thread.

## Test cases

### Pass

- **SH-1** unconfigured R2 ⇒ `/health` has `storage: "degraded"`.
- **SH-2** configured, no operation yet ⇒ `ok`.
- **SH-3** configured, last operation succeeded ⇒ `ok`.
- **SH-4** configured, last operation failed ⇒ `degraded`.
- **SH-5** a failure followed by a success ⇒ `ok` (it recovers); a success followed by a failure ⇒
  `degraded`.
- **SH-6** `/health` builds no S3 client: with the client factory made to raise, 20 probes all answer
  200 with a `storage` field.
- **SH-7** the startup probe, configured: one `list_objects_v2` with `Prefix="inkprint/"` and
  `MaxKeys=1`; success ⇒ `ok`.
- **SH-8** the startup probe, unconfigured: no client is built, one WARNING says archival is disabled.
- **SH-9** composed: with R2 configured and `put_object` failing, `POST /certificates` still answers
  201 with the logical `storage_key`, and `/health` then reports `degraded`.

### Failure (negative space)

- **SH-10** a failing `put_object` logs one WARNING naming `put_object`, the key, `ClientError` and
  the error code; the record carries no secret and no exception message; `archive_text` returns
  `None`.
- **SH-11** a non-`ClientError` failure (e.g. `EndpointConnectionError`, `OSError`) logs its class
  and still degrades the status.
- **SH-12** a failing `get_object` logs a WARNING naming `get_object`, degrades the status and
  re-raises.
- **SH-13** the startup probe failing logs a WARNING naming `list_objects_v2` and degrades the status;
  it never raises out of the lifespan.
- **SH-14** an unconfigured `archive_text` logs nothing at WARNING (it is not a failure) and does not
  change the recorded outcome.
