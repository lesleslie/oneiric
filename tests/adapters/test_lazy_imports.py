"""Tests for the lazy adapter-package imports.

Importing ``oneiric.adapters`` used to execute the whole resolution
stack (``bootstrap`` -> ``core.config`` -> ``mcp.config`` -> ``mcp``),
and every family package eagerly imported all of its adapters. That cost
~3 s for ``import oneiric.adapters`` and ~4 s for
``import oneiric.adapters.queue``.

The tax was not optional: Python executes every parent package's
``__init__`` on the way down, so importing one concrete adapter paid for
its whole family. Claude Code hooks that publish one bus event per tool
call paid it on the tool-call critical path.

These tests pin the contract: the packages stay cheap to import, and the
re-exported names still resolve to the same objects.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _modules_loaded(import_stmt: str) -> set[str]:
    """Return the modules loaded after running *import_stmt* in a clean process."""
    code = f"import sys\n{import_stmt}\nprint('\\n'.join(sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.split())


class TestAdaptersPackageIsLazy:
    def test_importing_the_package_does_not_load_the_resolution_stack(self) -> None:
        """``import oneiric.adapters`` must not drag in the mcp stack."""
        loaded = _modules_loaded("import oneiric.adapters")

        assert "oneiric.adapters.bridge" not in loaded
        assert "oneiric.adapters.bootstrap" not in loaded
        assert "oneiric.mcp" not in loaded

    def test_exported_names_still_resolve(self) -> None:
        """The lazy re-exports point at the same classes as before."""
        from oneiric.adapters import AdapterBridge, AdapterMetadata
        from oneiric.adapters.bridge import AdapterBridge as BridgeFromModule

        assert AdapterBridge is BridgeFromModule
        assert AdapterMetadata.__name__ == "AdapterMetadata"

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """A name that is not exported raises, rather than resolving to None."""
        import oneiric.adapters

        with pytest.raises(AttributeError):
            oneiric.adapters.NotARealAdapter  # noqa: B018

    def test_dir_advertises_the_exports(self) -> None:
        """``dir()`` lists the lazy exports so tab-completion works."""
        import oneiric.adapters

        assert "AdapterBridge" in dir(oneiric.adapters)
        assert "bootstrap" in dir(oneiric.adapters)


class TestFamilyPackagesAreLazy:
    def test_queue_package_does_not_load_the_sibling_queues(self) -> None:
        """Importing one queue adapter must not pull Kafka or RabbitMQ in."""
        loaded = _modules_loaded(
            "import oneiric.adapters.queue.redis_streams",
        )

        assert "oneiric.adapters.queue.kafka" not in loaded
        assert "oneiric.adapters.queue.rabbitmq" not in loaded
        assert "oneiric.adapters.queue.nats" not in loaded

    def test_storage_package_does_not_load_the_cloud_sdks(self) -> None:
        """Importing the storage family stays cheap."""
        loaded = _modules_loaded("import oneiric.adapters.storage")

        assert "oneiric.adapters.storage.s3" not in loaded
        assert "oneiric.adapters.storage.azure" not in loaded

    def test_bootstrap_import_is_cheap(self) -> None:
        """``bootstrap`` only pulls the catalogue when it is asked for."""
        loaded = _modules_loaded("import oneiric.adapters.bootstrap")

        assert "oneiric.adapters.queue.kafka" not in loaded
        assert "oneiric.adapters.storage.s3" not in loaded


class TestExportedNamesResolve:
    @pytest.mark.parametrize(
        ("package", "name"),
        [
            ("oneiric.adapters.queue", "RedisStreamsQueueAdapter"),
            ("oneiric.adapters.queue", "RedisStreamsQueueSettings"),
            ("oneiric.adapters.storage", "S3StorageAdapter"),
            ("oneiric.adapters.http", "HTTPClientAdapter"),
            ("oneiric.adapters.llm", "AnthropicLLM"),
        ],
    )
    def test_from_package_import_name_works(self, package: str, name: str) -> None:
        """``from <family> import <Name>`` resolves through the lazy path."""
        namespace: dict[str, object] = {}
        exec(f"from {package} import {name}", namespace)  # noqa: S102

        assert namespace[name].__name__ == name

    def test_lavinmq_queue_settings_alias_resolves(self) -> None:
        """``__all__`` has advertised ``LavinMQQueueSettings`` since the
        family was added, but the class is named ``LavinMQSettings`` -- so
        the import raised ImportError. The advertised name resolves now.
        """
        from oneiric.adapters.queue import LavinMQQueueSettings, LavinMQSettings

        assert LavinMQQueueSettings is LavinMQSettings
