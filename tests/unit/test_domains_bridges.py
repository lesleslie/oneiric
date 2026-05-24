"""Gap-fill tests for domains: services, tasks, and watchers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestServiceBridgeInit:
    def test_passes_service_domain_to_base(self) -> None:
        """ServiceBridge.__init__ calls super().__init__ with 'service' — line 21."""
        from oneiric.domains.base import DomainBridge
        from oneiric.domains.services import ServiceBridge

        with patch.object(DomainBridge, "__init__", return_value=None) as mock_init:
            resolver = MagicMock()
            lifecycle = MagicMock()
            settings = MagicMock()
            activity_store = MagicMock()
            supervisor = MagicMock()

            ServiceBridge(
                resolver,
                lifecycle,
                settings,
                activity_store=activity_store,
                supervisor=supervisor,
            )

        mock_init.assert_called_once_with(
            "service",
            resolver,
            lifecycle,
            settings,
            activity_store=activity_store,
            supervisor=supervisor,
        )


class TestTaskBridgeInit:
    def test_passes_task_domain_to_base(self) -> None:
        """TaskBridge.__init__ calls super().__init__ with 'task' — line 21."""
        from oneiric.domains.base import DomainBridge
        from oneiric.domains.tasks import TaskBridge

        with patch.object(DomainBridge, "__init__", return_value=None) as mock_init:
            resolver = MagicMock()
            lifecycle = MagicMock()
            settings = MagicMock()

            TaskBridge(resolver, lifecycle, settings)

        mock_init.assert_called_once_with(
            "task",
            resolver,
            lifecycle,
            settings,
            activity_store=None,
            supervisor=None,
        )


class TestLayerSelectorAndWatcherInits:
    def test_layer_selector_returns_correct_attribute(self) -> None:
        """_layer_selector closure returns getattr(settings, '{name}s') — lines 13-16."""
        from oneiric.domains.watchers import _layer_selector

        mock_settings = MagicMock()
        mock_settings.services = ["svc1", "svc2"]

        selector = _layer_selector("service")
        result = selector(mock_settings)
        assert result == mock_settings.services

    def test_service_config_watcher_init(self) -> None:
        """ServiceConfigWatcher passes 'service' to SelectionWatcher — line 27."""
        from oneiric.domains.watchers import ServiceConfigWatcher
        from oneiric.runtime.watchers import SelectionWatcher

        with patch.object(SelectionWatcher, "__init__", return_value=None) as mock_init:
            bridge = MagicMock()
            ServiceConfigWatcher(bridge)

        args, kwargs = mock_init.call_args
        assert args[0] == "service"
        assert args[1] is bridge

    def test_task_config_watcher_init(self) -> None:
        """TaskConfigWatcher passes 'task' to SelectionWatcher — line 44."""
        from oneiric.domains.watchers import TaskConfigWatcher
        from oneiric.runtime.watchers import SelectionWatcher

        with patch.object(SelectionWatcher, "__init__", return_value=None) as mock_init:
            bridge = MagicMock()
            TaskConfigWatcher(bridge)

        args, _ = mock_init.call_args
        assert args[0] == "task"

    def test_event_config_watcher_init(self) -> None:
        """EventConfigWatcher passes 'event' + refresh_on_every_tick=True — line 61."""
        from oneiric.domains.watchers import EventConfigWatcher
        from oneiric.runtime.watchers import SelectionWatcher

        with patch.object(SelectionWatcher, "__init__", return_value=None) as mock_init:
            bridge = MagicMock()
            EventConfigWatcher(bridge)

        args, kwargs = mock_init.call_args
        assert args[0] == "event"
        assert kwargs.get("refresh_on_every_tick") is True

    def test_workflow_config_watcher_init(self) -> None:
        """WorkflowConfigWatcher passes 'workflow' + refresh_on_every_tick=True — line 79."""
        from oneiric.domains.watchers import WorkflowConfigWatcher
        from oneiric.runtime.watchers import SelectionWatcher

        with patch.object(SelectionWatcher, "__init__", return_value=None) as mock_init:
            bridge = MagicMock()
            WorkflowConfigWatcher(bridge)

        args, kwargs = mock_init.call_args
        assert args[0] == "workflow"
        assert kwargs.get("refresh_on_every_tick") is True


class TestModeUtilsConfigFilePath:
    def test_load_mode_config_file_found_in_package_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_mode_config_file returns path when config/mode.yaml exists — line 101."""
        import oneiric
        from oneiric.modes.utils import load_mode_config_file

        # Work from a directory without a local config/ so the CWD check doesn't fire
        empty_cwd = tmp_path / "empty_cwd"
        empty_cwd.mkdir()
        monkeypatch.chdir(empty_cwd)

        # Build a fake package layout: pkg_root/oneiric/__init__.py
        # so that Path(oneiric.__file__).parent.parent == pkg_root
        pkg_root = tmp_path / "pkg_root"
        fake_oneiric_dir = pkg_root / "oneiric"
        fake_oneiric_dir.mkdir(parents=True)
        (fake_oneiric_dir / "__init__.py").write_text("")

        config_dir = pkg_root / "config"
        config_dir.mkdir()
        config_file = config_dir / "lite.yaml"
        config_file.write_text("name: lite\n")

        with patch.object(oneiric, "__file__", str(fake_oneiric_dir / "__init__.py")):
            result = load_mode_config_file("lite")

        assert result == config_file
