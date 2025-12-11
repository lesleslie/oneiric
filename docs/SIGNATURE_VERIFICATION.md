# Remote Manifest Signature Verification

## Overview

Oneiric supports cryptographic signature verification for remote manifests using **ED25519 public key cryptography**. This prevents man-in-the-middle attacks and ensures manifest authenticity.

**Security Level:** CVSS 8.1 mitigation (Supply Chain Attack Prevention)

## Quick Start

### 1. Manifest Publishers: Generate Keys and Sign Manifests

```python
#!/usr/bin/env python3
"""Generate ED25519 keypair and sign a manifest."""

import base64
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Generate keypair
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()

# Export keys (base64-encoded)
private_key_b64 = base64.b64encode(private_key.private_bytes_raw()).decode("ascii")
public_key_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")

print(f"Private Key (KEEP SECRET): {private_key_b64}")
print(f"Public Key (DISTRIBUTE): {public_key_b64}")

# Load manifest to sign
with open("manifest.json") as f:
    manifest = json.load(f)

# Sign manifest using Oneiric's signing utility
from oneiric.remote.security import sign_manifest_for_publishing

signature = sign_manifest_for_publishing(manifest, private_key_b64)

# Add signature to manifest
manifest["signature"] = signature
manifest["signature_algorithm"] = "ed25519"

# Save signed manifest
with open("manifest_signed.json", "w") as f:
    json.dump(manifest, f, indent=2)

print(f"✅ Manifest signed successfully!")
print(f"Signature: {signature[:32]}...")
```

### 2. Manifest Consumers: Configure Trusted Public Keys

```bash
# Set trusted public keys environment variable (comma-separated for multiple keys)
export ONEIRIC_TRUSTED_PUBLIC_KEYS="base64-public-key-1,base64-public-key-2"
```

**Example:**

```bash
export ONEIRIC_TRUSTED_PUBLIC_KEYS="MCowBQYDK2VwAyEA..."
```

### 3. Verification Happens Automatically

When a signed manifest is loaded, Oneiric automatically verifies the signature:

```python
from oneiric.remote.loader import sync_remote_manifest

# Signature verification happens automatically during sync
result = await sync_remote_manifest(
    resolver, config, manifest_url="https://example.com/manifest.json"
)
```

**Verification Behavior:**

- ✅ **Signature present + valid**: Manifest accepted, logged as verified
- ⚠️ **Signature present + invalid**: Manifest **rejected**, error raised
- ⚠️ **No signature**: Manifest accepted with warning (backward compatibility)

## Key Generation Details

### Using Python (Recommended)

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import base64

# Generate keypair
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()

# Export for storage/distribution
private_key_bytes = private_key.private_bytes_raw()  # 64 bytes
public_key_bytes = public_key.public_bytes_raw()  # 32 bytes

private_key_b64 = base64.b64encode(private_key_bytes).decode("ascii")
public_key_b64 = base64.b64encode(public_key_bytes).decode("ascii")
```

### Using OpenSSL (Alternative)

```bash
# Generate private key
openssl genpkey -algorithm ED25519 -out private_key.pem

# Extract public key
openssl pkey -in private_key.pem -pubout -out public_key.pem

# Convert to raw base64 (requires additional processing)
# Note: OpenSSL outputs PEM format; raw bytes extraction needed
```

### Key Storage Best Practices

**Private Keys (Publishers):**

- ❌ Never commit to version control
- ✅ Store in secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
- ✅ Use environment variables in CI/CD
- ✅ Rotate periodically (e.g., every 90 days)

**Public Keys (Consumers):**

- ✅ Can be committed to configuration
- ✅ Distribute via secure channels
- ✅ Include in documentation
- ✅ Support multiple keys for rotation

## Manifest Signing Workflow

### Manual Signing

```python
#!/usr/bin/env python3
"""Sign a manifest for distribution."""

import base64
import json
import sys
from oneiric.remote.security import sign_manifest_for_publishing

# Load private key from environment or file
private_key_b64 = os.environ["MANIFEST_SIGNING_KEY"]

# Load manifest
with open(sys.argv[1]) as f:
    manifest = json.load(f)

# Sign manifest
signature = sign_manifest_for_publishing(manifest, private_key_b64)

# Add signature fields
manifest["signature"] = signature
manifest["signature_algorithm"] = "ed25519"

# Save signed manifest
output_path = sys.argv[1].replace(".json", "_signed.json")
with open(output_path, "w") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)

print(f"✅ Signed: {output_path}")
```

### Automated CI/CD Signing

```yaml
# .github/workflows/publish-manifest.yml
name: Sign and Publish Manifest

