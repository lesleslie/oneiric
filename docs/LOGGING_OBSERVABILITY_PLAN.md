# Logging & Observability Plan (Oneiric)

Goal: build logging/observability utilities from scratch for Oneiric with async-aware
IO, structured logs, and easy drop-in for adapters/services/tasks/events/workflows.
Leverage logly or structlog; drop legacy globals.

## Recommendations
- Prefer structured logging with async-friendly handlers.
- If choosing between loguru and logly, favor logly (async-ready, pluggable sinks);
  if sticking with structlog, pair it with standard logging handlers and async sinks.
- Ensure OpenTelemetry log correlation (trace/span IDs) when tracing is enabled.

## Build Plan
1) **Core logger factory**:
   - Provide a factory that configures a base logger with JSON/structured output,
     context fields (domain, key, provider, source, priority, stack_level), and async
     sinks (e.g., aiofiles-based file, stdout, HTTP sink).
   - Expose both a `Logger` (structlog or logly) and a bridge to stdlib logging for
     third-party libs.
2) **Context injection**:
   - Middleware/helpers to inject resolver metadata (domain/key/provider/source) into
     log context automatically.
   - OTel correlation: include trace_id/span_id when tracing is active.
3) **Sinks/Handlers**:
   - Async stdout sink (line-delimited JSON).
   - Optional file sink with rotation (async-friendly).
   - Optional HTTP sink (batch, backpressure).
   - Optional console pretty printer for CLI/debug.
4) **Configuration**:
   - Pydantic settings for logging: level, format (json/plain), sinks, OTel flag,
     sampling, redaction rules.
   - Secret-aware fields (e.g., HTTP sink auth) via secret adapter source.
5) **Domain integration**:
   - Provide helpers for each domain bridge to attach domain context to logs.
   - Lifecycle events (init/health/cleanup/swap) emit structured events.
6) **Testing**:
   - Validate structured output shape, context injection, OTel correlation when enabled,
     and async sink behavior (flush/rotation).
   - Ensure backpressure handling for HTTP sink and file writes.

## Library Choices
- **logly**: Good async story and structured sinks; use as primary if adopting.
- **structlog**: Still a solid choice; pair with async-capable handlers. Good ecosystem.
- **OTel logging**: Use OTel log bridge to add trace/span IDs to log records; keep it
  optional and configurable.

## Migration Notes
- Do not reuse loguru globals; re-create logging setup per Oneiric’s runtime init.
- Provide a thin adapter if existing code expects loguru-like API (optional).
- Ensure adapters/services/tasks/events/workflows use dependency-injected logger
  instances, not module-level singletons.
