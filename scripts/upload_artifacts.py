#!/usr/bin/env python3
"""Upload artifacts (wheels, manifests) to S3/GCS.

This script uploads build artifacts to cloud storage for remote manifest delivery.

Usage:
    # Upload to S3
    python scripts/upload_artifacts.py \\
      --artifact dist/oneiric-1.0.0-py3-none-any.whl \\
      --backend s3 \\
      --bucket oneiric-releases \\
      --key releases/v1.0.0/oneiric.whl

    # Upload to GCS
    python scripts/upload_artifacts.py \\
      --artifact dist/manifest.yaml \\
      --backend gcs \\
      --bucket oneiric-releases \\
      --key releases/v1.0.0/manifest.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import boto3  # type: ignore
except ImportError:
    boto3 = None  # type: ignore

try:
    from google.cloud import storage  # type: ignore
except ImportError:
    storage = None  # type: ignore


def upload_to_s3(
    artifact_path: Path,
    bucket: str,
    key: str,
    region: str = "us-east-1",
    public_read: bool = False,
) -> str:
    """Upload artifact to AWS S3.

    Args:
        artifact_path: Path to local artifact file
        bucket: S3 bucket name
        key: Object key (path within bucket)
        region: AWS region (default: us-east-1)
        public_read: Whether to make object publicly readable

    Returns:
        Public HTTPS URL to uploaded artifact

    Raises:
        ImportError: If boto3 not installed
        Exception: If upload fails
    """
    if boto3 is None:
        raise ImportError(
            "boto3 is required for S3 uploads. Install with: pip install boto3"
        )

    print("Uploading to S3...")
    print(f"  Bucket: {bucket}")
    print(f"  Key: {key}")
    print(f"  Region: {region}")
    print(f"  File: {artifact_path} ({artifact_path.stat().st_size} bytes)")

    s3 = boto3.client("s3", region_name=region)

    # Build extra args
    extra_args = {}
    if public_read:
        extra_args["ACL"] = "public-read"

    # Upload
    with artifact_path.open("rb") as f:
        s3.upload_fileobj(f, bucket, key, ExtraArgs=extra_args or None)

    url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    print(f"\n✓ Uploaded to S3: {url}")
    return url


def upload_to_gcs(
    artifact_path: Path,
    bucket: str,
    blob_name: str,
    public_read: bool = False,
) -> str:
    """Upload artifact to Google Cloud Storage.

    Args:
        artifact_path: Path to local artifact file
        bucket: GCS bucket name
        blob_name: Blob name (path within bucket)
        public_read: Whether to make blob publicly readable

    Returns:
        Public HTTPS URL to uploaded artifact

    Raises:
        ImportError: If google-cloud-storage not installed
        Exception: If upload fails
    """
    if storage is None:
        raise ImportError(
            "google-cloud-storage is required for GCS uploads. "
            "Install with: pip install google-cloud-storage"
        )

    print("Uploading to GCS...")
    print(f"  Bucket: {bucket}")
    print(f"  Blob: {blob_name}")
    print(f"  File: {artifact_path} ({artifact_path.stat().st_size} bytes)")

    blob = storage.Client().bucket(bucket).blob(blob_name)

    # Upload
    blob.upload_from_filename(str(artifact_path))

    # Set public access if requested
    if public_read:
        blob.make_public()

    url = f"https://storage.googleapis.com/{bucket}/{blob_name}"
    print(f"\n✓ Uploaded to GCS: {url}")
    return url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload artifacts to S3 or GCS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload wheel to S3
  python scripts/upload_artifacts.py \\
    --artifact dist/oneiric-1.0.0-py3-none-any.whl \\
    --backend s3 \\
    --bucket oneiric-releases \\
    --key releases/v1.0.0/oneiric.whl \\
    --region us-east-1 \\
    --public-read

  # Upload manifest to GCS
  python scripts/upload_artifacts.py \\
    --artifact dist/manifest.yaml \\
    --backend gcs \\
    --bucket oneiric-releases \\
    --key releases/v1.0.0/manifest.yaml \\
    --public-read

Credentials:
  S3 requires AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
  GCS requires GOOGLE_APPLICATION_CREDENTIALS environment variable

Installation:
  S3:  pip install boto3
  GCS: pip install google-cloud-storage
        """,
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
        help="Path to artifact file to upload",
    )
    parser.add_argument(
        "--backend",
        choices=["s3", "gcs"],
        required=True,
        help="Cloud storage backend",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="Bucket name",
    )
    parser.add_argument(
        "--key",
        required=True,
        help="Object key/blob name (path within bucket)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (S3 only, default: us-east-1)",
    )
    parser.add_argument(
        "--public-read",
        action="store_true",
        help="Make uploaded artifact publicly readable",
    )

    args = parser.parse_args()

    # Validate artifact exists
    if not args.artifact.exists():
        print(f"✗ Error: Artifact not found: {args.artifact}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.backend == "s3":
            url = upload_to_s3(
                args.artifact,
                args.bucket,
                args.key,
                args.region,
                args.public_read,
            )
        else:
            url = upload_to_gcs(
                args.artifact,
                args.bucket,
                args.key,
                args.public_read,
            )

        print("\n✓ Upload complete")
        print(f"  URL: {url}")

    except ImportError as exc:
        print(f"\n✗ Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n✗ Upload failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