on:
  push:
    branches: [main]
    paths: ['manifests/**']

jobs:
  sign-and-publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: pip install cryptography

      - name: Sign manifest
        env:
          MANIFEST_SIGNING_KEY: ${{ secrets.MANIFEST_SIGNING_KEY }}
        run: python scripts/sign_manifest.py manifests/production.json

      - name: Publish signed manifest
        run: |
          aws s3 cp manifests/production_signed.json s3://manifests/production.json
```

## Verification Process

### Canonical Form

Before verification, manifests are converted to a canonical JSON representation:

1. **Remove signature fields** (`signature`, `signature_algorithm`)
1. **Sort keys alphabetically**
1. **Compact JSON** (no whitespace)

**Example:**

```python
from oneiric.remote.security import get_canonical_manifest_for_signing

manifest = {
    "entries": [...],
    "source": "remote",
    "signature": "...",  # Removed during canonicalization
}

canonical = get_canonical_manifest_for_signing(manifest)
# Result: '{"entries":[...],"source":"remote"}'
```

This ensures that:

- Signature verification is consistent regardless of formatting
- Whitespace/order differences don't break verification
- Publishers and consumers use identical byte sequences

### Verification Algorithm

```python
def verify_manifest_signature(
    manifest_data: str, signature_b64: str, trusted_keys: list[Ed25519PublicKey]
) -> tuple[bool, Optional[str]]:
    """
    1. Decode base64 signature
    2. Try each trusted public key
    3. Verify signature matches canonical manifest
    4. Return (True, None) on success or (False, error_msg)
    """
```

**Key Rotation Support:**

- Multiple public keys can be trusted simultaneously
- Verification succeeds if **any** trusted key validates the signature
- Allows gradual key rotation without downtime

## Configuration

### Environment Variables

| Variable | Format | Example | Required |
|----------|--------|---------|----------|
| `ONEIRIC_TRUSTED_PUBLIC_KEYS` | Comma-separated base64 keys | `key1,key2,key3` | Yes (for verification) |

### Python API

```python
from oneiric.remote.security import (
    load_trusted_public_keys,
    verify_manifest_signature,
)

# Load keys from environment
keys = load_trusted_public_keys()

# Manual verification
is_valid, error = verify_manifest_signature(
    manifest_text, signature_b64, trusted_keys=keys
)
```

## Security Considerations

### Threat Model

**Mitigated Threats:**

- ✅ Man-in-the-middle attacks (CVSS 8.1)
- ✅ Manifest tampering during transit
- ✅ Unauthorized manifest publishing
- ✅ Supply chain compromise

**Not Mitigated (Out of Scope):**

- ❌ Compromised signing keys (key management responsibility)
- ❌ Malicious but validly-signed manifests (trust boundary)
- ❌ Replay attacks (consider timestamp validation in future)

### Key Security

**ED25519 Properties:**

- **Key Size:** 256-bit security level
- **Signature Size:** 64 bytes
- **Performance:** ~70K signatures/second, ~25K verifications/second
- **Resistance:** Collision-resistant, EUF-CMA secure

**Best Practices:**

1. Generate keys in secure environment (not production servers)
1. Use hardware security modules (HSMs) for production keys
1. Implement key rotation policy
1. Monitor signature verification logs for anomalies
1. Revoke compromised keys immediately

### Backward Compatibility

**Current Behavior (v0.1.0):**

- Unsigned manifests: **Accepted** with warning
- Signed + valid: Accepted
- Signed + invalid: **Rejected**

**Future Behavior (v1.0.0):**

- Consider making signatures **mandatory** for production manifests
- Add `require_signature` configuration option
- Implement manifest versioning with signature requirements

## Troubleshooting

### Common Issues

#### 1. "No trusted public keys configured"

```python
# Check environment variable
import os

print(os.environ.get("ONEIRIC_TRUSTED_PUBLIC_KEYS"))

# Should output: "base64-key-1,base64-key-2"
```

**Fix:** Set `ONEIRIC_TRUSTED_PUBLIC_KEYS` environment variable

#### 2. "Signature verification failed with all trusted keys"

**Causes:**

- Wrong public key (doesn't match private key used for signing)
- Manifest was modified after signing
- Signature is corrupted

**Debugging:**

```python
from oneiric.remote.security import get_canonical_manifest_for_signing

# Get canonical form of manifest
canonical = get_canonical_manifest_for_signing(manifest)
print(f"Canonical: {canonical}")

# Verify manually with known key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import base64

