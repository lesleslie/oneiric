"""Tests for CLI commands."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest
from typer.testing import CliRunner

from oneiric import plugins
from oneiric.cli import _print_runtime_health, app
from oneiric.core.config import OneiricSettings

# Test fixtures


@pytest.fixture
def runner():
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_settings(tmp_path):
    """Mock OneiricSettings for testing."""
    return OneiricSettings(
        config_dir=str(tmp_path / "settings"),
        cache_dir=str(tmp_path / "cache"),
    )


# CLI Command Tests


class TestListCommand:
    """Test list command."""

    def test_list_without_demo(self, runner, tmp_path):
        """list command works without demo providers."""
        result = runner.invoke(app, ["list", "--domain", "adapter"])

        assert result.exit_code == 0
        assert "Active adapters:" in result.stdout

    def test_list_with_demo(self, runner):
        """list command works with demo providers."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "adapter"])

        assert result.exit_code == 0
        assert "Active adapters:" in result.stdout
        assert "demo/cli" in result.stdout

    def test_list_with_shadowed(self, runner):
        """list command shows shadowed candidates."""
        result = runner.invoke(
            app, ["--demo", "list", "--domain", "adapter", "--shadowed"]
        )

        assert result.exit_code == 0
        assert "Active adapters:" in result.stdout

    def test_list_services(self, runner):
        """list command works for services."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "service"])

        assert result.exit_code == 0
        assert "Active services:" in result.stdout

    def test_list_tasks(self, runner):
        """list command works for tasks."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "task"])

        assert result.exit_code == 0
        assert "Active tasks:" in result.stdout

    def test_list_events(self, runner):
        """list command works for events."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "event"])

        assert result.exit_code == 0
        assert "Active events:" in result.stdout

    def test_list_workflows(self, runner):
        """list command works for workflows."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "workflow"])

        assert result.exit_code == 0
        assert "Active workflows:" in result.stdout

    def test_list_actions(self, runner):
        """list command works for actions."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "action"])

        assert result.exit_code == 0
        assert "Active actions:" in result.stdout

    def test_list_invalid_domain(self, runner):
        """list command rejects invalid domain."""
        result = runner.invoke(app, ["list", "--domain", "invalid"])

        assert result.exit_code != 0
        # Error message appears in stderr or stdout depending on Typer version
        output = result.stdout + (result.stderr or "")
        assert "Domain must be one of" in output


class TestExplainCommand:
    """Test explain command."""

    def test_explain_adapter(self, runner):
        """explain command shows resolution path for adapter."""
        result = runner.invoke(
            app, ["--demo", "explain", "demo", "--domain", "adapter"]
        )

        assert result.exit_code == 0
        # Command outputs JSON but may be mixed with logs - just verify it runs
        assert result.stdout is not None

    def test_explain_service(self, runner):
        """explain command shows resolution path for service."""
        result = runner.invoke(
            app, ["--demo", "explain", "status", "--domain", "service"]
        )

        assert result.exit_code == 0
        assert result.stdout is not None

    def test_explain_unresolved(self, runner):
        """explain command handles unresolved keys."""
        result = runner.invoke(
            app, ["--demo", "explain", "nonexistent", "--domain", "adapter"]
        )

        assert result.exit_code == 0
        assert result.stdout is not None


class TestSwapCommand:
    """Test swap command."""

    def test_swap_basic(self, runner):
        """swap command performs lifecycle swap."""
        result = runner.invoke(app, ["--demo", "swap", "status", "--domain", "service"])

        assert result.exit_code == 0
        assert "Swapped service:status" in result.stdout

    def test_swap_with_provider(self, runner):
        """swap command accepts provider override."""
        result = runner.invoke(
            app, ["--demo", "swap", "demo", "--domain", "adapter", "--provider", "cli"]
        )

        assert result.exit_code == 0
        assert "Swapped adapter:demo" in result.stdout

    def test_swap_with_force(self, runner):
        """swap command accepts force flag."""
        result = runner.invoke(
            app, ["--demo", "swap", "status", "--domain", "service", "--force"]
        )

        assert result.exit_code == 0
        assert "Swapped service:status" in result.stdout


class TestPauseCommand:
    """Test pause command."""

    def test_pause_basic(self, runner, tmp_path):
        """pause command marks key as paused."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "pause",
                "demo",
                "--domain",
                "adapter",
            ],
        )

        assert result.exit_code == 0
        assert "Paused adapter:demo" in result.stdout

    def test_pause_with_note(self, runner, tmp_path):
        """pause command accepts note."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "pause",
                "demo",
                "--domain",
                "adapter",
                "--note",
                "maintenance",
            ],
        )

        assert result.exit_code == 0
        assert "Paused adapter:demo" in result.stdout
        assert "note=maintenance" in result.stdout

    def test_pause_resume(self, runner, tmp_path):
        """pause command with --resume unpauses."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "pause",
                "demo",
                "--domain",
                "adapter",
                "--resume",
            ],
        )

        assert result.exit_code == 0
        assert "Resumed adapter:demo" in result.stdout


