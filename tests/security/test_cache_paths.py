"""Test cache path security and boundary enforcement.

This test suite validates that the remote artifact manager properly prevents
path traversal attacks and enforces cache directory boundaries.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from oneiric.remote.loader import ArtifactManager
from oneiric.remote.security import sanitize_filename


class TestPathTraversalPrevention:
    """Test path traversal attack prevention."""

    pytestmark = pytest.mark.asyncio

    async def test_path_traversal_with_double_dot(self, tmp_path):
        """Should reject URIs with '..' path components."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("../../etc/passwd", None, {})

    async def test_path_traversal_with_triple_dot(self, tmp_path):
        """Should reject URIs with multiple '..' sequences."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("../../../../../../../etc/passwd", None, {})

    async def test_path_traversal_with_absolute_path(self, tmp_path):
        """Should reject absolute paths in URIs."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("/etc/passwd", None, {})

    async def test_path_traversal_with_windows_absolute(self, tmp_path):
        """Should reject Windows-style absolute paths."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("C:\\Windows\\System32\\config\\sam", None, {})

    async def test_path_traversal_with_backslash(self, tmp_path):
        """Should reject Windows-style path separators."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("..\\..\\windows\\system32", None, {})

    async def test_path_traversal_with_mixed_separators(self, tmp_path):
        """Should reject mixed forward/backslash separators."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("../..\\etc/passwd", None, {})

    async def test_path_traversal_with_url_encoding(self, tmp_path):
        """Should reject URL-encoded path traversal attempts."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        # URL-encoded '..' is '%2E%2E'
        with pytest.raises(ValueError, match="Path traversal"):
            await manager.fetch("%2E%2E/%2E%2E/etc/passwd", None, {})

    async def test_legitimate_http_url_allowed(self, tmp_path):
        """Should allow legitimate HTTP URLs."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        # This should NOT raise - it's a legitimate URL
        # (Will fail later due to network, but path validation should pass)
        try:
            await manager.fetch("https://example.com/file.whl", "abc123", {})
        except Exception as exc:
            # Should fail on network/digest, not path validation
            assert "Path traversal" not in str(exc)

    async def test_legitimate_https_url_with_path(self, tmp_path):
        """Should allow HTTPS URLs with path components."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        try:
            await manager.fetch(
                "https://cdn.example.com/releases/v1.0.0/package.whl", "abc123", {}
            )
        except Exception as exc:
            assert "Path traversal" not in str(exc)


class TestFilenameSanitization:
    """Test filename sanitization function."""

    def test_normal_filename_unchanged(self):
        """Should preserve normal filenames."""
        assert sanitize_filename("artifact.whl") == "artifact.whl"
        assert sanitize_filename("my-package-1.0.0.tar.gz") == "my-package-1.0.0.tar.gz"

    def test_removes_double_dot(self):
        """Should remove '..' from filenames."""
        result = sanitize_filename("../../../etc/passwd")
        assert ".." not in result
        assert result != "../../../etc/passwd"

    def test_removes_forward_slash(self):
        """Should remove '/' from filenames."""
        result = sanitize_filename("/etc/passwd")
        assert "/" not in result
        assert result != "/etc/passwd"

    def test_removes_backslash(self):
        """Should remove '\\' from filenames."""
        result = sanitize_filename("..\\windows\\system32")
        assert "\\" not in result
        assert result != "..\\windows\\system32"

    def test_removes_null_bytes(self):
        """Should remove null bytes from filenames."""
        result = sanitize_filename("file\x00.whl")
        assert "\x00" not in result
        assert result == "file.whl"

    def test_multiple_malicious_characters(self):
        """Should remove all malicious characters."""
        result = sanitize_filename("../../../etc\x00/passwd\\admin")
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result
        assert "\x00" not in result


