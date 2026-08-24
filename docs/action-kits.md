# Oneiric Action Kits — Catalog

This is the canonical reference for every built-in action kit in
`oneiric.actions`. Each entry documents when to reach for the kit,
the settings/payload/result shapes, a minimal example, and known
production callers.

**Ordering:** alphabetical by `metadata.key`. **Adding a kit:** append a
new entry (don't break ordering); do the same in
`oneiric/oneiric/actions/__init__.py::builtin_action_metadata()`.

---

### `automation.trigger`

**Module**: `oneiric.actions.automation`
**Use when**: evaluating declarative automation rules against a context
to decide which downstream action(s) to fire — e.g., a router that maps
"if env == prod" → `workflow.orchestrate`, "else" → `debug.console`.
**Don't use when**: you need to actually run a recurring task on a
schedule — use `task.schedule` instead. Trigger decides *what to fire*;
schedule decides *when to fire*.

**Settings** (see `AutomationTriggerSettings` in
`oneiric/actions/automation.py`):
- `max_rules` (int, 1-200, default 20) — safety cap on rules per call.

**Payload shape**:
- `context` (Mapping) — dictionary inspected by `AutomationCondition` paths.
- `rules` (list[`AutomationRule`], required, min_length 1) — evaluated in order.
- `stop_on_first_match` (bool | None) — short-circuit override per call.

**Result shape**:
```python
{"status": "triggered" | "noop",
 "matched_rules": [{"name", "action", "payload", "condition_count"}],
 "evaluated_rules": int,
 "context": dict}
```

**Minimal example**:
```python
from oneiric.actions.automation import (
    AutomationTriggerAction,
    AutomationTriggerSettings,
)

action = AutomationTriggerAction(settings=AutomationTriggerSettings())
result = await action.execute({
    "context": {"env": "prod", "tier": "free"},
    "rules": [
        {
            "name": "free-tier",
            "action": "debug.console",
            "conditions": [
                {"field": "tier", "operator": "equals", "value": "free"}
            ],
        },
    ],
})
matched = result["matched_rules"]
```

**Adopted by**: (none yet — production candidate)

---

### `compression.encode`

**Module**: `oneiric.actions.compression`
**Use when**: compressing/decompressing short text payloads (logs,
config blobs, event bodies) for transport or storage — round-trips
through base64-wrapped zlib/bz2/lzma.
**Don't use when**: you need a streaming compressor, an archive
container (zip/tar), or to compress bytes already in a binary protocol
— those are not what this kit does.

**Settings** (see `CompressionActionSettings`):
- `algorithm` (`"zlib"` | `"bz2"` | `"lzma"`, default `"zlib"`).
- `level` (int, 0-9, default 6) — handed to the underlying algorithm.

**Payload shape**:
- `mode` (`"compress"` | `"decompress"`, default `"compress"`).
- `algorithm` (str) — overrides settings; `"zlib"`/`"bz2"`/`"lzma"`.
- `text` (str, required when `mode == "compress"`) or `data` (str, base64, required when `mode == "decompress"`).

**Result shape**:
```python
# mode == "compress"
{"mode": "compress", "algorithm": str, "data": "<base64>"}
# mode == "decompress"
{"mode": "decompress", "algorithm": str, "text": str}
```

**Minimal example**:
```python
from oneiric.actions.compression import (
    CompressionAction,
    CompressionActionSettings,
)

action = CompressionAction(settings=CompressionActionSettings(algorithm="zlib"))
result = await action.execute({"text": "hello world", "mode": "compress"})
token = result["data"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `compression.hash`

**Module**: `oneiric.actions.compression`
**Use when**: producing a deterministic, unkeyed digest of a string,
bytes, or JSON-serializable value for caching, dedup, or content
addressing — supports `sha256`/`sha512`/`blake2b` with optional salt.
**Don't use when**: you need a keyed MAC for outbound webhooks — use
`security.signature` (HMAC) instead. This kit is *unkeyed*.

**Settings** (see `HashActionSettings`):
- `algorithm` (`"sha256"` | `"sha512"` | `"blake2b"`, default `"sha256"`).
- `encoding` (`"hex"` | `"base64"`, default `"hex"`).
- `salt` (str | None) — optional prefix prepended before hashing.

**Payload shape**:
- `value` (str | bytes | JSON-serializable) — required; alternatively `text` or `data`.
- `algorithm` (str) — overrides settings.
- `encoding` (str) — overrides settings.
- `salt` (str) — overrides settings; concatenated before hashing.

**Result shape**:
```python
{"status": "hashed",
 "algorithm": str,
 "encoding": "hex" | "base64",
 "digest": str,
 "salted": bool}
```

**Minimal example**:
```python
from oneiric.actions.compression import HashAction, HashActionSettings

action = HashAction(settings=HashActionSettings(algorithm="sha256"))
result = await action.execute({"value": "user-42"})
digest = result["digest"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `compression.stream`

**Module**: `oneiric.actions.streaming_compression`
**Use when**: compressing or decompressing a *chunked* source (file
chunks, network bytes, worktree bundles >100MB) that can't be
materialized in memory before compression — yields a stream of output
bytes via a stateful chunker/decompressor.
**Don't use when**: you have a small in-memory payload (use
`compression.encode`, which returns base64 in a single envelope) or
you need an archive container (zip/tar). This kit only compresses raw
byte streams.

**Codec**: `zstandard>=0.23.0` for the `zstd` algorithm (default), via
the `compression-zstd` PEP 735 dependency group
(`uv sync --group compression-zstd`). The `gzip` algorithm uses the
stdlib `zlib` module and has no extra dependency. The `zstandard`
import is lazy — selecting `zstd` without the group installed raises
`LifecycleError("zstandard dependency required for zstd algorithm;
install with \`uv sync --group compression-zstd\`")` rather than
failing at module load.

**Settings** (see `StreamingCompressionSettings`):
- `algorithm` (`"zstd"` | `"gzip"`, default `"zstd"`).
- `level` (int, 1-22, default 3) — handed to `zstandard.ZstdCompressor`
  for `zstd`; for `gzip`, used as the `zlib` compression level (1-9
  range, but the schema permits 1-22 for uniformity; values above 9
  are clamped by zlib at runtime).

**Payload shape** (action-kit dispatch via `execute()`):
- `mode` (`"compress"` | `"decompress"`, default `"compress"`).

> **Note**: the `execute()` entrypoint is metadata-only — it returns
> `{"status": "noop", "mode": ..., "note": "use compress/decompress
> directly"}` because the action-kit dispatcher can't transport an
> iterator of bytes. Callers that need the actual streamed bytes
> should construct the action directly and invoke `compress()` or
> `decompress()`.

**Direct API** (bypass dispatch — use this for streaming):
```python
def compress(
    chunk_reader: Callable[[], Iterator[bytes]],
    *,
    algorithm: str | None = None,
    level: int | None = None,
) -> Iterator[bytes]: ...

def decompress(
    chunk_reader: Callable[[], Iterator[bytes]],
    *,
    algorithm: str | None = None,
) -> Iterator[bytes]: ...
```

The `chunk_reader` is a *zero-arg callable* returning an iterator of
bytes (not the iterator itself) — this lets callers re-invoke the
reader for retries without exhausting a one-shot generator. Previous
spec revisions carried vestigial `(offset, chunk_size)` parameters;
those were removed.

**Result shape** (for direct API calls):
- `compress()` / `decompress()` yield raw bytes; the caller consumes
  the iterator and is responsible for assembly (file writes,
  `shutil.copyfileobj`, network send, etc.).
- `execute()` returns `{"status": "noop", "mode": str, "note": str}`.

**Minimal example**:
```python
from oneiric.actions.streaming_compression import (
    StreamingCompressionAction,
    StreamingCompressionSettings,
)

action = StreamingCompressionAction(
    settings=StreamingCompressionSettings(algorithm="zstd", level=3),
)

# compress a chunked source (e.g., a tar iterator) into a stream
with open("bundle.tar.zst", "wb") as out:
    for chunk in action.compress(lambda: tar_chunk_iter("bundle.tar")):
        out.write(chunk)

# decompress back to plaintext
with open("bundle.tar", "wb") as out:
    for chunk in action.decompress(lambda: read_chunks("bundle.tar.zst")):
        out.write(chunk)
```

**Adopted by**: Phase 3 streaming tar.zst work in mahavishnu
(worktree bundles >100MB) — wires through S3 / local storage
multipart paths.

---

### `data.sanitize`

**Module**: `oneiric.actions.data`
**Use when**: redacting or stripping sensitive fields from a record
before logging, persisting, or forwarding — applies an allowlist, a
drop list, and a mask list (configurable mask value) in one pass.
**Don't use when**: you need schema-level type enforcement (use
`validation.schema`) or HMAC verification of authenticity (use
`security.signature`). Sanitize only *transforms shape*, not type or
provenance.

