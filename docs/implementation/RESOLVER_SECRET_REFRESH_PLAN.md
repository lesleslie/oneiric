# Resolver Secret Cache Refresh Design

**Last Updated:** 2025-12-09  
**Owners:** Platform Core (resolver/runtime), Docs Team (runbooks)

This note captures the implementation plan for zero-downtime secret rotation so the outstanding Stage 5 audit item (“Secrets rotation requires manual restart”) can be closed in v0.2.1.

---

## 1. Goals

1. Support hot secret refresh without bouncing the orchestrator.
2. Keep the serverless profile stateless: Cloud Run revisions still restart to pick up new values, but long-lived installs (Crackerjack, FastBlocks) can rotate in place.
3. Avoid noisy watcher loops—rely on resolver-level cache invalidation hooks instead.

---

## 2. Proposed Flow

1. **Central cache layer**
   - Extend `oneiric.core.config.Settings` to expose `secrets_cache_ttl` (default 10 minutes) and surface it via env/TOML config.
   - Introduce `SecretValueCache` in `oneiric.adapters.secrets.common` that stores `(value, fetched_at)` per `(provider, key)`.
2. **Resolver hook**
   - Add `Resolver.invalidate_secrets(keys: Sequence[str] | None = None)` that clears cached entries and broadcasts a structlog event `secrets-cache-invalidated`.
   - Lifecycle managers call this hook before re-running adapter init when rotation events fire.
3. **Triggering rotation**
   - New CLI command: `uv run python -m oneiric.cli secrets rotate --provider gcp --keys key1,key2` → calls remote admin endpoint or simply issues `Resolver.invalidate_secrets`.
   - Watchers optional: long-lived installs can run `oneiric.runtime.watchers.SecretRefreshWatcher` that checks Secret Manager metadata timestamps every `secrets_watch_interval`.
4. **Telemetry & safety**
   - Emit metrics (`secrets.cache_hits`, `secrets.cache_misses`, `secrets.invalidate_total`) via `core.observability`.
   - Gate refreshes so concurrent invalidations de-dup based on key hash to avoid redundant adapter churn.

---

## 3. Serverless Profile Considerations

- Serverless deployments keep `secrets_cache_ttl` small (<=60 s) and rely on Cloud Run revisions for rotation; watchers stay disabled.
- Documentation (`docs/runbooks/MAINTENANCE.md`) gets a new subsection: “Initiate live secret rotation” describing the CLI command followed by validation steps.

---

## 4. Rollout Checklist

1. Implement cache + TTL in adapters/secrets helpers.
2. Add resolver hook + logging/metrics.
3. Wire CLI `secrets rotate` command and update docs/README + runbooks.
4. Update `docs/implementation/STAGE5_FINAL_AUDIT_REPORT.md §8.2` to reference this plan (closing the audit follow-up).

---

Keep this file alongside the serverless/parity execution plan so future audit reports can reference the concrete steps and status.