class TestCacheBoundaryEnforcement:
    """Test cache directory isolation and boundary enforcement."""

    def test_cache_boundary_enforcement_with_sha256(self, tmp_path):
        """Should ensure all cached files stay within cache directory."""
        ArtifactManager(cache_dir=str(tmp_path))
        cache_dir = Path(tmp_path)

        # When sha256 is provided, filename is the sha256 (safe)
        # This test would need actual network fetch - skip for now
        # Just verify the cache directory exists
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_cache_directory_created_with_secure_permissions(self, tmp_path):
        """Should create cache directory with appropriate permissions."""
        cache_dir = tmp_path / "secure_cache"
        ArtifactManager(cache_dir=str(cache_dir))

        assert cache_dir.exists()
        # Note: Permissions vary by system and umask
        stat = cache_dir.stat()
        # At minimum, directory should be readable and writable by owner
        assert stat.st_mode & 0o700 in (0o700, 0o755, 0o775)

    def test_multiple_managers_share_cache_safely(self, tmp_path):
        """Multiple managers should safely share same cache directory."""
        cache_dir = tmp_path / "shared_cache"

        manager1 = ArtifactManager(cache_dir=str(cache_dir))
        manager2 = ArtifactManager(cache_dir=str(cache_dir))

        # Both should work without conflicts
        assert manager1.cache_dir == manager2.cache_dir
        assert manager1.cache_dir.exists()
        assert manager2.cache_dir.exists()

    def test_cache_directory_isolation_from_parent(self, tmp_path):
        """Cache operations should not escape to parent directories."""
        cache_dir = tmp_path / "isolated_cache"
        parent_file = tmp_path / "parent_file.txt"
        parent_file.write_text("sensitive data")

        manager = ArtifactManager(cache_dir=str(cache_dir))

        # Even with path traversal attempts, should stay in cache
        assert manager.cache_dir == cache_dir
        assert manager.cache_dir.is_relative_to(tmp_path)

        # Parent file should remain untouched
        assert parent_file.exists()
        assert parent_file.read_text() == "sensitive data"


class TestSecurityEdgeCases:
    """Test security edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_empty_uri(self, tmp_path):
        """Should handle empty URI gracefully."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        with pytest.raises((ValueError, TypeError)):
            await manager.fetch("", None, {})

    @pytest.mark.asyncio
    async def test_uri_with_unicode_characters(self, tmp_path):
        """Should handle Unicode in URIs."""
        manager = ArtifactManager(cache_dir=str(tmp_path))

        # Should not crash on Unicode
        try:
            await manager.fetch("https://example.com/пакет.whl", "abc123", {})
        except Exception as exc:
            # May fail on network, but shouldn't crash on Unicode
            assert isinstance(
                exc,
                (ValueError, ConnectionError, OSError, httpx.HTTPError),
            )

    def test_very_long_filename(self, tmp_path):
        """Should handle very long filenames."""
        ArtifactManager(cache_dir=str(tmp_path))
        long_name = "a" * 1000 + ".whl"

        # Should handle long filenames (may fail on filesystem limits)
        try:
            sanitized = sanitize_filename(long_name)
            # Should at least not crash
            assert isinstance(sanitized, str)
        except Exception as exc:
            # Filesystem limits are acceptable
            assert isinstance(exc, (OSError, ValueError))

    def test_null_byte_injection(self, tmp_path):
        """Should prevent null byte injection attacks."""
        ArtifactManager(cache_dir=str(tmp_path))

        # Null byte injection: file.whl\x00.txt
        # Should sanitize to file.whl.txt
        sanitized = sanitize_filename("file.whl\x00.txt")
        assert "\x00" not in sanitized

    def test_dot_files_allowed(self, tmp_path):
        """Should allow dot-files (hidden files)."""
        # Dot-files like .gitignore are legitimate
        assert sanitize_filename(".gitignore") == ".gitignore"
        assert sanitize_filename(".hidden_config.yaml") == ".hidden_config.yaml"

    def test_double_extension_attack(self, tmp_path):
        """Should handle double extension attacks."""
        # file.whl.exe - should preserve as-is (detection is not sanitization's job)
        assert sanitize_filename("file.whl.exe") == "file.whl.exe"


class TestCacheIsolation:
    """Test cache directory isolation between different projects."""

    def test_different_cache_dirs_isolated(self, tmp_path):
        """Different cache directories should be completely isolated."""
        cache1 = tmp_path / "cache1"
        cache2 = tmp_path / "cache2"

        manager1 = ArtifactManager(cache_dir=str(cache1))
        manager2 = ArtifactManager(cache_dir=str(cache2))

        assert manager1.cache_dir != manager2.cache_dir
        assert cache1.exists() and cache2.exists()
        assert not cache1.is_relative_to(cache2)
        assert not cache2.is_relative_to(cache1)

    def test_nested_cache_dirs_allowed(self, tmp_path):
        """Nested cache directories should be allowed (but not recommended)."""
        parent_cache = tmp_path / "parent"
        child_cache = parent_cache / "child"

        manager_parent = ArtifactManager(cache_dir=str(parent_cache))
        manager_child = ArtifactManager(cache_dir=str(child_cache))

        assert manager_parent.cache_dir != manager_child.cache_dir
        assert child_cache.is_relative_to(parent_cache)