**Settings** (see `DataSanitizeSettings`):
- `allow_fields` (list[str] | None) — if set, only these fields survive.
- `drop_fields` (list[str]) — removed after the allowlist is applied.
- `mask_fields` (list[str]) — replaced with `mask_value`.
- `mask_value` (Any, default `"***"`) — replacement value.
- `case_sensitive` (bool, default `False`).

**Payload shape**:
- `data` (Mapping, required) — alternatively `record`.
- `allow_fields` / `drop_fields` / `mask_fields` (list[str]) — override settings.
- `mask_value` (Any) — override settings.
- `case_sensitive` (bool) — override settings.

**Result shape**:
```python
{"status": "sanitized",
 "data": dict,
 "applied": {"removed": int, "masked": int, "allow_fields": list | None}}
```

**Minimal example**:
```python
from oneiric.actions.data import DataSanitizeAction, DataSanitizeSettings

action = DataSanitizeAction(
    settings=DataSanitizeSettings(mask_fields=["password", "token"]),
)
result = await action.execute({"data": {"name": "x", "password": "secret"}})
sanitized = result["data"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `data.transform`

**Module**: `oneiric.actions.data`
**Use when**: reshaping a record between schemas — pick a subset
(`include_fields`), drop fields (`exclude_fields`), rename via map
(`rename_fields`), and backfill defaults — non-destructive operations
on a single record.
**Don't use when**: you need type-safe schema enforcement with required
fields and error aggregation (use `validation.schema`). Transform
doesn't check types; it just reshapes.

**Settings** (see `DataTransformSettings`):
- `include_fields` (list[str] | None) — when set, only these survive.
- `exclude_fields` (list[str]) — fields removed.
- `rename_fields` (dict[str, str]) — source → destination rename map.
- `defaults` (dict[str, Any]) — applied when keys are missing.

**Payload shape**:
- `data` (Mapping, required) — alternatively `record`.
- `include_fields` / `exclude_fields` (list[str]) — override settings.
- `rename_fields` (dict[str, str]) — override settings.
- `defaults` (dict[str, Any]) — override settings.

**Result shape**:
```python
{"status": "transformed",
 "data": dict,
 "applied": {"include_fields": list | None, "exclude_fields": list,
             "rename_applied": int, "defaults_applied": int}}