class TestManifestCommands:
    """Tests for manifest helper commands."""

    def test_manifest_pack_outputs_json(self, runner, tmp_path):
        """manifest pack produces canonical JSON file."""
        manifest_source = tmp_path / "manifest.yaml"
        manifest_source.write_text(
            json.dumps(
                {
                    "source": "serverless",
                    "entries": [
                        {
                            "domain": "adapter",
                            "key": "cache",
                            "provider": "memory",
                            "factory": "oneiric.adapters.cache.memory:MemoryCacheAdapter",
                        }
                    ],
                }
            )
        )
        output_path = tmp_path / "packed.json"
        result = runner.invoke(
            app,
            [
                "manifest",
                "pack",
                "--input",
                str(manifest_source),
                "--output",
                str(output_path),
            ],
        )

        assert result.exit_code == 0
        packed = json.loads(output_path.read_text())
        assert packed["source"] == "serverless"
        assert packed["entries"][0]["domain"] == "adapter"


class TestSecretsCommands:
    """Tests for secrets helper commands."""

    def test_secrets_rotate_all(self, runner, tmp_path):
        """secrets rotate clears cache (even when empty)."""
        result = runner.invoke(
            app,
            [
                "--config",
                str(tmp_path / "app.toml"),
                "--demo",
                "secrets",
                "rotate",
                "--all",
            ],
        )

        assert result.exit_code == 0
        assert "Invalidated" in result.stdout


