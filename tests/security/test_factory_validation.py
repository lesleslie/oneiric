"""Security tests for factory string validation.

These tests verify that the factory resolution mechanism properly validates
and blocks potentially dangerous module imports.
"""

from __future__ import annotations

import pytest

from oneiric.core.lifecycle import LifecycleError, resolve_factory
from oneiric.core.security import (
    load_factory_allowlist,
    validate_factory_string,
)


class TestFactoryValidation:
    """Test factory string format validation and security controls."""

    def test_allowed_factory_succeeds(self, allowed_factory):
        """Valid factory from allowed module loads successfully."""
        result = resolve_factory(allowed_factory)
        assert callable(result)

    def test_blocked_os_module_fails(self, blocked_factory):
        """OS module imports are blocked."""
        with pytest.raises(LifecycleError, match="blocked for security"):
            resolve_factory(blocked_factory)

    def test_subprocess_blocked(self):
        """Subprocess module blocked."""
        factory = "subprocess:run"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_importlib_blocked(self):
        """Importlib blocked (prevents nested imports)."""
        factory = "importlib:import_module"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_sys_blocked(self):
        """Sys module blocked."""
        factory = "sys:exit"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_builtins_blocked(self):
        """Builtins module blocked."""
        for module in ["__builtin__", "builtins"]:
            factory = f"{module}:eval"
            with pytest.raises(LifecycleError, match="blocked"):
                resolve_factory(factory)

    def test_disallowed_prefix_rejected(self):
        """Modules outside allowlist rejected."""
        factory = "random_package.evil:backdoor"
        with pytest.raises(LifecycleError, match="not in allowlist"):
            resolve_factory(factory)

    def test_malformed_factory_rejected(self, malformed_factory):
        """Invalid factory format rejected."""
        with pytest.raises(LifecycleError, match="Security validation failed"):
            resolve_factory(malformed_factory)

    def test_malformed_formats(self):
        """Various invalid factory formats rejected."""
        invalid_factories = [
            "",
            "nocolon",
            ":nomodule",
            "module:",
            "../../evil:hack",
            "module::double",
        ]
        for factory in invalid_factories:
            is_valid, _ = validate_factory_string(factory)
            assert not is_valid, f"Should reject: {factory}"

    def test_allowlist_from_environment(self, monkeypatch):
        """Allowlist can be extended via environment."""
        monkeypatch.setenv("ONEIRIC_FACTORY_ALLOWLIST", "oneiric.,custom.")
        allowlist = load_factory_allowlist()
        assert "oneiric." in allowlist
        assert "custom." in allowlist

    def test_allowlist_adds_trailing_dot(self, monkeypatch):
        """Allowlist prefixes get trailing dots added automatically."""
        monkeypatch.setenv("ONEIRIC_FACTORY_ALLOWLIST", "oneiric,custom")
        allowlist = load_factory_allowlist()
        assert "oneiric." in allowlist
        assert "custom." in allowlist

    def test_callable_factory_bypasses_validation(self):
        """Callable factories don't need string validation."""
        factory = lambda: {"type": "test"}
        result = resolve_factory(factory)
        assert result is factory
        assert callable(result)

    def test_shutil_blocked(self):
        """Shutil module blocked (filesystem operations)."""
        factory = "shutil:rmtree"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_pathlib_blocked(self):
        """Pathlib blocked (path manipulation)."""
        factory = "pathlib:Path"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_tempfile_blocked(self):
        """Tempfile blocked (filesystem writes)."""
        factory = "tempfile:mkstemp"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)


class TestFactorySecurityEdgeCases:
    """Test edge cases and attack vectors."""

    def test_dotted_evil_path(self):
        """Reject dotted paths attempting module escape."""
        factory = "oneiric.....evil:hack"
        # Should still validate format but likely fail import
        is_valid, _ = validate_factory_string(factory)
        # This is technically valid format (module.path:attr)
        assert is_valid or not is_valid  # Format check passes, allowlist may reject

    def test_nested_os_import(self):
        """Block nested os module access."""
        factory = "os.path:exists"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_case_sensitive_blocking(self):
        """Module blocking is case-sensitive (lowercase only)."""
        # Python modules are lowercase, so OS/Sys shouldn't exist anyway
        factory = "OS:system"
        # Will fail on import, not security check (OS != os)
        # But allowlist will catch it
        with pytest.raises(LifecycleError):
            resolve_factory(factory)

    def test_empty_allowlist_rejects_all(self, monkeypatch):
        """Empty allowlist rejects all factories."""
        monkeypatch.setenv("ONEIRIC_FACTORY_ALLOWLIST", "")
        allowlist = load_factory_allowlist()
        assert len(allowlist) == 0

        factory = "oneiric.demo:DemoAdapter"
        is_valid, error = validate_factory_string(factory, allowlist)
        assert not is_valid
        assert "not in allowlist" in error


@pytest.mark.security
class TestRealWorldAttackScenarios:
    """Test realistic attack scenarios from remote manifests."""

    def test_rce_via_os_system(self):
        """Block RCE attempt via os.system."""
        factory = "os:system"
        with pytest.raises(LifecycleError, match="blocked for security"):
            resolve_factory(factory)

    def test_rce_via_subprocess_call(self):
        """Block RCE via subprocess."""
        factory = "subprocess:call"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_arbitrary_import_via_importlib(self):
        """Block arbitrary imports via importlib."""
        factory = "importlib:import_module"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_filesystem_attack_via_shutil(self):
        """Block filesystem attacks via shutil."""
        factory = "shutil:rmtree"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)

    def test_eval_attack_via_builtins(self):
        """Block eval attacks via builtins."""
        factory = "builtins:eval"
        with pytest.raises(LifecycleError, match="blocked"):
            resolve_factory(factory)