```

**Minimal example**:
```python
from oneiric.actions.data import DataTransformAction, DataTransformSettings

action = DataTransformAction(
    settings=DataTransformSettings(rename_fields={"userId": "user_id"}),
)
result = await action.execute({"data": {"userId": 1, "email": "x@y"}})
record = result["data"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `debug.console`

**Module**: `oneiric.actions.debug`
**Use when**: emitting a structured log line from inside a workflow
with optional stdout echo, level filtering, and redaction of
sensitive fields by name (`secret`, `token`, `password`, `key`).
**Don't use when**: you need durable audit records (use
`workflow.audit`) or fan-out to a notification channel (use
`workflow.notify`). Console goes to logger/stdout, not to a record
store.

**Settings** (see `DebugConsoleSettings`):
- `default_level` (`"debug"` | `"info"` | `"warning"` | `"error"` | `"critical"`, default `"info"`).
- `include_timestamp` (bool, default `True`) — adds ISO timestamp to record.
- `prefix` (str, default `"[debug]"`) — written before the message when echoing.
- `echo` (bool, default `True`) — also write to stdout.
- `scrub_fields` (list[str]) — fields scrubbed from nested `details`.

**Payload shape**:
- `message` (str, required).
- `level` (str) — overrides `default_level`.
- `details` (Mapping) — structured fields; nested `scrub_fields` are redacted.
- `prefix` / `echo` / `include_timestamp` / `scrub_fields` — override settings.

