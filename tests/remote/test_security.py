"""Tests for remote manifest signature verification."""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from oneiric.remote.security import (
    get_canonical_manifest_for_signing,
    load_trusted_public_keys,
    sign_manifest_for_publishing,
    verify_manifest_signature,
)

# Test helpers


def generate_test_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate ED25519 keypair for testing."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def encode_public_key(public_key: Ed25519PublicKey) -> str:
    """Encode public key to base64."""
    public_bytes = public_key.public_bytes_raw()
    return base64.b64encode(public_bytes).decode("ascii")


def encode_private_key(private_key: Ed25519PrivateKey) -> str:
    """Encode private key to base64."""
    private_bytes = private_key.private_bytes_raw()
    return base64.b64encode(private_bytes).decode("ascii")


# Canonical Manifest Tests


class TestCanonicalManifest:
    """Test get_canonical_manifest_for_signing."""

    def test_canonical_removes_signature_fields(self):
        """Canonical form removes signature and signature_algorithm."""
        manifest = {
            "source": "test",
            "entries": [],
            "signature": "should-be-removed",
            "signature_algorithm": "ed25519",
        }

        canonical = get_canonical_manifest_for_signing(manifest)

        assert "signature" not in canonical
        assert "signature_algorithm" not in canonical
        assert '"source":"test"' in canonical

    def test_canonical_sorts_keys(self):
        """Canonical form sorts keys alphabetically."""
        manifest = {
            "zebra": "last",
            "alpha": "first",
            "middle": "middle",
        }

        canonical = get_canonical_manifest_for_signing(manifest)

        # JSON with sorted keys
        assert canonical == '{"alpha":"first","middle":"middle","zebra":"last"}'

    def test_canonical_compact_json(self):
        """Canonical form uses compact JSON (no whitespace)."""
        manifest = {
            "source": "test",
            "entries": [{"domain": "adapter"}],
        }

        canonical = get_canonical_manifest_for_signing(manifest)

        # No spaces or newlines
        assert " " not in canonical
        assert "\n" not in canonical
        assert canonical == '{"entries":[{"domain":"adapter"}],"source":"test"}'

    def test_canonical_deterministic(self):
        """Canonical form is deterministic."""
        manifest = {
            "source": "test",
            "entries": [{"key": "value"}],
        }

        canonical1 = get_canonical_manifest_for_signing(manifest)
        canonical2 = get_canonical_manifest_for_signing(manifest)

        assert canonical1 == canonical2


# Signature Verification Tests


