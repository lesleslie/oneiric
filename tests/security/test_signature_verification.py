"""Security tests for remote manifest signature verification.

These tests verify that remote manifests can be cryptographically signed
and verified using ED25519 public key cryptography.
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneiric.remote.security import (
    get_canonical_manifest_for_signing,
    load_trusted_public_keys,
    sign_manifest_for_publishing,
    verify_manifest_signature,
    verify_manifest_signatures,
)


class TestSignatureVerification:
    """Test ED25519 signature verification for remote manifests."""

    def test_sign_and_verify_valid_manifest(self):
        """Valid signature verifies successfully."""
        # Generate test keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Create test manifest
        manifest = {
            "source": "test-remote",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.demo:RedisAdapter",
                }
            ],
        }

        # Get canonical form
        canonical = get_canonical_manifest_for_signing(manifest)

        # Sign manifest
        signature_bytes = private_key.sign(canonical.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Verify signature
        is_valid, error = verify_manifest_signature(
            canonical, signature_b64, trusted_keys=[public_key]
        )
        assert is_valid
        assert error is None

    def test_tampered_manifest_fails_verification(self):
        """Tampered manifest fails signature verification."""
        # Generate test keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Create and sign original manifest
        manifest = {
            "source": "test-remote",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.demo:RedisAdapter",
                }
            ],
        }
        canonical = get_canonical_manifest_for_signing(manifest)
        signature_bytes = private_key.sign(canonical.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Tamper with manifest (change provider)
        manifest["entries"][0]["provider"] = "memcached"
        tampered_canonical = get_canonical_manifest_for_signing(manifest)

        # Verification should fail
        is_valid, error = verify_manifest_signature(
            tampered_canonical, signature_b64, trusted_keys=[public_key]
        )
        assert not is_valid
        assert "signature mismatch" in error

    def test_wrong_public_key_fails_verification(self):
        """Signature fails verification with wrong public key."""
        # Generate two keypairs
        private_key1 = Ed25519PrivateKey.generate()
        private_key2 = Ed25519PrivateKey.generate()
        public_key2 = private_key2.public_key()

        # Sign with key1, verify with key2
        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)
        signature_bytes = private_key1.sign(canonical.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Verification should fail (wrong key)
        is_valid, error = verify_manifest_signature(
            canonical, signature_b64, trusted_keys=[public_key2]
        )
        assert not is_valid
        assert "signature mismatch" in error

    def test_multiple_trusted_keys_first_succeeds(self):
        """First matching key succeeds verification."""
        # Generate three keypairs
        private_key1 = Ed25519PrivateKey.generate()
        public_key1 = private_key1.public_key()

        private_key2 = Ed25519PrivateKey.generate()
        public_key2 = private_key2.public_key()

        private_key3 = Ed25519PrivateKey.generate()
        public_key3 = private_key3.public_key()

        # Sign with key1
        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)
        signature_bytes = private_key1.sign(canonical.encode("utf-8"))
        signature_b64 = base64.b64encode(signature_bytes).decode("ascii")

        # Verify with multiple keys (key1 is in the list)
        is_valid, error = verify_manifest_signature(
            canonical,
            signature_b64,
            trusted_keys=[public_key2, public_key1, public_key3],
        )
        assert is_valid
        assert error is None

    def test_threshold_signature_verification(self):
        """Threshold verification succeeds when enough signatures validate."""
        private_key1 = Ed25519PrivateKey.generate()
        private_key2 = Ed25519PrivateKey.generate()
        public_key1 = private_key1.public_key()
        public_key2 = private_key2.public_key()

        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)
        sig1 = base64.b64encode(private_key1.sign(canonical.encode("utf-8"))).decode(
            "ascii"
        )
        sig2 = base64.b64encode(private_key2.sign(canonical.encode("utf-8"))).decode(
            "ascii"
        )

        is_valid, error, valid_count = verify_manifest_signatures(
            canonical,
            [sig1, sig2],
            threshold=2,
            trusted_keys=[public_key1, public_key2],
        )
        assert is_valid
        assert error is None
        assert valid_count == 2

    def test_no_trusted_keys_fails(self):
        """Verification fails when no trusted keys configured."""
        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)
        signature_b64 = "fake-signature"

        is_valid, error = verify_manifest_signature(
            canonical, signature_b64, trusted_keys=[]
        )
        assert not is_valid
        assert "No trusted public keys" in error

    def test_empty_signature_fails(self):
        """Empty signature fails verification."""
        public_key = Ed25519PrivateKey.generate().public_key()
        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)

        is_valid, error = verify_manifest_signature(
            canonical, "", trusted_keys=[public_key]
        )
        assert not is_valid
        assert "empty" in error.lower()

    def test_invalid_base64_signature_fails(self):
        """Invalid base64 signature fails verification."""
        public_key = Ed25519PrivateKey.generate().public_key()
        manifest = {"source": "test", "entries": []}
        canonical = get_canonical_manifest_for_signing(manifest)

        is_valid, error = verify_manifest_signature(
            canonical, "not-valid-base64!@#", trusted_keys=[public_key]
        )
        assert not is_valid
        assert "Invalid base64" in error


class TestCanonicalManifestForm:
    """Test canonical manifest representation for signing."""

    def test_signature_fields_removed(self):
        """Signature fields are removed from canonical form."""
        manifest = {
            "source": "test",
            "entries": [],
            "signature": "should-be-removed",
            "signature_algorithm": "ed25519",
            "signatures": [{"signature": "remove-me", "algorithm": "ed25519"}],
        }

        canonical = get_canonical_manifest_for_signing(manifest)
        parsed = json.loads(canonical)

        assert "signature" not in parsed
        assert "signature_algorithm" not in parsed
        assert "signatures" not in parsed
        assert "source" in parsed
        assert "entries" in parsed

    def test_keys_sorted_alphabetically(self):
        """Keys are sorted alphabetically in canonical form."""
        manifest = {
            "z_last": "value",
            "a_first": "value",
            "m_middle": "value",
        }

        canonical = get_canonical_manifest_for_signing(manifest)
        # Check that keys appear in alphabetical order
        assert canonical.index('"a_first"') < canonical.index('"m_middle"')
        assert canonical.index('"m_middle"') < canonical.index('"z_last"')

    def test_compact_json_no_whitespace(self):
        """Canonical form uses compact JSON (no whitespace)."""
        manifest = {
            "source": "test",
            "entries": [{"domain": "adapter"}],
        }

        canonical = get_canonical_manifest_for_signing(manifest)

        # Should not contain extra whitespace
        assert "  " not in canonical
        assert "\n" not in canonical
        assert "\t" not in canonical

    def test_canonical_form_deterministic(self):
        """Same manifest produces same canonical form."""
        manifest = {
            "entries": [{"key": "cache"}],
            "source": "test",
        }

        canonical1 = get_canonical_manifest_for_signing(manifest)
        canonical2 = get_canonical_manifest_for_signing(manifest)

        assert canonical1 == canonical2


class TestPublicKeyLoading:
    """Test loading public keys from environment."""

    def test_load_single_public_key(self, monkeypatch):
        """Single public key loaded from environment."""
        # Generate test key
        private_key = Ed25519PrivateKey.generate()
        public_key_bytes = private_key.public_key().public_bytes_raw()
        public_key_b64 = base64.b64encode(public_key_bytes).decode("ascii")

        # Set environment variable
        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", public_key_b64)

        # Load keys
        keys = load_trusted_public_keys()
        assert len(keys) == 1

    def test_load_multiple_public_keys(self, monkeypatch):
        """Multiple public keys loaded from comma-separated list."""
        # Generate two test keys
        key1_bytes = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        key2_bytes = Ed25519PrivateKey.generate().public_key().public_bytes_raw()

        key1_b64 = base64.b64encode(key1_bytes).decode("ascii")
        key2_b64 = base64.b64encode(key2_bytes).decode("ascii")

        # Set environment variable with comma-separated keys
        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", f"{key1_b64},{key2_b64}")

        # Load keys
        keys = load_trusted_public_keys()
        assert len(keys) == 2

    def test_no_environment_variable_returns_empty(self, monkeypatch):
        """No keys returned when environment variable not set."""
        monkeypatch.delenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", raising=False)

        keys = load_trusted_public_keys()
        assert len(keys) == 0

    def test_invalid_key_skipped_with_warning(self, monkeypatch):
        """Invalid keys are skipped with warning."""
        # Valid key
        valid_key_bytes = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        valid_key_b64 = base64.b64encode(valid_key_bytes).decode("ascii")

        # Invalid base64
        invalid_key = "not-valid-base64!@#"

        # Set environment with both
        monkeypatch.setenv(
            "ONEIRIC_TRUSTED_PUBLIC_KEYS", f"{valid_key_b64},{invalid_key}"
        )

        # Load keys (should skip invalid)
        keys = load_trusted_public_keys()
        assert len(keys) == 1  # Only valid key loaded

    def test_empty_keys_skipped(self, monkeypatch):
        """Empty keys in comma-separated list are skipped."""
        key_bytes = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        key_b64 = base64.b64encode(key_bytes).decode("ascii")

        # Include empty strings in list
        monkeypatch.setenv("ONEIRIC_TRUSTED_PUBLIC_KEYS", f",{key_b64},,")

        keys = load_trusted_public_keys()
        assert len(keys) == 1


class TestManifestSigningUtility:
    """Test manifest signing utility for publishers."""

    def test_sign_manifest_produces_valid_signature(self):
        """Signed manifest can be verified."""
        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        # Prepare private key for signing
        private_key_bytes = private_key.private_bytes_raw()
        private_key_b64 = base64.b64encode(private_key_bytes).decode("ascii")

        # Create manifest
        manifest = {
            "source": "test-publisher",
            "entries": [
                {
                    "domain": "adapter",
                    "key": "cache",
                    "provider": "redis",
                    "factory": "oneiric.demo:RedisAdapter",
                }
            ],
        }

        # Sign manifest
        signature_b64 = sign_manifest_for_publishing(manifest, private_key_b64)

        # Verify signature
        canonical = get_canonical_manifest_for_signing(manifest)
        is_valid, error = verify_manifest_signature(
            canonical, signature_b64, trusted_keys=[public_key]
        )
        assert is_valid
        assert error is None

    def test_signed_manifest_roundtrip(self):
        """Full roundtrip: sign, add to manifest, verify."""
        # Generate keypair
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_key_bytes = private_key.private_bytes_raw()
        private_key_b64 = base64.b64encode(private_key_bytes).decode("ascii")

        # Create manifest
        manifest = {"source": "publisher", "entries": []}

        # Sign and add signature to manifest
        signature = sign_manifest_for_publishing(manifest, private_key_b64)
        manifest["signature"] = signature
        manifest["signature_algorithm"] = "ed25519"

        # Verify by extracting canonical form
        canonical = get_canonical_manifest_for_signing(manifest)
        is_valid, error = verify_manifest_signature(
            canonical, signature, trusted_keys=[public_key]
        )
        assert is_valid
