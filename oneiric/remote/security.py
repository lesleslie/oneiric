"""Remote manifest signature verification.

This module provides cryptographic signature verification for remote manifests
using ED25519 public key cryptography.
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from oneiric.core.logging import get_logger

logger = get_logger("remote.security")

# Environment variable for trusted public keys (base64-encoded, comma-separated)
ENV_TRUSTED_PUBLIC_KEYS = "ONEIRIC_TRUSTED_PUBLIC_KEYS"


class SignatureVerificationError(Exception):
    """Raised when signature verification fails."""

    pass


def load_trusted_public_keys() -> list[Ed25519PublicKey]:
    """Load trusted public keys from environment variable.

    Reads from ONEIRIC_TRUSTED_PUBLIC_KEYS environment variable.
    Format: comma-separated list of base64-encoded ED25519 public keys.

    Returns:
        List of Ed25519PublicKey objects

    Examples:
        # With env: ONEIRIC_TRUSTED_PUBLIC_KEYS="base64key1,base64key2"
        >>> keys = load_trusted_public_keys()
        >>> len(keys)
        2

        # Without env (no keys)
        >>> load_trusted_public_keys()
        []
    """
    env_value = os.getenv(ENV_TRUSTED_PUBLIC_KEYS)
    if not env_value:
        return []

    keys = []
    for key_b64 in env_value.split(","):
        key_b64 = key_b64.strip()
        if not key_b64:
            continue

        try:
            key_bytes = base64.b64decode(key_b64)
            public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
            keys.append(public_key)
        except Exception as exc:
            logger.warning(
                "invalid-public-key",
                key_b64_prefix=key_b64[:16],
                error=str(exc),
            )
            continue

    return keys


def verify_manifest_signature(
    manifest_data: str,
    signature_b64: str,
    *,
    trusted_keys: list[Ed25519PublicKey] | None = None,
) -> tuple[bool, str | None]:
    """Verify manifest signature using ED25519.

    Args:
        manifest_data: Original manifest JSON/YAML text (before parsing)
        signature_b64: Base64-encoded signature
        trusted_keys: List of trusted public keys (defaults to loading from env)

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.

    Raises:
        SignatureVerificationError: If signature verification fails critically

    Examples:
        >>> is_valid, error = verify_manifest_signature(manifest_text, signature)
        >>> if not is_valid:
        ...     print(f"Signature verification failed: {error}")
    """
    if trusted_keys is None:
        trusted_keys = load_trusted_public_keys()

    if not trusted_keys:
        return (
            False,
            "No trusted public keys configured (ONEIRIC_TRUSTED_PUBLIC_KEYS not set)",
        )

    if not signature_b64:
        return False, "Signature is empty"

    # Decode signature from base64
    try:
        signature_bytes = base64.b64decode(signature_b64)
    except Exception as exc:
        return False, f"Invalid base64 signature: {exc}"

    # Try each trusted key until one succeeds
    errors = []
    for i, public_key in enumerate(trusted_keys):
        try:
            # Verify signature (raises InvalidSignature if verification fails)
            public_key.verify(signature_bytes, manifest_data.encode("utf-8"))
            logger.info(
                "signature-verified",
                key_index=i,
                signature_length=len(signature_bytes),
            )
            return True, None
        except InvalidSignature:
            errors.append(f"key_{i}: signature mismatch")
            continue
        except Exception as exc:
            errors.append(f"key_{i}: {type(exc).__name__}: {exc}")
            continue

    # None of the keys verified the signature
    error_msg = f"Signature verification failed with all {len(trusted_keys)} trusted keys: {'; '.join(errors)}"
    logger.warning("signature-verification-failed", error=error_msg)
    return False, error_msg


def get_canonical_manifest_for_signing(manifest_dict: dict) -> str:
    """Get canonical JSON representation for signing/verification.

    This ensures consistent serialization by:
    - Removing signature fields (signature, signature_algorithm)
    - Sorting keys alphabetically
    - Using compact JSON (no whitespace)

    Args:
        manifest_dict: Parsed manifest dictionary

    Returns:
        Canonical JSON string for signing

    Examples:
        >>> manifest = {"source": "remote", "entries": []}
        >>> canonical = get_canonical_manifest_for_signing(manifest)
        >>> canonical
        '{"entries":[],"source":"remote"}'
    """
    # Remove signature fields to get the unsigned content
    unsigned = {
        k: v
        for k, v in manifest_dict.items()
        if k not in ("signature", "signature_algorithm", "signatures")
    }

    # Canonical JSON: sorted keys, compact (no whitespace)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"))


def verify_manifest_signatures(
    manifest_data: str,
    signatures: list[str],
    *,
    threshold: int = 1,
    trusted_keys: list[Ed25519PublicKey] | None = None,
) -> tuple[bool, str | None, int]:
    """Verify multiple signatures and enforce a threshold."""

    if threshold < 1:
        return False, "Signature threshold must be >= 1", 0

    if trusted_keys is None:
        trusted_keys = load_trusted_public_keys()

    if not trusted_keys:
        return (
            False,
            "No trusted public keys configured (ONEIRIC_TRUSTED_PUBLIC_KEYS not set)",
            0,
        )

    valid_count = 0
    errors: list[str] = []
    for idx, signature in enumerate(signatures):
        is_valid, error = verify_manifest_signature(
            manifest_data, signature, trusted_keys=trusted_keys
        )
        if is_valid:
            valid_count += 1
        else:
            errors.append(f"sig_{idx}: {error}")
        if valid_count >= threshold:
            return True, None, valid_count

    error_msg = (
        "Signature threshold not met: "
        f"{valid_count} valid of {len(signatures)} provided; "
        f"required {threshold}. Errors: {'; '.join(errors)}"
    )
    return False, error_msg, valid_count


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal attacks.

    Removes dangerous path components like '..' and '/', and null bytes.

    Args:
        filename: The filename to sanitize

    Returns:
        Sanitized filename safe for use in file paths

    Examples:
        >>> sanitize_filename("../../etc/passwd")
        'etcpasswd'
        >>> sanitize_filename("normal_file.txt")
        'normal_file.txt'
        >>> sanitize_filename("file\\x00.whl")
        'file.whl'
    """
    from pathlib import Path

    # Remove null bytes first
    filename = filename.replace("\x00", "")

    # Remove any path separators and parent directory references
    return (
        "".join(
            part
            for part in Path(filename).parts
            if part not in (".", "..") and "/" not in part and "\\" not in part
        )
        or "sanitized_file"
    )


def sign_manifest_for_publishing(manifest_dict: dict, private_key_b64: str) -> str:
    """Sign a manifest for publishing (utility for manifest authors).

    This is a helper function for manifest publishers, not used in verification.

    Args:
        manifest_dict: Manifest dictionary to sign
        private_key_b64: Base64-encoded ED25519 private key (64 bytes)

    Returns:
        Base64-encoded signature

    Examples:
        >>> signature = sign_manifest_for_publishing(manifest, private_key)
        >>> manifest["signature"] = signature
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # Get canonical representation
    canonical = get_canonical_manifest_for_signing(manifest_dict)

    # Decode private key
    # Sign the canonical JSON
    return base64.b64encode(
        (
            private_key := Ed25519PrivateKey.from_private_bytes(
                base64.b64decode(private_key_b64)
            )
        ).sign(canonical.encode("utf-8"))
    ).decode("ascii")