pub_key_bytes = base64.b64decode(public_key_b64)
pub_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)

sig_bytes = base64.b64decode(signature_b64)
pub_key.verify(sig_bytes, canonical.encode("utf-8"))  # Raises if invalid
```

#### 3. "Invalid base64 signature"

**Cause:** Signature string is not valid base64

**Fix:** Ensure signature is properly base64-encoded:

```python
import base64

# Valid base64 uses only: A-Z, a-z, 0-9, +, /, =
# Example: "MCowBQYDK2VwAyEA..."
```

### Debug Logging

Enable debug logging to see signature verification details:

```python
import logging

logging.getLogger("remote.security").setLevel(logging.DEBUG)
```

**Output:**

```
INFO:remote.security:signature-verified key_index=0 signature_length=64
WARNING:remote.security:signature-verification-failed error="Signature verification failed with all 2 trusted keys: key_0: signature mismatch; key_1: signature mismatch"
```

## Examples

### Complete Publisher Workflow

```python
#!/usr/bin/env python3
"""Complete manifest publishing workflow with signature."""

import base64
import json
import os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from oneiric.remote.security import sign_manifest_for_publishing


def publish_signed_manifest(manifest_path: str, private_key_b64: str, output_path: str):
    """Sign and publish a manifest."""

    # Load manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Sign manifest
    signature = sign_manifest_for_publishing(manifest, private_key_b64)

    # Add signature
    manifest["signature"] = signature
    manifest["signature_algorithm"] = "ed25519"

    # Save signed manifest
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    print(f"✅ Manifest signed and saved to {output_path}")
    print(f"   Signature: {signature[:32]}...")

    return manifest


if __name__ == "__main__":
    # Get private key from environment
    private_key_b64 = os.environ.get("MANIFEST_SIGNING_KEY")
    if not private_key_b64:
        # Generate new key for testing
        private_key = Ed25519PrivateKey.generate()
        private_key_b64 = base64.b64encode(private_key.private_bytes_raw()).decode(
            "ascii"
        )
        print(f"Generated new key: {private_key_b64}")

    # Sign and publish
    publish_signed_manifest(
        manifest_path="manifests/production.json",
        private_key_b64=private_key_b64,
        output_path="manifests/production_signed.json",
    )
```

### Complete Consumer Workflow

```python
#!/usr/bin/env python3
"""Complete manifest consumption workflow with verification."""

import asyncio
import os
from oneiric.core.resolution import Resolver
from oneiric.core.config import Settings
from oneiric.remote.loader import sync_remote_manifest


async def consume_signed_manifest(manifest_url: str):
    """Load and verify a signed manifest."""

    # Ensure public keys are configured
    public_keys = os.environ.get("ONEIRIC_TRUSTED_PUBLIC_KEYS")
    if not public_keys:
        print("⚠️ WARNING: No trusted public keys configured!")
        print("   Set ONEIRIC_TRUSTED_PUBLIC_KEYS environment variable")
        return

    # Load settings and create resolver
    settings = Settings.from_directory("settings")
    resolver = Resolver()

    # Sync manifest (signature verification happens automatically)
    try:
        result = await sync_remote_manifest(
            resolver, settings.remote, manifest_url=manifest_url
        )

        if result:
            print(f"✅ Manifest loaded and verified successfully!")
            print(f"   Registered: {result.registered} components")
            print(f"   Duration: {result.duration_ms:.1f}ms")

    except ValueError as e:
        print(f"❌ Manifest verification failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(
        consume_signed_manifest(
            manifest_url="https://example.com/manifests/production.json"
        )
    )
```

## Testing

See `tests/security/test_signature_verification.py` for comprehensive test coverage:

- ✅ Valid signature verification
- ✅ Tampered manifest detection
- ✅ Wrong public key detection
- ✅ Multiple trusted keys support
- ✅ Key rotation scenarios
- ✅ Invalid signature handling
- ✅ Canonical form consistency

**Test Coverage:** 94% (61/65 statements)

## References

- [ED25519 Signature Scheme](https://ed25519.cr.yp.to/)
- [RFC 8032: Edwards-Curve Digital Signature Algorithm](https://www.rfc-editor.org/rfc/rfc8032)
- [Cryptography Library Documentation](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)
- [Supply Chain Security Best Practices](https://slsa.dev/)

## Future Enhancements

- [ ] Timestamp-based replay attack prevention
- [ ] Multi-signature support (threshold signatures)
- [ ] Manifest versioning with signature requirements
- [ ] Hardware security module (HSM) integration
- [ ] Key revocation lists (CRLs)
- [ ] Signature transparency logging