**Result shape**:
```python
{"status": "emitted",
 "message": str,
 "level": str,
 "prefix": str,
 "details": dict,           # scrubbed
 "timestamp": str | None}   # ISO when include_timestamp
```

**Minimal example**:
```python
from oneiric.actions.debug import DebugConsoleAction, DebugConsoleSettings

action = DebugConsoleAction(settings=DebugConsoleSettings(default_level="info"))
result = await action.execute({
    "message": "step complete",
    "details": {"step_id": "s-1", "duration_ms": 12},
})
status = result["status"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `event.dispatch`

**Module**: `oneiric.actions.event`
**Use when**: emitting a structured event to one or more webhook
subscribers with concurrency limits, optional per-hook timeouts, and
`dry_run` to validate wiring before going live.
**Don't use when**: you need local, in-process pub/sub between oneiric
kits — that's the `EventBus` infrastructure. Dispatch is for *external*
webhook fan-out.

**Settings** (see `EventDispatchSettings`):
- `default_topic` (str, default `"events.default"`).
- `default_source` (str, default `"oneiric.runtime"`).
- `max_hooks` (int, default 10).
- `timeout_seconds` (float, default 5.0) — base HTTP timeout.
- `concurrency` (int, default 5).
- `dry_run` (bool, default `True`) — `True` to simulate delivery.

**Payload shape**:
- `topic` (str) — required; overrides `default_topic`.
- `payload` (Mapping) — required; the event body. Alternatively `data`.
- `metadata` (Mapping) — event metadata.
- `hooks` (list[EventHookConfig dict]) — required for delivery. Alternatively `subscriptions`.
- `event_id` (str) — auto-generated UUID hex if omitted.
- `source` (str) — overrides `default_source`.
- `dry_run` (bool) — overrides settings.

**Result shape**:
```python
{"status": "dispatched" | "skipped" | "queued",
 "event": {"event_id", "topic", "source", "timestamp", "payload", "metadata"},
 "hooks": [{"name", "status" (delivered|skipped|failed),
            "code", "duration_ms", "reason"}],
 "delivered": int, "skipped": int, "failed": int}
```

**Minimal example**:
```python
from oneiric.actions.event import EventDispatchAction, EventDispatchSettings

