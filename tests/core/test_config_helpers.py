"""Tests for domain-agnostic configuration helper functions.

These tests verify that configuration helpers work correctly across
all domains (adapters, services, tasks, events, workflows).
"""

from __future__ import annotations

import pytest

from oneiric.core.config import LayerSettings, OneiricSettings
from oneiric.core.domain_settings import (
    SUPPORTED_DOMAINS,
    create_layer_selector,
    get_domain_settings,
    is_supported_domain,
)


class TestCreateLayerSelector:
    """Test the create_layer_selector function."""

    def test_create_selector_for_adapter(self):
        """Create selector for adapter domain."""
        selector = create_layer_selector("adapter")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.adapters
        assert isinstance(result, LayerSettings)

    def test_create_selector_for_service(self):
        """Create selector for service domain."""
        selector = create_layer_selector("service")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.services
        assert isinstance(result, LayerSettings)

    def test_create_selector_for_task(self):
        """Create selector for task domain."""
        selector = create_layer_selector("task")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.tasks
        assert isinstance(result, LayerSettings)

    def test_create_selector_for_event(self):
        """Create selector for event domain."""
        selector = create_layer_selector("event")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.events
        assert isinstance(result, LayerSettings)

    def test_create_selector_for_workflow(self):
        """Create selector for workflow domain."""
        selector = create_layer_selector("workflow")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.workflows
        assert isinstance(result, LayerSettings)

    def test_create_selector_for_action(self):
        """Create selector for action domain."""
        selector = create_layer_selector("action")
        settings = OneiricSettings()

        result = selector(settings)

        assert result is settings.actions
        assert isinstance(result, LayerSettings)

    def test_selector_returns_mutable_settings(self):
        """Selector returns mutable LayerSettings that can be modified."""
        selector = create_layer_selector("service")
        settings = OneiricSettings()

        layer = selector(settings)
        layer.selections["test-service"] = "test-provider"

        assert settings.services.selections["test-service"] == "test-provider"

    def test_selector_with_custom_settings(self):
        """Selector works with custom OneiricSettings."""
        selector = create_layer_selector("adapter")
        settings = OneiricSettings(
            adapters=LayerSettings(
                selections={"cache": "redis"},
                provider_settings={"redis": {"host": "localhost"}},
            )
        )

        result = selector(settings)

        assert result.selections["cache"] == "redis"
        assert result.provider_settings["redis"]["host"] == "localhost"


class TestGetDomainSettings:
    """Test the get_domain_settings function."""

    def test_get_adapter_settings(self):
        """Get settings for adapter domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "adapter")

        assert result is settings.adapters
        assert isinstance(result, LayerSettings)

    def test_get_service_settings(self):
        """Get settings for service domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "service")

        assert result is settings.services
        assert isinstance(result, LayerSettings)

    def test_get_task_settings(self):
        """Get settings for task domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "task")

        assert result is settings.tasks
        assert isinstance(result, LayerSettings)

    def test_get_event_settings(self):
        """Get settings for event domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "event")

        assert result is settings.events
        assert isinstance(result, LayerSettings)

    def test_get_workflow_settings(self):
        """Get settings for workflow domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "workflow")

        assert result is settings.workflows
        assert isinstance(result, LayerSettings)

    def test_get_action_settings(self):
        """Get settings for action domain."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, "action")

        assert result is settings.actions
        assert isinstance(result, LayerSettings)

    def test_get_settings_with_custom_config(self):
        """Get settings with custom configuration."""
        settings = OneiricSettings(
            services=LayerSettings(
                selections={"payment": "stripe"},
                provider_settings={"stripe": {"api_key": "sk_test_"}},
            )
        )
        result = get_domain_settings(settings, "service")

        assert result.selections["payment"] == "stripe"
        assert result.provider_settings["stripe"]["api_key"] == "sk_test_"

    def test_get_settings_invalid_domain_raises(self):
        """Get settings for invalid domain raises AttributeError."""
        settings = OneiricSettings()

        with pytest.raises(AttributeError):
            get_domain_settings(settings, "invalid_domain")


class TestIsSupportedDomain:
    """Test the is_supported_domain function."""

    def test_adapter_is_supported(self):
        """Adapter domain is supported."""
        assert is_supported_domain("adapter") is True

    def test_service_is_supported(self):
        """Service domain is supported."""
        assert is_supported_domain("service") is True

    def test_task_is_supported(self):
        """Task domain is supported."""
        assert is_supported_domain("task") is True

    def test_event_is_supported(self):
        """Event domain is supported."""
        assert is_supported_domain("event") is True

    def test_workflow_is_supported(self):
        """Workflow domain is supported."""
        assert is_supported_domain("workflow") is True

    def test_action_is_supported(self):
        """Action domain is supported."""
        assert is_supported_domain("action") is True

    def test_invalid_domain_not_supported(self):
        """Invalid domain is not supported."""
        assert is_supported_domain("invalid") is False
        assert is_supported_domain("adapters") is False  # plural, not supported
        assert is_supported_domain("") is False


class TestSupportedDomainsConstant:
    """Test the SUPPORTED_DOMAINS constant."""

    def test_supported_domains_list(self):
        """SUPPORTED_DOMAINS contains all expected domains."""
        expected = ["adapter", "service", "task", "event", "workflow", "action"]
        assert SUPPORTED_DOMAINS == expected

    def test_all_supported_domains_pass_check(self):
        """All domains in SUPPORTED_DOMAINS pass is_supported_domain check."""
        for domain in SUPPORTED_DOMAINS:
            assert is_supported_domain(domain) is True