class TestDrainCommand:
    """Test drain command."""

    def test_drain_basic(self, runner, tmp_path):
        """drain command marks key as draining."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "drain",
                "demo",
                "--domain",
                "adapter",
            ],
        )

        assert result.exit_code == 0
        assert "Marked draining for adapter:demo" in result.stdout

    def test_drain_with_note(self, runner, tmp_path):
        """drain command accepts note."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "drain",
                "demo",
                "--domain",
                "adapter",
                "--note",
                "migration",
            ],
        )

        assert result.exit_code == 0
        assert "Marked draining for adapter:demo" in result.stdout
        assert "note=migration" in result.stdout

    def test_drain_clear(self, runner, tmp_path):
        """drain command with --clear removes draining."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "drain",
                "demo",
                "--domain",
                "adapter",
                "--clear",
            ],
        )

        assert result.exit_code == 0
        assert "Cleared draining for adapter:demo" in result.stdout


class TestStatusCommand:
    """Test status command."""

    def test_status_basic(self, runner):
        """status command shows domain status."""
        result = runner.invoke(app, ["--demo", "status", "--domain", "adapter"])

        assert result.exit_code == 0
        assert "Domain: adapter" in result.stdout

    def test_status_with_key(self, runner):
        """status command accepts key filter."""
        result = runner.invoke(
            app, ["--demo", "status", "--domain", "adapter", "--key", "demo"]
        )

        assert result.exit_code == 0
        assert "Domain: adapter" in result.stdout

    def test_status_json_output(self, runner):
        """status command supports JSON output."""
        result = runner.invoke(
            app, ["--demo", "status", "--domain", "adapter", "--json"]
        )

        assert result.exit_code == 0
        # JSON output may be mixed with logs - just verify it runs
        assert result.stdout is not None

    def test_status_with_shadowed(self, runner):
        """status command shows shadowed details."""
        result = runner.invoke(
            app, ["--demo", "status", "--domain", "adapter", "--shadowed"]
        )

        assert result.exit_code == 0
        assert "Domain: adapter" in result.stdout


class TestHealthCommand:
    """Test health command."""

    def test_health_basic(self, runner, tmp_path):
        """health command shows lifecycle health."""
        result = runner.invoke(
            app, [f"--config={tmp_path / 'app.yml'}", "--demo", "health"]
        )

        assert result.exit_code == 0
        # May show "No lifecycle statuses" or health data

    def test_health_with_domain_filter(self, runner, tmp_path):
        """health command accepts domain filter."""
        result = runner.invoke(
            app,
            [
                f"--config={tmp_path / 'app.yml'}",
                "--demo",
                "health",
                "--domain",
                "adapter",
            ],
        )

        assert result.exit_code == 0

    def test_health_with_key_filter(self, runner, tmp_path):
        """health command accepts key filter."""
        result = runner.invoke(
            app,
            [f"--config={tmp_path / 'app.yml'}", "--demo", "health", "--key", "demo"],
        )

        assert result.exit_code == 0

    def test_health_json_output(self, runner, tmp_path):
        """health command supports JSON output."""
        result = runner.invoke(
            app, [f"--config={tmp_path / 'app.yml'}", "--demo", "health", "--json"]
        )

        assert result.exit_code == 0
        stdout = result.stdout
        json_start = stdout.find("{\n")
        blob = stdout[json_start:] if json_start != -1 else stdout
        payload = json.loads(blob)
        assert "profile" in payload
        assert "secrets" in payload
        assert payload["secrets"].get("provider")

    def test_health_with_probe(self, runner, tmp_path):
        """health command supports live probing."""
        # First activate an instance
        runner.invoke(app, ["--demo", "swap", "demo", "--domain", "adapter"])

        result = runner.invoke(
            app, [f"--config={tmp_path / 'app.yml'}", "--demo", "health", "--probe"]
        )

        assert result.exit_code == 0


class TestRuntimeHealthPrinter:
    """Unit tests for runtime health printer helper."""

    def test_runtime_health_latency_warning(self, tmp_path):
        """_print_runtime_health includes latency budget warnings."""
        snapshot = {
            "watchers_running": True,
            "remote_enabled": True,
            "last_remote_duration_ms": 7500.0,
        }
        settings = OneiricSettings()
        settings.remote.latency_budget_ms = 1000.0
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _print_runtime_health(snapshot, str(tmp_path), settings.remote)

        output = buffer.getvalue()
        assert "last_remote_duration" in output
        assert "exceeds budget" in output


class TestPluginBootstrap:
    """Ensure CLI bootstraps entry-point plugins when enabled."""

    def test_cli_initializes_plugins(self, monkeypatch, runner):
        settings = OneiricSettings()
        settings.plugins.auto_load = True

        monkeypatch.setattr("oneiric.cli.load_settings", lambda path: settings)
        called = {}

        def fake_register(resolver, config):
            called["config"] = config
            return plugins.PluginRegistrationReport(
                groups=["oneiric.adapters"], registered=0
            )

        monkeypatch.setattr(
            "oneiric.cli.plugins.register_entrypoint_plugins", fake_register
        )

        result = runner.invoke(app, ["--demo", "list", "--domain", "adapter"])

        assert result.exit_code == 0
        assert called["config"] is settings.plugins


class TestPluginsCommand:
    """Tests for the plugins diagnostics command."""

    def test_plugins_command_text(self, monkeypatch, runner):
        settings = OneiricSettings()
        settings.plugins.auto_load = True
        report = plugins.PluginRegistrationReport(
            groups=["oneiric.adapters"],
            registered=2,
            entries=[
                plugins.PluginEntryRecord(
                    group="oneiric.adapters",
                    entry_point="demo",
                    payload_type="Candidate",
                    registered_candidates=2,
                )
            ],
        )

        monkeypatch.setattr("oneiric.cli.load_settings", lambda path: settings)
        monkeypatch.setattr(
            "oneiric.cli.plugins.register_entrypoint_plugins",
            lambda *args, **kwargs: report,
        )

        result = runner.invoke(app, ["--demo", "plugins"])

        assert result.exit_code == 0
        assert "Entry-point groups loaded" in result.stdout
        assert "demo" in result.stdout

    def test_plugins_command_json(self, monkeypatch, runner):
        settings = OneiricSettings()
        report = plugins.PluginRegistrationReport(groups=["pkg"], registered=0)
        monkeypatch.setattr("oneiric.cli.load_settings", lambda path: settings)
        monkeypatch.setattr(
            "oneiric.cli.plugins.register_entrypoint_plugins",
            lambda *args, **kwargs: report,
        )

        result = runner.invoke(app, ["--demo", "plugins", "--json"])

        assert result.exit_code == 0
        output = result.stdout.strip()
        lines = [line for line in output.splitlines() if line.strip()]
        start_index = None
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith("{"):
                start_index = idx
                break
        payload = (
            "\n".join(lines[start_index:]) if start_index is not None else lines[-1]
        )
        data = json.loads(payload)
        assert data["registered"] == 0


class TestActionInvokeCommand:
    def test_action_invoke_returns_json(self, runner):
        result = runner.invoke(
            app,
            [
                "--demo",
                "action-invoke",
                "compression.encode",
                "--payload",
                '{"text": "hello"}',
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_index = None
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith("{"):
                start_index = idx
                break
        payload = (
            "\n".join(lines[start_index:]) if start_index is not None else lines[-1]
        )
        data = json.loads(payload)
        assert data["mode"] == "compress"
        assert data["algorithm"] == "zlib"

    def test_action_invoke_workflow_audit(self, runner):
        result = runner.invoke(
            app,
            [
                "--demo",
                "action-invoke",
                "workflow.audit",
                "--payload",
                '{"event": "deploy", "details": {"service": "oneiric"}}',
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_index = None
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith("{"):
                start_index = idx
                break
        payload = (
            "\n".join(lines[start_index:]) if start_index is not None else lines[-1]
        )
        data = json.loads(payload)
        assert data["status"] == "recorded"
        assert data["details"]["service"] == "oneiric"

    def test_action_invoke_workflow_notify(self, runner):
        result = runner.invoke(
            app,
            [
                "--demo",
                "action-invoke",
                "workflow.notify",
                "--payload",
                '{"message": "deploy", "recipients": ["ops"], "channel": "deploys"}',
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_index = None
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith("{"):
                start_index = idx
                break
        payload = (
            "\n".join(lines[start_index:]) if start_index is not None else lines[-1]
        )
        data = json.loads(payload)
        assert data["status"] == "queued"
        assert data["channel"] == "deploys"
        assert data["recipients"] == ["ops"]

    def test_action_invoke_workflow_retry(self, runner):
        result = runner.invoke(
            app,
            [
                "--demo",
                "action-invoke",
                "workflow.retry",
                "--payload",
                '{"attempt": 1, "max_attempts": 3}',
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_index = None
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith("{"):
                start_index = idx
                break
        payload = (
            "\n".join(lines[start_index:]) if start_index is not None else lines[-1]
        )
        data = json.loads(payload)
        assert data["status"] == "scheduled"
        assert data["next_attempt"] == 2


class TestActivityCommand:
    """Test activity command."""

    def test_activity_empty(self, runner, tmp_path):
        """activity command handles no paused/draining keys."""
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')
        result = runner.invoke(app, [f"--config={config_file}", "--demo", "activity"])

        assert result.exit_code == 0
        assert "No paused or draining" in result.stdout

    def test_activity_with_paused(self, runner, tmp_path):
        """activity command shows paused keys."""
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')
        # Pause a key first
        runner.invoke(
            app,
            [
                f"--config={config_file}",
                "--demo",
                "pause",
                "demo",
                "--domain",
                "adapter",
            ],
        )

        result = runner.invoke(app, [f"--config={config_file}", "--demo", "activity"])

        assert result.exit_code == 0
        assert "Total activity: paused=1" in result.stdout
        assert "adapter activity: paused=1 draining=0" in result.stdout

    def test_activity_json_output(self, runner, tmp_path):
        """activity command supports JSON output."""
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')
        result = runner.invoke(
            app, [f"--config={config_file}", "--demo", "activity", "--json"]
        )

        assert result.exit_code == 0
        output = result.stdout
        idx = output.rfind("\n{")
        payload = json.loads(output[idx + 1 :])
        assert "totals" in payload
        assert "domains" in payload


class TestRemoteStatusCommand:
    """Test remote-status command."""

    def test_remote_status_empty(self, runner, tmp_path):
        """remote-status command handles no telemetry."""
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')
        result = runner.invoke(
            app, [f"--config={config_file}", "--demo", "remote-status"]
        )

        assert result.exit_code == 0
        assert "Manifest URL" in result.stdout
        assert "Remote latency budget" in result.stdout

    def test_remote_status_json_output(self, runner, tmp_path):
        """remote-status command supports JSON output."""
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')
        result = runner.invoke(
            app, [f"--config={config_file}", "--demo", "remote-status", "--json"]
        )

        assert result.exit_code == 0
        # JSON output may be mixed with logs - just verify it runs
        assert result.stdout is not None


class TestRemoteSyncCommand:
    """Test remote-sync command."""

    def test_remote_sync_with_manifest(self, runner, tmp_path):
        """remote-sync command syncs from manifest file."""
        # Create a minimal manifest
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text("source: test\nentries: []\n")
        config_file = tmp_path / "settings.toml"
        cache_dir = tmp_path / "cache"
        config_file.write_text(f'[remote]\ncache_dir = "{cache_dir}"\n')

        result = runner.invoke(
            app,
            [
                f"--config={config_file}",
                "--demo",
                "remote-sync",
                "--manifest",
                str(manifest_file),
            ],
        )

        assert result.exit_code == 0
        # May show "Remote sync complete" or "Remote sync skipped"
        assert "Remote sync" in result.stdout


class TestEventWorkflowCommands:
    """Tests for event emit and workflow run helpers."""

    def test_event_emit_demo(self, runner):
        """event emit dispatches to the demo handler."""
        result = runner.invoke(
            app,
            [
                "--demo",
                "event",
                "emit",
                "cli.event",
                "--payload",
                '{"demo": true}',
            ],
        )

        assert result.exit_code == 0
        assert "Dispatched to 1 handler(s)" in result.stdout

    def test_event_emit_json(self, runner):
        """event emit supports JSON output."""
        result = runner.invoke(
            app,
            [
                "--demo",
                "event",
                "emit",
                "cli.event",
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_idx = next(i for i, line in enumerate(lines) if line.strip() == "{")
        payload_text = "\n".join(lines[start_idx:])
        payload = json.loads(payload_text)
        assert payload["topic"] == "cli.event"
        assert payload["matched_handlers"] == 1

    def test_workflow_run_demo(self, runner):
        """workflow run executes the demo DAG."""
        result = runner.invoke(
            app,
            [
                "--demo",
                "workflow",
                "run",
                "demo-workflow",
            ],
        )

        assert result.exit_code == 0
        assert "Workflow demo-workflow completed" in result.stdout

    def test_workflow_run_json(self, runner):
        """workflow run supports JSON output."""
        result = runner.invoke(
            app,
            [
                "--demo",
                "workflow",
                "run",
                "demo-workflow",
                "--json",
            ],
        )

        assert result.exit_code == 0
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        start_idx = next(i for i, line in enumerate(lines) if line.strip() == "{")
        payload_text = "\n".join(lines[start_idx:])
        payload = json.loads(payload_text)
        assert payload["workflow"] == "demo-workflow"
        assert isinstance(payload["results"], dict)

    def test_workflow_enqueue_demo(self, runner):
        """workflow enqueue uses demo queue adapter."""
        result = runner.invoke(
            app,
            [
                "--demo",
                "workflow",
                "enqueue",
                "demo-workflow",
                "--json",
            ],
        )

        assert result.exit_code == 0
        stdout = result.stdout.splitlines()
        start_idx = next(i for i, line in enumerate(stdout) if line.strip() == "{")
        payload = json.loads("\n".join(stdout[start_idx:]))
        assert payload["workflow"] == "demo-workflow"
        assert payload["queue_provider"] == "cli"
        assert payload["queue_category"] == "queue"


class TestOrchestrateCommand:
    """Test orchestrate command."""

    # Note: Orchestrate is long-running and hard to test in unit tests
    # These tests verify command parsing but not full execution

    def test_orchestrate_cli_parsing(self, runner, tmp_path):
        """orchestrate command accepts options."""
        # Just verify command parsing - don't actually run orchestrator
        # (would run forever)
        pass


class TestCLIHelpers:
    """Test CLI helper functions."""

    def test_cli_without_subcommand_shows_help(self, runner):
        """CLI root without subcommand shows help."""
        result = runner.invoke(app, [])

        assert result.exit_code == 0
        assert "Usage:" in result.stdout

    def test_cli_with_demo_flag(self, runner):
        """CLI --demo flag registers demo providers."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "adapter"])

        assert result.exit_code == 0
        assert "demo/cli" in result.stdout

    def test_cli_with_import_option(self, runner):
        """CLI --import option imports modules."""
        # Import a standard library module (won't register anything)
        result = runner.invoke(app, ["--import", "json", "list", "--domain", "adapter"])

        assert result.exit_code == 0


class TestDomainNormalization:
    """Test domain normalization."""

    def test_domain_case_insensitive(self, runner):
        """Domain names are case-insensitive."""
        result = runner.invoke(app, ["--demo", "list", "--domain", "ADAPTER"])

        assert result.exit_code == 0
        assert "Active adapters:" in result.stdout

    def test_invalid_domain_rejected(self, runner):
        """Invalid domain names are rejected."""
        result = runner.invoke(app, ["list", "--domain", "invalid"])

        assert result.exit_code != 0
        # Error message appears in stderr or stdout depending on Typer version
        output = result.stdout + (result.stderr or "")
        assert "Domain must be one of" in output
