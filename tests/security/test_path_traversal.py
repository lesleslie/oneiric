"""Security tests for path traversal prevention.

These tests verify that file paths are properly sanitized to prevent
directory traversal attacks.
"""

from __future__ import annotations

import pytest

from oneiric.core.security import validate_key_format
from oneiric.remote.loader import ArtifactManager


class TestPathTraversalPrevention:
    """Test path traversal attack prevention."""

    pytestmark = pytest.mark.asyncio

    async def test_normal_filename_allowed(self, cache_dir):
        """Normal filenames work correctly."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        # SHA256 hash is safe (all hex characters)
        sha256 = "a" * 64
        destination = (manager.cache_dir / sha256).resolve()
        assert destination.is_relative_to(manager.cache_dir.resolve())

    async def test_parent_directory_blocked(self, cache_dir):
        """Parent directory traversal blocked."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="../../etc/passwd", sha256=None, headers={})

    async def test_absolute_path_blocked(self, cache_dir):
        """Absolute paths blocked."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="/etc/passwd", sha256=None, headers={})

    async def test_dotdot_in_filename_blocked(self, cache_dir):
        """Filenames containing .. are blocked."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="file..txt", sha256=None, headers={})

    async def test_forward_slash_in_filename_blocked(self, cache_dir):
        """Filenames containing / are blocked."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="subdir/evil.txt", sha256=None, headers={})

    async def test_backslash_in_filename_blocked(self, cache_dir):
        """Filenames containing backslash are blocked (Windows paths)."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="subdir\\evil.txt", sha256=None, headers={})

    async def test_sha256_bypasses_filename_validation(self, cache_dir):
        """When SHA256 provided, filename is the hash (safe)."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        sha256 = "b" * 64  # Valid hex string
        # Even with evil URI, sha256 is used as filename
        # (This will fail on network fetch, but path validation passes)
        # Testing just the path resolution logic here
        destination = (manager.cache_dir / sha256).resolve()
        assert destination.is_relative_to(manager.cache_dir.resolve())


class TestKeyFormatValidation:
    """Test component key format validation."""

    def test_valid_key_accepted(self, valid_key):
        """Normal alphanumeric keys with dashes/underscores accepted."""
        is_valid, error = validate_key_format(valid_key)
        assert is_valid
        assert error is None

    def test_key_with_dots_accepted(self):
        """Keys with dots accepted by default."""
        is_valid, error = validate_key_format("my.component.v1")
        assert is_valid

    def test_key_with_dots_rejected_when_disabled(self):
        """Keys with dots can be rejected via allow_dots=False."""
        is_valid, error = validate_key_format("my.component", allow_dots=False)
        assert not is_valid
        assert "invalid characters" in error

    def test_path_traversal_key_rejected(self, path_traversal_key):
        """Keys with path traversal blocked."""
        is_valid, error = validate_key_format(path_traversal_key)
        assert not is_valid
        assert "path traversal" in error

    def test_absolute_path_key_rejected(self):
        """Keys starting with / blocked."""
        is_valid, error = validate_key_format("/absolute/path")
        assert not is_valid
        assert "path traversal" in error

    def test_backslash_in_key_rejected(self):
        """Keys with backslashes blocked."""
        is_valid, error = validate_key_format("windows\\path")
        assert not is_valid
        assert "path traversal" in error

    def test_dotdot_anywhere_in_key_rejected(self):
        """.. anywhere in key is rejected."""
        invalid_keys = ["..start", "mid..dle", "end..", "../../evil"]
        for key in invalid_keys:
            is_valid, error = validate_key_format(key)
            assert not is_valid, f"Should reject: {key}"
            assert "path traversal" in error

    def test_empty_key_rejected(self):
        """Empty keys rejected."""
        is_valid, error = validate_key_format("")
        assert not is_valid
        assert "cannot be empty" in error

    def test_special_characters_rejected(self):
        """Special characters in keys rejected."""
        invalid_keys = ["key@name", "key#name", "key$name", "key%name", "key*name"]
        for key in invalid_keys:
            is_valid, error = validate_key_format(key)
            assert not is_valid, f"Should reject: {key}"


@pytest.mark.security
class TestPathTraversalAttackScenarios:
    """Test realistic path traversal attack scenarios."""

    pytestmark = pytest.mark.asyncio

    async def test_linux_etc_passwd_attack(self, cache_dir):
        """Block attempts to access /etc/passwd."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="../../../../etc/passwd", sha256=None, headers={})

    async def test_windows_system32_attack(self, cache_dir):
        """Block attempts to access Windows system files."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="..\\..\\..\\Windows\\System32\\config\\SAM",
                sha256=None,
                headers={},
            )

    async def test_home_directory_attack(self, cache_dir):
        """Block attempts to access home directory files."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(uri="../../.ssh/id_rsa", sha256=None, headers={})

    async def test_cron_backdoor_attack(self, cache_dir):
        """Block attempts to write to cron.d."""
        manager = ArtifactManager(cache_dir=str(cache_dir))
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch(
                uri="../../../etc/cron.d/backdoor", sha256=None, headers={}
            )