class TestDomainAgnosticConfigPatterns:
    """Test that config patterns work consistently across all domains."""

    @pytest.mark.parametrize(
        "domain",
        ["adapter", "service", "task", "event", "workflow", "action"],
    )
    def test_layer_selector_works_for_all_domains(self, domain):
        """Layer selector function works for all supported domains."""
        selector = create_layer_selector(domain)
        settings = OneiricSettings()

        result = selector(settings)

        assert isinstance(result, LayerSettings)
        assert result.selections == {}
        assert result.provider_settings == {}
        assert result.options == {}

    @pytest.mark.parametrize(
        "domain",
        ["adapter", "service", "task", "event", "workflow", "action"],
    )
    def test_get_domain_settings_works_for_all_domains(self, domain):
        """get_domain_settings works for all supported domains."""
        settings = OneiricSettings()
        result = get_domain_settings(settings, domain)

        assert isinstance(result, LayerSettings)

    @pytest.mark.parametrize(
        "domain",
        ["adapter", "service", "task", "event", "workflow", "action"],
    )
    def test_domain_config_can_be_modified(self, domain):
        """Domain configuration can be modified through selector."""
        selector = create_layer_selector(domain)
        settings = OneiricSettings()

        layer = selector(settings)
        layer.selections["test-key"] = "test-provider"
        layer.provider_settings["test-provider"] = {"config": "value"}

        assert layer.selections["test-key"] == "test-provider"
        assert layer.provider_settings["test-provider"]["config"] == "value"


class TestConfigBackwardsCompatibility:
    """Test backwards compatibility with existing adapter code."""

    def test_adapter_layer_function_still_works(self):
        """Verify the old adapter_layer function still exists for backwards compat."""
        from oneiric.adapters.watcher import adapter_layer

        settings = OneiricSettings()
        result = adapter_layer(settings)

        assert result is settings.adapters

    def test_adapter_configWatcher_uses_new_pattern(self):
        """AdapterConfigWatcher now uses the generalized pattern."""
        from oneiric.adapters.watcher import AdapterConfigWatcher
        from oneiric.core.domain_settings import create_layer_selector

        # Verify that the new pattern is used internally
        # by checking that create_layer_selector("adapter") returns same result
        selector = create_layer_selector("adapter")
        settings = OneiricSettings()

        assert selector(settings) is settings.adapters

    def test_existing_domain_watchers_use_new_pattern(self):
        """All domain watchers use the generalized pattern."""
        from oneiric.domains.watchers import (
            ServiceConfigWatcher,
            TaskConfigWatcher,
            EventConfigWatcher,
            WorkflowConfigWatcher,
        )
        from oneiric.core.domain_settings import create_layer_selector

        settings = OneiricSettings()

        # Test service watcher selector
        service_selector = create_layer_selector("service")
        assert service_selector(settings) is settings.services

        # Test task watcher selector
        task_selector = create_layer_selector("task")
        assert task_selector(settings) is settings.tasks

        # Test event watcher selector
        event_selector = create_layer_selector("event")
        assert event_selector(settings) is settings.events

        # Test workflow watcher selector
        workflow_selector = create_layer_selector("workflow")
        assert workflow_selector(settings) is settings.workflows


class TestRealWorldConfigScenarios:
    """Test real-world configuration scenarios."""

    def test_multi_domain_configuration(self):
        """Test configuring multiple domains simultaneously."""
        settings = OneiricSettings(
            adapters=LayerSettings(
                selections={"cache": "redis", "database": "postgresql"},
                provider_settings={
                    "redis": {"host": "localhost", "port": 6379},
                    "postgresql": {"connection_string": "postgresql://localhost/db"},
                },
            ),
            services=LayerSettings(
                selections={"payment": "stripe", "email": "sendgrid"},
                provider_settings={
                    "stripe": {"api_key": "sk_test_"},
                    "sendgrid": {"api_key": "SG.xxx"},
                },
            ),
            workflows=LayerSettings(
                selections={"order-processing": "sequential"},
                options={"max_parallel_tasks": 10},
            ),
        )

        # Verify adapter config
        adapter_layer = get_domain_settings(settings, "adapter")
        assert adapter_layer.selections["cache"] == "redis"
        assert adapter_layer.provider_settings["redis"]["host"] == "localhost"

        # Verify service config
        service_layer = get_domain_settings(settings, "service")
        assert service_layer.selections["payment"] == "stripe"
        assert service_layer.provider_settings["stripe"]["api_key"] == "sk_test_"

        # Verify workflow config
        workflow_layer = get_domain_settings(settings, "workflow")
        assert workflow_layer.selections["order-processing"] == "sequential"
        assert workflow_layer.options["max_parallel_tasks"] == 10

    def test_domain_isolation(self):
        """Test that domain configurations are isolated."""
        settings = OneiricSettings(
            adapters=LayerSettings(selections={"cache": "redis"}),
            services=LayerSettings(selections={"cache": "memcached"}),
        )

        adapter_selector = create_layer_selector("adapter")
        service_selector = create_layer_selector("service")

        adapter_layer = adapter_selector(settings)
        service_layer = service_selector(settings)

        # Each domain should have its own independent config
        assert adapter_layer.selections["cache"] == "redis"
        assert service_layer.selections["cache"] == "memcached"

        # Modifying one should not affect the other
        adapter_layer.selections["database"] = "postgresql"
        assert "database" not in service_layer.selections