action = EventDispatchAction(
    settings=EventDispatchSettings(dry_run=True, max_hooks=4),
)
result = await action.execute({
    "topic": "user.created",
    "payload": {"user_id": 42},
    "hooks": [
        {"name": "audit", "url": "https://example.test/hook",
         "method": "POST", "enabled": True}
    ],
})
delivered = result["delivered"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `http.fetch`

**Module**: `oneiric.actions.http`
**Use when**: making outbound HTTP calls (GET/POST/PUT/PATCH/DELETE)
from inside a workflow with structured JSON parsing, automatic trace
context injection, and optional OTel-instrumented spans.
**Don't use when**: you need webhook fan-out (use `event.dispatch`) or
a one-way fire-and-forget call (this kit awaits the response and
parses it). For streaming/long-polling, no built-in kit — bring your
own `httpx.AsyncClient`.

**Settings** (see `HttpActionSettings` extends `BaseURLSettings`):
- `default_method` (str, default `"GET"`) — GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS.
- `timeout_seconds` (float, default 10.0).
- `verify_ssl` (bool, default `True`).
- `allow_redirects` (bool, default `True`).
- `raise_for_status` (bool, default `False`) — raise on 4xx/5xx.
- `default_headers` (dict[str, str]) — merged with per-call headers.
- `base_url` (str | None, from `BaseURLSettings`) — combined with `path` when set.

**Payload shape**:
- `url` (str) — required unless `path`+`base_url` is set.
- `method` (str) — overrides settings.
- `path` (str) — joined to `base_url` when `url` is omitted.
- `params` / `query` (Mapping) — query string.
- `headers` (Mapping[str, str]) — merged on top of `default_headers`.
- `json` / `data` / `content` (Any) — request body.
- `timeout`, `verify`, `allow_redirects`, `raise_for_status` — per-call overrides.

**Result shape**:
```python
{"status": "success" | "error",
 "status_code": int, "ok": bool, "method": str, "url": str,
 "headers": dict, "elapsed_ms": float | None,
 "json": Any | None, "text": str | None}
```

**Minimal example**:
```python
from oneiric.actions.http import HttpFetchAction, HttpActionSettings

action = HttpFetchAction(settings=HttpActionSettings(timeout_seconds=5.0))
result = await action.execute({"url": "https://api.example.test/ping"})
body = result["json"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `security.secure`

**Module**: `oneiric.actions.security`
**Use when**: generating cryptographically strong tokens, hashing
passwords with PBKDF2-HMAC-SHA256, verifying password hashes, or
constant-time comparing two strings — all without bringing in a full
identity library.
**Don't use when**: you need Argon2/scrypt/bcrypt (PBKDF2 only here) or
JWT/SSO flows (out of scope). For HMAC signatures, use
`security.signature` instead.

**Settings** (see `SecuritySecureSettings`):
- `token_length` (int, default 32) — bytes fed to `secrets.token_urlsafe`.
- `password_iterations` (int, default 100_000) — PBKDF2 rounds.
- `include_symbols` (bool, default `True`).

**Payload shape**:
- `mode` (`"token"` | `"password-hash"` | `"password-verify"` | `"compare"`, default `"token"`).
- `length` (int) — token length override (mode `token`).
- `password`, `salt`, `iterations` — mode `password-hash` / `password-verify`.
- `hash` (str) — mode `password-verify`.
- `a`, `b` (str) — mode `compare`.

**Result shape**:
```python
# mode == "token"
{"status": "token", "token": str, "length": int}
# mode == "password-hash"
{"status": "password-hash", "hash": str, "salt": str, "iterations": int}
# mode == "password-verify"
{"status": "password-verify", "valid": bool}
# mode == "compare"
{"status": "compare", "equal": bool}
```

**Minimal example**:
```python
from oneiric.actions.security import SecuritySecureAction, SecuritySecureSettings

action = SecuritySecureAction(
    settings=SecuritySecureSettings(token_length=24),
)
result = await action.execute({"mode": "token"})
token = result["token"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `security.signature`

**Module**: `oneiric.actions.security`
**Use when**: producing an HMAC signature over a request body to
authenticate outbound webhooks or verify inbound ones — keyed (the
key difference from `compression.hash`) with the secret you supply.
**Don't use when**: you need an unkeyed digest (use `compression.hash`)
or full JWT/SSO. This kit only does HMAC.

**Settings** (see `SecuritySignatureSettings`):
- `algorithm` (`"sha256"` | `"sha512"` | `"blake2b"`, default `"sha256"`).
- `encoding` (`"hex"` | `"base64"`, default `"hex"`).
- `secret` (str | None) — fallback when payload omits `secret`.
- `header_name` (str, default `"X-Oneiric-Signature"`).
- `include_timestamp` (bool, default `True`).

**Payload shape**:
- `secret` (str) — required (or set in settings).
- `message` / `body` / `data` (str | bytes | JSON-serializable) — required.
- `algorithm` / `encoding` — override settings.
- `header` (str) — override of `header_name`.
- `include_timestamp` (bool) — override settings.

**Result shape**:
```python
{"status": "signed",
 "algorithm": str,
 "encoding": "hex" | "base64",
 "signature": str,
 "header": str,
 "timestamp": str | None}   # ISO when include_timestamp
```

**Minimal example**:
```python
from oneiric.actions.security import (
    SecuritySignatureAction,
    SecuritySignatureSettings,
)

action = SecuritySignatureAction(
    settings=SecuritySignatureSettings(secret="shh", algorithm="sha256"),
)
result = await action.execute({"message": '{"event":"ping"}'})
sig = result["signature"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `serialization.encode`

**Module**: `oneiric.actions.serialization`
**Use when**: encoding/decoding values to/from JSON, YAML, or
pickle (base64-wrapped) for transport, persistence, or file IO —
single kit that round-trips in-memory, text, and path-based sources.
**Don't use when**: you need a streaming serializer, a format beyond
json/yaml/pickle, or you want to load pickle from an untrusted source
(this kit's pickle path *requires* you trust the source; a warning
is logged but not enforced).

**Settings** (see `SerializationActionSettings`):
- `default_format` (`"json"` | `"yaml"` | `"pickle"`, default `"json"`).
- `sort_keys` (bool, default `False`) — deterministic output for json/yaml.
- `ensure_ascii` (bool, default `False`) — force ASCII for json.

**Payload shape**:
- `mode` (`"encode"` | `"decode"`, default `"encode"`).
- `format` (str) — override `default_format`.
- `value` / `data` (Any, required when encoding) — alternatively `text` when decoding.
- `path` (str) — when set, the kit reads from or writes to this path.
- `sort_keys` / `ensure_ascii` — override settings.

**Result shape**:
```python
# mode == "encode" (text formats)
{"status": "encoded", "format": "json"|"yaml", "text": str}
# mode == "encode" (pickle)
{"status": "encoded", "format": "pickle", "encoding": "base64", "data": str}
# mode == "decode"
{"status": "decoded", "format": str, "data": Any}
```

**Minimal example**:
```python
from oneiric.actions.serialization import (
    SerializationAction,
    SerializationActionSettings,
)

action = SerializationAction(
    settings=SerializationActionSettings(default_format="yaml", sort_keys=True),
)
result = await action.execute({"value": {"a": 1, "b": [2, 3]}, "mode": "encode"})
text = result["text"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `task.schedule`

**Module**: `oneiric.actions.task`
**Use when**: building a cron-style or fixed-interval schedule for a
task type, with optional start/end windows, max-runs caps, and a
preview of upcoming fire times — pure planning, no actual scheduling
side effects.
**Don't use when**: you need to *execute* on a tick (this kit only
plans; wire the output into a runner) or you need a sub-minute cadence
(currently minute-resolution; the cron parser walks minute boundaries).

**Settings** (see `TaskScheduleSettings`):
- `default_queue` (str, default `"default"`).
- `default_priority` (int, default 100, ge 0).
- `timezone` (str, default `"UTC"`).
- `max_preview_runs` (int, 1-50, default 5).

**Payload shape**:
- `task_type` (str, required) — task type to enqueue when the rule fires.
- `cron_expression` / `cron` (str) — 5-field minute-resolution cron; mutually exclusive with `interval_seconds`.
- `interval_seconds` / `interval` / `every_seconds` (float, gt 0) — fixed cadence.
- `queue` / `queue_name`, `name` / `rule_name`, `rule_id` / `id` (str) — identifiers.
- `payload` (Mapping, default `{}`).
- `priority` (int, ge 0), `start_time` / `end_time` (datetime), `max_runs` (int, gt 0), `preview_runs` (int, ge 0), `timezone` (str), `tags` (Mapping).

**Result shape**:
```python
{"status": "scheduled" | "unscheduled",
 "rule": {"rule_id", "name", "task_type", "queue", "priority",
          "cron_expression", "interval_seconds", "start_time", "end_time",
          "max_runs", "tags"},
 "next_run": str | None,           # ISO
 "upcoming_runs": [str, ...],      # ISO list, up to max_preview_runs
 "payload": dict}
```

**Minimal example**:
```python
from oneiric.actions.task import TaskScheduleAction, TaskScheduleSettings

action = TaskScheduleAction(
    settings=TaskScheduleSettings(default_queue="nightly", timezone="UTC"),
)
result = await action.execute({
    "task_type": "report.daily",
    "cron_expression": "0 3 * * *",
    "payload": {"report": "usage"},
})
next_run = result["next_run"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `validation.schema`

**Module**: `oneiric.actions.data`
**Use when**: type-checking a record against declarative per-field
rules (name, type, required, allow_null) and returning a
`{status, validated, errors}` envelope — fail-fast or collect-all
errors.
**Don't use when**: you need to reshape a record (use `data.transform`)
or redact secrets (use `data.sanitize`). Validation doesn't mutate.

**Settings** (see `ValidationSchemaSettings`):
- `fields` (list[`ValidationFieldRule`]) — name/type/required/allow_null per field.
- `allow_extra` (bool, default `True`) — allow keys beyond the schema.
- `fail_fast` (bool, default `False`) — stop on first error vs. collect.

**Payload shape**:
- `data` (Mapping, required) — alternatively `record`.
- `fields` (list[dict | `ValidationFieldRule`]) — overrides settings.
- `allow_extra` (bool) — override settings.
- `fail_fast` (bool) — override settings.

**Result shape**:
```python
{"status": "valid" | "invalid",
 "data": dict,            # original record
 "validated": dict,       # per-field validated values
 "errors": [str, ...]}
```

**Minimal example**:
```python
from oneiric.actions.data import (
    ValidationSchemaAction,
    ValidationSchemaSettings,
    ValidationFieldRule,
)

action = ValidationSchemaAction(
    settings=ValidationSchemaSettings(
        fields=[
            ValidationFieldRule(name="email", type="str", required=True),
            ValidationFieldRule(name="age", type="int", required=False, allow_null=True),
        ],
        allow_extra=False,
    ),
)
result = await action.execute({"data": {"email": "x@y"}})
status = result["status"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `workflow.audit`

**Module**: `oneiric.actions.workflow`
**Use when**: recording a structured, redacted audit event into the
workflow log channel (channel defaults to `"workflow"`, redacts
`secret`/`token`/`password`/`key` by default) — non-side-effect
emit, but durable to the log stream.
**Don't use when**: you need a notification with recipients (use
`workflow.notify`) or stdout echo (use `debug.console`). Audit is
*log-stream only*, not user-facing.

**Settings** (see `WorkflowAuditSettings`):
- `channel` (str, default `"workflow"`).
- `include_timestamp` (bool, default `True`).
- `default_event` (str, default `"workflow.audit"`).
- `redact_fields` (list[str]) — fields masked to `"***"` in nested details.

**Payload shape**:
- `event` (str) — required (or relies on `default_event`).
- `channel` (str) — overrides settings.
- `details` (Mapping) — structured fields; nested `redact_fields` are masked.
- `redact_fields` (list[str]) — additional fields to redact on top of settings.
- `include_timestamp` (bool) — override settings.

**Result shape**:
```python
{"status": "recorded",
 "event": str,
 "channel": str,
 "details": dict,           # redacted
 "timestamp": str | None}   # ISO when include_timestamp
```

**Minimal example**:
```python
from oneiric.actions.workflow import WorkflowAuditAction, WorkflowAuditSettings

action = WorkflowAuditAction(
    settings=WorkflowAuditSettings(channel="billing"),
)
result = await action.execute({
    "event": "billing.charge",
    "details": {"invoice_id": "inv-1", "amount_cents": 1999},
})
status = result["status"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `workflow.notify`

**Module**: `oneiric.actions.workflow`
**Use when**: composing a structured notification with an optional
recipient list, level, and context dict, then queueing it (with
recipients) or logging it (no recipients) — single kit that covers
both "needs to be seen by humans" and "needs to be in the log".
**Don't use when**: you need a redacted audit trail (use
`workflow.audit`) or a webhook to an external system (use
`event.dispatch`). Notify targets *humans* (or the log channel).

**Settings** (see `WorkflowNotifySettings`):
- `default_channel` (str, default `"workflow"`).
- `default_level` (`"debug"` | `"info"` | `"warning"` | `"error"` | `"critical"`, default `"info"`).
- `default_recipients` (list[str]) — applied when payload omits recipients.
- `require_message` (bool, default `True`).

**Payload shape**:
- `message` (str) — required when `require_message` is true.
- `channel` (str) — overrides settings.
- `level` (str) — overrides settings; defaults to `"info"` if invalid.
- `recipients` (str | list[str]) — overrides settings.
- `context` (Mapping) — opaque context blob forwarded with the notification.

**Result shape**:
```python
{"status": "queued" | "logged",
 "message": str,
 "channel": str,
 "level": str,
 "recipients": [str, ...],
 "context": dict | None}
```

**Minimal example**:
```python
from oneiric.actions.workflow import WorkflowNotifyAction, WorkflowNotifySettings

action = WorkflowNotifyAction(
    settings=WorkflowNotifySettings(default_recipients=["oncall@example.test"]),
)
result = await action.execute({
    "message": "deploy succeeded",
    "level": "info",
    "context": {"service": "api", "version": "1.2.3"},
})
status = result["status"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `workflow.orchestrate`

**Module**: `oneiric.actions.workflow`
**Use when**: planning a multi-step workflow into a versioned,
dependency-ordered plan with parallel batches, per-step retry/timeout,
and entry/terminal step detection — pure planner, no execution.
**Don't use when**: you need to *run* the workflow (use
`workflow.retry` per step, or wire this plan into an external
orchestrator). Orchestrate produces a plan; it doesn't execute it.

**Settings** (see `WorkflowOrchestratorSettings`):
- `max_parallel_steps` (int, default 4, ge 1) — cap on parallel batch size.
- `default_version` (str, default `"1.0.0"`) — applied when definitions omit one.
- `default_retry_attempts` (int, default 3, ge 0).
- `default_timeout_seconds` (float, default 300.0, gt 0).

**Payload shape** (see `WorkflowDefinitionSpec`):
- `workflow_id` (str, required).
- `name`, `version`, `description` (str) — optional metadata.
- `start_paused` (bool, default `False`) — produce a paused plan.
- `steps` (list[`WorkflowStepSpec`], required) — each has `step_id`, `name`, `action`, optional `depends_on`/`retry_attempts`/`timeout_seconds`/`metadata`/`tags`.
- `metadata`, `context`, `tags` — workflow-level extras.
- `target_steps` (list[str]) — optional subset to compile (dependencies included).

**Result shape**:
```python
{"status": "planned" | "paused",
 "workflow_id", "name", "version", "run_token", "generated_at",
 "step_count", "schedule": [[step_id, ...], ...],   # parallel batches
 "ordered_steps": [step_id, ...],
 "steps": [{step_id, name, action, depends_on, retry_attempts,
            retry_policy, timeout_seconds, metadata, tags}, ...],
 "graph": {"dependencies": {...}, "entry_steps": [...], "terminal_steps": [...]},
 "context", "metadata", "tags",
 "stats": {"parallel_groups", "max_group_size",
           "default_retry_attempts", "default_timeout_seconds"}}
```

**Minimal example**:
```python
from oneiric.actions.workflow import (
    WorkflowOrchestratorAction,
    WorkflowOrchestratorSettings,
)

action = WorkflowOrchestratorAction(
    settings=WorkflowOrchestratorSettings(max_parallel_steps=2),
)
result = await action.execute({
    "workflow_id": "wf-001",
    "steps": [
        {"step_id": "fetch", "name": "Fetch", "action": "http.fetch"},
        {"step_id": "parse", "name": "Parse", "action": "data.transform",
         "depends_on": ["fetch"]},
    ],
})
batches = result["schedule"]
```

**Adopted by**: (none yet — internal scaffolding only).

---

### `workflow.retry`

**Module**: `oneiric.actions.workflow`
**Use when**: computing deterministic exponential-backoff guidance
(`delay_seconds`, `next_attempt`) for a retrying operation —
side-effect free, so you can call it inside a planner to decide
whether to schedule another attempt.
**Don't use when**: you need a real retry loop with sleep + execute
(this kit only *computes* the next attempt; bring your own loop or
wire it to `workflow.orchestrate`).

**Settings** (see `WorkflowRetrySettings`):
- `max_attempts` (int, default 3, ge 1).
- `base_delay_seconds` (float, default 1.0, ge 0).
- `multiplier` (float, default 2.0, ge 1.0).
- `max_delay_seconds` (float, default 60.0, ge 0).
- `jitter` (float, default 0.1, clamped 0-1).

**Payload shape**:
- `attempt` (int, default 0, ge 0) — current attempt count.
- `max_attempts` (int, ge 1) — override settings.
- `base_delay_seconds`, `multiplier`, `max_delay_seconds`, `jitter` — overrides.

**Result shape**:
```python
{"attempt": int, "max_attempts": int, "status": "scheduled" | "exhausted",
 "next_attempt": int | None, "delay_seconds": float | None}
```

**Minimal example**:
```python
from oneiric.actions.workflow import WorkflowRetryAction, WorkflowRetrySettings

action = WorkflowRetryAction(
    settings=WorkflowRetrySettings(base_delay_seconds=0.5, max_attempts=4),
)
result = await action.execute({"attempt": 1})
delay = result["delay_seconds"]
```

**Adopted by**: (none yet — internal scaffolding only).
