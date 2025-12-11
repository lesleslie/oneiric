# NoSQL Adapter Sprint (MongoDB / DynamoDB / Firestore)

**Last Updated:** 2025-12-09
**Owners:** Data Platform (Nadia – DRI), Platform Core (support), Runtime Team (test infra)
**Timeline:** Q1 2026 sprint (kick-off immediately, target code complete by Jan 31)

______________________________________________________________________

## 1. Objectives

1. Deliver production-grade MongoDB, DynamoDB, and Firestore adapters that satisfy the Stage 3 lifecycle contract.
1. Ship adapter extras + dependency guards so serverless builds stay lean.
1. Provide end-to-end coverage: unit tests, manifest snippets, CLI demos, and runbook notes.

______________________________________________________________________

## 2. Deliverables

| Deliverable | Details | Owner |
|-------------|---------|-------|
| `oneiric.adapters.nosql.mongodb.MongoDBAdapter` | ✅ **Complete (Dec 2025):** Motor client with CRUD helpers, aggregation support, health probes, unit tests. | Nadia (Data Platform) |
| `oneiric.adapters.nosql.dynamodb.DynamoDBAdapter` | ✅ **Complete (Dec 2025):** aioboto3 adapter with CRUD, scan, conditional writes, optional profile/endpoint support, unit tests/fakes. | Nadia + Runtime pairing |
| `oneiric.adapters.nosql.firestore.FirestoreAdapter` | ✅ **Complete (Dec 2025):** Async Firestore adapter with set/get/query helpers, emulator + credentials support, manifests/docs/tests. | Nadia + Platform Core |
| Extras | ✅ **Complete:** `pyproject.toml` extras `nosql-mongo`, `nosql-dynamo`, `nosql-firestore`, plus `nosql` meta extra + lockfile refresh. | Platform Core |
| Fixtures & tests | `tests/adapters/nosql/test_mongodb.py`, etc. Use pytests with `pytest.importorskip` to avoid missing deps. Include Snapshot fixtures under `tests/fixtures/nosql`. | Runtime Team |
| Docs | `docs/analysis/NOSQL_ADAPTERS.md` (usage + config), manifest snippets under `docs/examples/`. Update CLI demo to show `--domain adapter --key nosql`. | Docs Team |
| CLI proof | `uv run python -m oneiric.cli --demo list --domain adapter` includes the new providers; add manifest snippet referencing `nosql.mongo`. | Platform Core |

______________________________________________________________________

## 3. Implementation Phases

### Phase A – Scaffolding & Extras (Week 1)

1. ✅ Define extras in `pyproject.toml`:
   - `nosql-mongo = ["motor>=3.6"]`
   - `nosql-dynamo = ["aioboto3>=12.0"]`
   - `nosql-firestore = ["google-cloud-firestore>=2.16"]`
   - `nosql = ["oneiric[nosql-mongo,nosql-dynamo,nosql-firestore]"]`
1. ✅ Add provider metadata (MongoDB) to `oneiric/adapters/bootstrap.py`.
1. ✅ Create adapter module with lazy import helpers; DynamoDB + Firestore modules follow the same pattern.

### Phase B – Adapter Implementation (Weeks 1-2)

1. **MongoDB** ✅ *(complete; keep for reference)*
   - Settings: URI, database, default collection, TLS flags.
   - Methods: `find_one`, `find`, `insert_one`, `update_one`, `delete_one`, `aggregate`.
   - Health: ping admin DB.
1. **DynamoDB** ✅ *(complete; see adapter docs)*
   - Settings cover table, region, endpoint override, credentials/profile.
   - Methods implemented: `get_item`, `put_item`, `update_item`, `delete_item`, `scan`.
   - Optional consistent reads + condition expressions supported.
1. **Firestore** ✅ *(complete)*
   - Settings cover project ID, collection name, credentials file, emulator host.
   - Methods implemented: `get_document`, `set_document`, `delete_document`, `query_documents`.
   - Emulator support via `FIRESTORE_EMULATOR_HOST`; lazy import guards for optional extras.

### Phase C – Tests, Docs, Examples (Weeks 2-3)

1. Unit tests mocking client libs (`pytest.importorskip("motor")` etc.) so tests skip when extras missing.
1. Integration-like tests using in-memory fakes:
   - For MongoDB use `mongomock` (optional extra) to keep CI fast.
   - For Dynamo/Firestore rely on stub clients (use simple dataclass to capture requests).
1. Update docs:
   - `docs/examples/LOCAL_CLI_DEMO.md` – add NoSQL section.
   - `docs/remote/sample_manifest*.yaml` – add entries referencing the new adapters.
1. CLI transcripts showing `--demo list --domain adapter` includes `nosql.mongo`.

______________________________________________________________________

## 4. Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| Optional deps unavailable in CI | Wrap tests with `pytest.importorskip`; run full suite in nightly job with extras installed. |
| Dynamo credentials handling | Use `SecretsHook` to fetch AWS keys or leverage IAM role when running in Cloud Run. Document both flows. |
| Firestore emulator vs prod differences | Provide `emulator_host` setting and note differences in docs. |
| Adapter cold start | Lazy import heavy libs (`motor`, `google.cloud`) inside `init`. |

______________________________________________________________________

## 5. Timeline

| Week | Milestone |
|------|-----------|
| Week 1 (Jan 6) | Extras + metadata merged, MongoDB skeleton + tests. |
| Week 2 (Jan 13) | DynamoDB adapter PR + shared fixtures. |
| Week 3 (Jan 20) | Firestore adapter + docs updates. |
| Week 4 (Jan 27) | Buffer for polish, CLI demos, manifest snippets. |

______________________________________________________________________

## 6. Tracking & Evidence

- PR checklist includes: adapter code, metadata registration, tests, docs, CLI transcript screenshot/log.
- Update `docs/implementation/ADAPTER_REMEDIATION_EXECUTION.md` after each adapter lands.
- Add release note bullet in next tag once all three are merged.

Keep this document in sync with actual progress (mark tasks complete, adjust risks) so reviewers can see sprint health at a glance.
