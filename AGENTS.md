# Repository Guidelines

## Project Structure & Module Organization

- `oneiric/` holds the Python package: adapters (`adapters/`), lifecycle + config logic (`core/`), CLI entrypoints (`cli.py`), remote sync clients (`remote/`), runtime/orchestration helpers (`runtime/`), and domain abstractions (`domains/`).
- `main.py` is the minimal runner that wires the default settings for demos; `docs/` stores manifests and reference material; `tests/` mirrors the package layout with unit and async integration suites; coverage artifacts land in `htmlcov/` and `coverage.xml`.
- Keep new assets (sample manifests, telemetry captures) inside `docs/` and gate experimental playground code behind `oneiric/demo.py` so production modules stay lean.
- Stage 3 action migration work now lives alongside adapters: use `oneiric/actions/` for metadata/bridge helpers and track features in `docs/STAGE3_ACTION_MIGRATION.md` so the action waves stay in sync with adapters. Builtin kits currently include `compression.encode`, `workflow.audit`, `workflow.notify`, `workflow.retry`, the Wave B helpers `http.fetch`, `security.signature`, `data.transform`, and the first Wave C console kit `debug.console`.

## Build, Test, and Development Commands

- `uv run python main.py` – smoke-test the packaged runtime with the default demo configuration.
- `uv run python -m oneiric.cli --demo list --domain adapter` – quick CLI verification; swap `--demo` flags per README examples for other flows.
- `uv run python -m oneiric.cli orchestrate --manifest docs/sample_remote_manifest.yaml --refresh-interval 120` – exercise the watcher + remote refresh loop locally.
- `uv run pytest` – executes the strict `pytest.ini` profile (asyncio auto mode, coverage reports: terminal, HTML, XML). Add `-k <pattern>` for targeted suites when iterating.
- `uv run python -m oneiric.cli --demo list --domain action` – inspect registered action kits (compression encode ships by default; more arrive via Stage 3 waves).
- `uv run python -m oneiric.cli --demo action-invoke compression.encode --payload '{"text":"cli"}' --json` – invoke an action kit directly to validate Stage 3 migrations end to end.

## Coding Style & Naming Conventions

- Target Python 3.14+, 4-space indentation, and comprehensive type hints; prefer `pydantic.BaseModel` for config/DTOs and `structlog`-backed loggers via `core.logging.get_logger`.
- Module naming is lowercase with underscores; provider identifiers stay kebab-case inside manifests, while Pydantic models use PascalCase (`RemoteSourceConfig`).
- Keep async entrypoints explicit (e.g., `async def refresh_remote(...)`) and expose orchestration hooks through thin adapters so lifecycle managers remain testable.
- Default cloud posture: new storage/secrets integrations should prioritize Google Cloud (GCS + Secret Manager) with AWS providers treated as optional fallbacks.

## Testing Guidelines

- House unit tests beside their domain (`tests/core/test_config.py`, `tests/runtime/test_health.py`, etc.) and name coroutines `async def test_*` to stay compatible with `pytest-asyncio` auto mode.
- Maintain coverage with `uv run pytest --cov=oneiric`; investigate any gaps reported in `htmlcov/index.html` before opening a PR.
- Use markers declared in `pyproject.toml` (`@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.slow`) to scope heavier flows and skip them in rapid loops.

## Quality Control & Best Practices

- Use Crackerjack for repo-wide quality gates before merging; run `python -m crackerjack -a patch` (or the staged `-x -t -p patch -c` flow) so linting, tests, formatting, and version bumps mirror the workflows in `../crackerjack`, `../acb`, and `../fastblocks`.
- Apply the ACB + Crackerjack best practices (type rigor, structured logging screenshots, CLI proof output) but tailor examples/configs to Oneiric’s resolver + lifecycle stack.
- Document behavioral changes the same way the sibling repos do: include CLI transcripts or log excerpts plus manifest snippets whenever behavior or configuration changes.

## Commit & Pull Request Guidelines

- Follow short, imperative commit subjects (`orchestrator: fix remote refresh backoff`); include a short body explaining context and linking issues when relevant.
- PRs should describe the resolver domain(s) touched, list the CLI/test commands executed, and attach screenshots or logs for CLI status/orchestrator output when behavior changes.
- Reference related manifests or config samples (`docs/sample_remote_manifest.yaml`) so reviewers can replay scenarios quickly.

## Security & Configuration Tips

- Never commit real secrets; keep credentials in `.env`/`ONEIRIC_` prefixed environment variables so `core.config.load_settings` can read them.
- Remote cache files (e.g., `.oneiric_cache/runtime_health.json`) may contain operational metadata—scrub or gitignore new cache paths before pushing.
- When documenting new remote domains, provide sanitized manifest snippets plus instructions for rotating `remote.auth` tokens to keep the samples safe yet actionable.