class TestSignatureVerification:
    """Test verify_manifest_signature."""

    def test_verify_valid_signature(self):
        """Verify accepts valid signature."""
        private_key, public_key = generate_test_keypair()
        manifest_data = '{"source":"test","entries":[]}'

        # Sign manifest
        signature_bytes = private_key.sign(manifest_data.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Verify signature
        is_valid, error = verify_manifest_signature(
            manifest_data,
            signature_b64,
            trusted_keys=[public_key],
        )

        assert is_valid is True
        assert error is None

    def test_verify_invalid_signature(self):
        """Verify rejects invalid signature."""
        private_key, public_key = generate_test_keypair()
        manifest_data = '{"source":"test","entries":[]}'

        # Sign different data
        wrong_data = '{"source":"wrong","entries":[]}'
        signature_bytes = private_key.sign(wrong_data.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Verify should fail
        is_valid, error = verify_manifest_signature(
            manifest_data,
            signature_b64,
            trusted_keys=[public_key],
        )

        assert is_valid is False
        assert error is not None
        assert "signature mismatch" in error

    def test_verify_no_trusted_keys(self):
        """Verify fails if no trusted keys configured."""
        manifest_data = '{"source":"test","entries":[]}'
        signature_b64 = "some-signature"

        is_valid, error = verify_manifest_signature(
            manifest_data,
            signature_b64,
            trusted_keys=[],
        )

        assert is_valid is False
        assert error is not None
        assert "No trusted public keys" in error

    def test_verify_empty_signature(self):
        """Verify fails on empty signature."""
        _, public_key = generate_test_keypair()
        manifest_data = '{"source":"test","entries":[]}'

        is_valid, error = verify_manifest_signature(
            manifest_data,
            "",
            trusted_keys=[public_key],
        )

        assert is_valid is False
        assert error is not None
        assert "empty" in error.lower()

    def test_verify_invalid_base64_signature(self):
        """Verify fails on malformed base64 signature."""
        _, public_key = generate_test_keypair()
        manifest_data = '{"source":"test","entries":[]}'

        is_valid, error = verify_manifest_signature(
            manifest_data,
            "not-valid-base64!!!",
            trusted_keys=[public_key],
        )

        assert is_valid is False
        assert error is not None
        assert "Invalid base64" in error

    def test_verify_multiple_keys_first_succeeds(self):
        """Verify succeeds if any trusted key validates."""
        private_key1, public_key1 = generate_test_keypair()
        _, public_key2 = generate_test_keypair()

        manifest_data = '{"source":"test","entries":[]}'
        signature_bytes = private_key1.sign(manifest_data.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # First key should validate
        is_valid, error = verify_manifest_signature(
            manifest_data,
            signature_b64,
            trusted_keys=[public_key1, public_key2],
        )

        assert is_valid is True
        assert error is None

    def test_verify_multiple_keys_second_succeeds(self):
        """Verify tries all keys until one succeeds."""
        _, public_key1 = generate_test_keypair()
        private_key2, public_key2 = generate_test_keypair()

        manifest_data = '{"source":"test","entries":[]}'
        signature_bytes = private_key2.sign(manifest_data.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Second key should validate
        is_valid, error = verify_manifest_signature(
            manifest_data,
            signature_b64,
            trusted_keys=[public_key1, public_key2],
        )

        assert is_valid is True
        assert error is None


# Trusted Keys Loading Tests


class TestLoadTrustedKeys:
    """Test load_trusted_public_keys from environment."""

    def test_load_keys_from_env(self, monkeypatch):
        """Load keys from ONEIRIC_TRUSTED_PUBLIC_KEYS env var."""
        _, public_key = generate_test_keypair()
        key_b64 = encode_public_key(public_key)

        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", key_b64)

        keys = load_trusted_public_keys()

        assert len(keys) == 1
        assert isinstance(keys[0], Ed25519PublicKey)

    def test_load_multiple_keys_from_env(self, monkeypatch):
        """Load multiple comma-separated keys."""
        _, public_key1 = generate_test_keypair()
        _, public_key2 = generate_test_keypair()

        key1_b64 = encode_public_key(public_key1)
        key2_b64 = encode_public_key(public_key2)

        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", f"{key1_b64},{key2_b64}")

        keys = load_trusted_public_keys()

        assert len(keys) == 2

    def test_load_keys_no_env_var(self, monkeypatch):
        """Load returns empty list if env var not set."""
        monkeypatch.delenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", raising=False)

        keys = load_trusted_public_keys()

        assert keys == []

    def test_load_keys_skips_invalid(self, monkeypatch):
        """Load skips invalid keys and logs warning."""
        _, public_key = generate_test_keypair()
        valid_key = encode_public_key(public_key)

        # Mix valid and invalid keys
        monkeypatch.setenv(
            "ONEIRIC_TRUSTED_PUBLIC_KEYS",
            f"{valid_key},invalid-key-here,",
        )

        keys = load_trusted_public_keys()

        assert len(keys) == 1  # Only valid key loaded

    def test_load_keys_handles_whitespace(self, monkeypatch):
        """Load handles whitespace around keys."""
        _, public_key = generate_test_keypair()
        key_b64 = encode_public_key(public_key)

        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", f"  {key_b64}  ,  ")

        keys = load_trusted_public_keys()

        assert len(keys) == 1


# Manifest Signing Tests (for publishers)


class TestManifestSigning:
    """Test sign_manifest_for_publishing utility."""

    def test_sign_manifest(self):
        """Sign manifest returns base64 signature."""
        private_key, public_key = generate_test_keypair()
        manifest = {
            "source": "test",
            "entries": [],
        }

        private_key_b64 = encode_private_key(private_key)
        signature = sign_manifest_for_publishing(manifest, private_key_b64)

        # Signature should be base64
        assert isinstance(signature, str)
        assert len(signature) > 0

        # Verify signature is valid
        canonical = get_canonical_manifest_for_signing(manifest)
        is_valid, _ = verify_manifest_signature(
            canonical,
            signature,
            trusted_keys=[public_key],
        )
        assert is_valid is True

    def test_sign_and_verify_roundtrip(self):
        """Sign and verify roundtrip works."""
        private_key, public_key = generate_test_keypair()
        manifest = {
            "source": "production",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "myapp.adapters:RedisCache",
                }
            ],
        }

        # Sign manifest
        private_key_b64 = encode_private_key(private_key)
        signature = sign_manifest_for_publishing(manifest, private_key_b64)

        # Add signature to manifest
        manifest["signature"] = signature
        manifest["signature_algorithm"] = "ed25519"

        # Verify canonical form
        canonical = get_canonical_manifest_for_signing(manifest)
        is_valid, error = verify_manifest_signature(
            canonical,
            signature,
            trusted_keys=[public_key],
        )

        assert is_valid is True
        assert error is None
