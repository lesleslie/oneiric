# DNS & File Transfer Adapter Plan

> **Archive Notice (2025-12-19):** Historical Wave C plan; adapters shipped. See `docs/analysis/ADAPTER_GAP_AUDIT.md` for current backlog status.

**Last Updated:** 2025-12-10
**Owners:** Platform Core (DNS), Infra/Messaging (File Transfer)

This document captures the original Wave C backlog tracked in the adapter gap audit: Route53 DNS plus file transfer adapters. Cloudflare DNS, Route53 DNS, and every file transfer transport (FTP/SFTP/SCP/HTTP download/HTTPS upload) now ship in-tree; the blueprint below documents the implementation for future reference.

______________________________________________________________________

## Completed Providers

| Adapter | Module | Tests / Docs | Notes |
|---------|--------|--------------|-------|
| DNS (Cloudflare) | `oneiric.adapters.dns.cloudflare.CloudflareDNSAdapter` | `tests/adapters/test_cloudflare_dns_adapter.py`, README built-ins | HTTPX implementation with record CRUD helpers and SecretsHook integration. |
| DNS (Route53) | `oneiric.adapters.dns.route53.Route53DNSAdapter` | `tests/adapters/test_route53_dns_adapter.py` | aioboto3-backed adapter using async clients + lifecycle hooks. |
| DNS (GCDNS) | `oneiric.adapters.dns.gcdns.GCDNSAdapter` | `tests/adapters/test_gcdns_adapter.py` | Google Cloud DNS adapter with record CRUD helpers and lifecycle checks. |
| File Transfer (FTP) | `oneiric.adapters.file_transfer.ftp.FTPFileTransferAdapter` | `tests/adapters/test_ftp_file_transfer_adapter.py`, `docs/examples/LOCAL_CLI_DEMO.md` §10 | FTP adapter supporting upload/download/delete/list, designed for optional aioftp installs. |
| File Transfer (SFTP) | `oneiric.adapters.file_transfer.sftp.SFTPFileTransferAdapter` | `tests/adapters/test_sftp_file_transfer_adapter.py` | asyncssh-backed adapter mirroring the FTP interface for secure transfers. |
| File Transfer (SCP) | `oneiric.adapters.file_transfer.scp.SCPFileTransferAdapter` | `tests/adapters/test_scp_file_transfer_adapter.py` | asyncssh-powered SCP helper for SSH-based uploads/downloads with manifest coverage. |
| File Transfer (HTTP download) | `oneiric.adapters.file_transfer.http_artifact.HTTPArtifactAdapter` | `tests/adapters/test_http_artifact_adapter.py` | httpx adapter for artifact downloads with optional SHA256 validation and base URL support. |
| File Transfer (HTTPS upload) | `oneiric.adapters.file_transfer.http_upload.HTTPSUploadAdapter` | `tests/adapters/test_https_upload_adapter.py` | httpx adapter for signed HTTPS uploads with auth headers + CLI/demo docs. |

Remaining backlog: optional transports (feature flag remotes, repo-specific adapters). Capture requirements here before implementation.

______________________________________________________________________

## 1. Goals

1. Provide resolver-friendly DNS adapters that expose create/update/delete record helpers with lifecycle hooks, secrets, and manifest metadata.
1. Ship file transfer adapters (FTP/SFTP/SCP/HTTP download/HTTPS upload) that align with Oneiric’s lifecycle/pause-drain semantics and can be referenced from manifests (`domains.file_transfer` or `adapters.file_transfer`).
1. Keep optional extras isolated (e.g., `oneiric[dns-cloudflare]`) so default installs remain slim.
1. Ensure parity artifacts (tests, manifests, docs) exist before enabling the adapters in production profiles.

______________________________________________________________________

## 2. DNS Adapter Blueprint

