#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


sys.path.insert(0, str(Path(__file__).parent.parent))

from oneiric.remote.models import RemoteManifest
from oneiric.remote.security import get_canonical_manifest_for_signing


def load_private_key(key_path: Path) -> Ed25519PrivateKey:
    try:
        with key_path.open("rb") as f:
            key_bytes = f.read()


        if len(key_bytes) == 32:
            return Ed25519PrivateKey.from_private_bytes(key_bytes)


        from cryptography.hazmat.primitives import serialization

        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
        )

        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Private key is not ED25519 type")

        return private_key

    except Exception as exc:
        raise ValueError(f"Failed to load private key: {exc}")


def sign_manifest(
    manifest_path: Path,
    private_key_path: Path,
    output_path: Path | None = None,
) -> RemoteManifest:

    print(f"Loading manifest: {manifest_path}")
    with manifest_path.open() as f:
        data = yaml.safe_load(f)

    manifest = RemoteManifest(**data)
    print(f"  Source: {manifest.source}")
    print(f"  Entries: {len(manifest.entries)}")


    print(f"\nLoading private key: {private_key_path}")
    private_key = load_private_key(private_key_path)
    print("  Algorithm: ED25519")


    print("\nGenerating canonical representation...")
    canonical = get_canonical_manifest_for_signing(manifest)
    print(f"  Canonical bytes: {len(canonical)} chars")


    print("\nSigning manifest...")
    signature_bytes = private_key.sign(canonical.encode())
    signature_b64 = base64.b64encode(signature_bytes).decode()


    manifest.signature = signature_b64
    manifest.signature_algorithm = "ed25519"


    output = output_path or manifest_path
    with output.open("w") as f:
        yaml.dump(
            manifest.model_dump(exclude_none=True),
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )

    print(f"\n✓ Signed manifest → {output}")
    print(f"  Signature (base64): {signature_b64[:64]}...")
    print(f"  Signature length: {len(signature_bytes)} bytes")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sign remote manifest with ED25519 private key",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

  python scripts/sign_manifest.py \\
    --manifest dist/manifest.yaml \\
    --private-key secrets/private_key.pem


  python scripts/sign_manifest.py \\
    --manifest dist/manifest.yaml \\
    --private-key secrets/private_key.pem \\
    --output dist/signed_manifest.yaml

Key Format:
  The private key must be ED25519 and can be:
  - PEM-encoded PKCS
  - Raw 32-byte key file

  Generate a new key pair:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()


    with open("private_key.pem", "wb") as f:
        f.write(private_key.private_bytes(...))


    with open("public_key.pem", "wb") as f:
        f.write(public_key.public_bytes(...))
        """,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to manifest YAML file to sign",
    )
    parser.add_argument(
        "--private-key",
        type=Path,
        required=True,
        help="Path to ED25519 private key (PEM or raw bytes)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for signed manifest (defaults to in-place update)",
    )

    args = parser.parse_args()


    if not args.manifest.exists():
        print(f"✗ Error: Manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    if not args.private_key.exists():
        print(f"✗ Error: Private key not found: {args.private_key}", file=sys.stderr)
        sys.exit(1)

    try:
        sign_manifest(args.manifest, args.private_key, args.output)
    except Exception as exc:
        print(f"\n✗ Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
