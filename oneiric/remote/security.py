from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from oneiric.core.logging import get_logger

logger = get_logger("remote.security")


ENV_TRUSTED_PUBLIC_KEYS = "ONEIRIC_TRUSTED_PUBLIC_KEYS"


class SignatureVerificationError(Exception):
    pass


def load_trusted_public_keys() -> list[Ed25519PublicKey]:
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
    if trusted_keys is None:
        trusted_keys = load_trusted_public_keys()

    if not trusted_keys:
        return (
            False,
            "No trusted public keys configured (ONEIRIC_TRUSTED_PUBLIC_KEYS not set)",
        )

    if not signature_b64:
        return False, "Signature is empty"

    try:
        signature_bytes = base64.b64decode(signature_b64)
    except Exception as exc:
        return False, f"Invalid base64 signature: {exc}"

    errors = []
    for i, public_key in enumerate(trusted_keys):
        try:
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

    error_msg = f"Signature verification failed with all {len(trusted_keys)} trusted keys: {'; '.join(errors)}"
    logger.warning("signature-verification-failed", error=error_msg)
    return False, error_msg


def get_canonical_manifest_for_signing(manifest_dict: dict) -> str:
    unsigned = {
        k: v
        for k, v in manifest_dict.items()
        if k not in ("signature", "signature_algorithm", "signatures")
    }

    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"))


def verify_manifest_signatures(
    manifest_data: str,
    signatures: list[str],
    *,
    threshold: int = 1,
    trusted_keys: list[Ed25519PublicKey] | None = None,
) -> tuple[bool, str | None, int]:
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
    from pathlib import Path

    filename = filename.replace("\x00", "")

    return (
        "".join(
            part
            for part in Path(filename).parts
            if part not in (".", "..") and "/" not in part and "\\" not in part
        )
        or "sanitized_file"
    )


def sign_manifest_for_publishing(manifest_dict: dict, private_key_b64: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    canonical = get_canonical_manifest_for_signing(manifest_dict)

    private_key = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key_b64)
    )
    signature = private_key.sign(canonical.encode("utf-8"))
    return base64.b64encode(signature).decode("ascii")