| Provider | Lib | Extra | Key Tasks |
|----------|-----|-------|-----------|
| Cloudflare | `cloudflare` REST API via `httpx` | `oneiric[dns-cloudflare]` | Typed settings (zone ID, API token), lifecycle wrapper with `init/health/cleanup`, record CRUD helpers, SecretsHook support, tests using Cloudflare mock server or responses, manifest snippet referencing `adapter.dns.cloudflare`. |
| Route53 | `boto3` (`aiobotocore`) | `oneiric[dns-route53]` | Typed settings (hosted zone ID, AWS creds), async client using aiobotocore, lifecycle hooks, record management API, tests using `moto` or stubbed client. |

**Common Requirements**

- **Metadata:** domain `adapter`, category `dns`, capabilities `["record.manage", "record.list"]`, `requires_secrets=True`, `settings_model` pointing at `CloudflareDNSSettings`/`Route53DNSSettings`.
- **Settings Fields:** API tokens/credentials, zone identifiers, retry/backoff configuration, optional base URL for mock servers.
- **Lifecycle Hooks:** `init` (validate credentials and zone), `health` (list or get zone), `cleanup` (close httpx/aiobotocore session).
- **Resolver Integration:** register via `register_builtin_adapters` and add CLI demo commands.
- **Testing:** unit tests with fake clients asserting request payloads; integration tests optional (e.g., `pytest.mark.integration` hitting mock server).
- **Docs:** README entry + sample manifest snippet demonstrating record creation. Add runbook notes if used for certificate automation.

______________________________________________________________________

## 3. File Transfer Adapter Blueprint

| Provider | Protocol | Extra | Key Tasks |
|----------|----------|-------|-----------|
| SFTP | Paramiko/asyncssh | `oneiric[file-transfer-sftp]` | Settings for host/port/auth, lifecycle-managed connection pool, upload/download/delete helpers, resume capability, tests using asyncssh stub server. |
| FTP | `aioftp` | `oneiric[file-transfer-ftp]` | Similar to SFTP but using FTP protocol; document insecure nature and encourage SFTP first. |
| HTTP Artifact | `httpx` | None (core dependency) | Provide streaming download helper with checksum validation (sha256), resumable support, optional auth headers (SecretsHook). |

**Common Requirements**

- Domain: `adapter` or new `file_transfer` bridge (decide based on manifest ergonomics). For now assume `adapter` with key `file_transfer`.
- Capabilities: `["upload", "download", "delete", "list", "checksum"]` where applicable.
- Settings: host, credentials (SecretStr), remote path defaults, TLS toggles, concurrency limits.
- Lifecycle: connection pool creation, health check (list root directory), cleanup closing sessions.
- Tests: use local stub servers (asyncssh, aioftp) and stubbed HTTP responses. Provide fixtures under `tests/adapters/file_transfer`.
- Docs: README + `docs/examples/LOCAL_CLI_DEMO.md` snippet showing `AdapterBridge` usage, manifest entry for remote artifact downloads.

______________________________________________________________________

## 4. Acceptance Checklist

Before marking a provider complete:

1. **Code:** adapter module + settings + metadata + lifecycle hooks, registered via `register_builtin_adapters`.
1. **Tests:** unit tests covering init/health/upload/download (SFTP/FTP) or record CRUD (DNS). Include error cases.
1. **Docs:** README entry, manifest snippet, settings example, CLI/demo snippet.
1. **Extras:** `pyproject.toml` extras entry + `uv.lock` update.
1. **Observability:** structured log keys (`adapter.dns.cloudflare`, etc.) and health logs for detectors.
1. **Audit:** update `docs/analysis/ACB_ADAPTER_ACTION_IMPLEMENTATION.md` + `docs/analysis/ADAPTER_GAP_AUDIT.md`.

______________________________________________________________________

## 5. Next Steps

1. Confirm which downstream repo (Crackerjack, FastBlocks, session-mgmt) needs DNS or file transfer support first.
1. Once prioritized, raise an issue referencing this plan and assign an owner.
1. Implement adapters sequentially: Cloudflare DNS → Route53 DNS → SFTP → HTTP artifact → FTP (optional fallback).
1. Capture CLI proofs (similar to other adapters) and add to `docs/examples/LOCAL_CLI_DEMO.md` or a dedicated runbook.

Maintain this plan alongside the adapter audit. Update it when new requirements land or once a provider ships so Phase 3’s backlog stays transparent.
