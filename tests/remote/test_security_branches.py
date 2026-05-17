from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from oneiric.remote.security import (
    ENV_TRUSTED_PUBLIC_KEYS,
    get_canonical_manifest_for_signing,
    load_trusted_public_keys,
    sanitize_filename,
    sign_manifest_for_publishing,
    verify_manifest_signature,
    verify_manifest_signatures,
)


def test_load_trusted_public_keys_skips_invalid_entries(monkeypatch) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    valid = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")

    monkeypatch.setenv(ENV_TRUSTED_PUBLIC_KEYS, f"not-base64,{valid},")

    keys = load_trusted_public_keys()

    assert len(keys) == 1


def test_verify_manifest_signature_handles_generic_key_error() -> None:
    class BrokenKey:
        def verify(self, signature_bytes, message_bytes):
            raise RuntimeError("boom")

    ok, error = verify_manifest_signature(
        "{}", base64.b64encode(b"sig").decode("ascii"), trusted_keys=[BrokenKey()]
    )

    assert ok is False
    assert "RuntimeError" in error


def test_verify_manifest_signatures_threshold_and_error_paths() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    canonical = "{\"source\":\"test\"}"
    signature = base64.b64encode(private_key.sign(canonical.encode("utf-8"))).decode(
        "ascii"
    )

    ok, error, count = verify_manifest_signatures(
        canonical,
        [signature],
        threshold=1,
        trusted_keys=[public_key],
    )
    assert ok is True
    assert error is None
    assert count == 1

    ok, error, count = verify_manifest_signatures(
        canonical,
        [signature],
        threshold=0,
        trusted_keys=[public_key],
    )
    assert ok is False
    assert ">= 1" in error
    assert count == 0


def test_sign_manifest_for_publishing_and_canonical_form() -> None:
    private_key = Ed25519PrivateKey.generate()
    private_b64 = base64.b64encode(private_key.private_bytes_raw()).decode("ascii")

    manifest = {"source": "test", "entries": [], "signature": "remove-me"}
    canonical = get_canonical_manifest_for_signing(manifest)
    signature = sign_manifest_for_publishing(manifest, private_b64)

    assert "signature" not in canonical
    assert len(signature) > 10


def test_sanitize_filename_removes_traversal_and_nul() -> None:
    assert sanitize_filename("../bad\x00name.txt") == "badname.txt"
    assert sanitize_filename("..") == "sanitized_file"
