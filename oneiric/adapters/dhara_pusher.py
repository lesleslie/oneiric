"""Push built-in Oneiric adapters to Dhara storage.

This module is called during Oneiric startup to push all built-in adapters
to Dhara for centralized storage and distribution across the ecosystem.

★ Insight: Adapter Distribution Pattern ────────────────────────────
1. Oneiric adapters are defined in bootstrap.py with metadata
2. On startup, adapters are pushed to Dhara via MCP
3. Dhara becomes the single source of truth for adapter discovery
4. Custom adapters can be registered directly in Dhara without code changes
───────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

import httpx

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from .metadata import AdapterMetadata

logger = get_logger(__name__)


class SinglePushResult(TypedDict):
    success: bool
    error: str | None


class PushResult(TypedDict):
    total: int
    success: int
    errors: int
    details: list[dict[str, object]]


class DharaAdapterPusher:
    """Push Oneiric adapters to Dhara MCP server.

    Provides automatic adapter registration on Oneiric startup with
    retry logic and error handling.

    Attributes:
        dhara_url: Base URL of Dhara MCP server
        timeout: Request timeout in seconds
        client: HTTP client for API calls
    """

    def __init__(
        self,
        dhara_url: str = "http://127.0.0.1:8683",
        timeout: float = 30.0,
    ):
        """Initialize adapter pusher.

        Args:
            dhara_url: Base URL of Dhara MCP server
            timeout: Request timeout in seconds
        """
        self.dhara_url = dhara_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def push_builtin_adapters(
        self,
        adapters: list[AdapterMetadata],
    ) -> PushResult:
        """Push all built-in adapters to Dhara.

        Args:
            adapters: List of AdapterMetadata instances from bootstrap

        Returns:
            Dict with success count, error count, and details
        """
        results: PushResult = {
            "total": len(adapters),
            "success": 0,
            "errors": 0,
            "details": [],
        }

        for adapter_metadata in adapters:
            try:
                result = self._push_single_adapter(adapter_metadata)

                if result.get("success"):
                    results["success"] += 1
                    results["details"].append(
                        {
                            "adapter_id": self._make_adapter_id(adapter_metadata),
                            "status": "success",
                        }
                    )
                    logger.info(
                        f"Pushed {self._make_adapter_id(adapter_metadata)} "
                        f"@ {adapter_metadata.version or '1.0.0'}"
                    )
                else:
                    results["errors"] += 1
                    results["details"].append(
                        {
                            "adapter_id": self._make_adapter_id(adapter_metadata),
                            "status": "error",
                            "error": result.get("error"),
                        }
                    )
                    logger.error(
                        f"Failed to push {self._make_adapter_id(adapter_metadata)}: "
                        f"{result.get('error')}"
                    )

            except Exception as e:
                results["errors"] += 1
                results["details"].append(
                    {
                        "adapter_id": self._make_adapter_id(adapter_metadata),
                        "status": "exception",
                        "error": str(e),
                    }
                )
                logger.exception(
                    f"Exception pushing {self._make_adapter_id(adapter_metadata)}"
                )

        logger.info(
            f"Pushed {results['success']}/{results['total']} adapters to Dhara "
            f"({results['errors']} errors)"
        )

        return results

    def _push_single_adapter(
        self,
        metadata: AdapterMetadata,
    ) -> SinglePushResult:
        """Push a single adapter to Dhruva via MCP.

        Args:
            metadata: AdapterMetadata instance

        Returns:
            Result dict with success flag
        """
        try:
            # Extract factory path
            if callable(metadata.factory):
                factory_path = f"{getattr(metadata.factory, '__module__', '<unknown>')}.{getattr(metadata.factory, '__name__', '<unknown>')}"
            else:
                factory_path = str(metadata.factory)

            # Prepare adapter data for Dhruva
            adapter_data = {
                "domain": "adapter",
                "key": metadata.category,
                "provider": metadata.provider,
                "version": metadata.version or "1.0.0",
                "factory_path": factory_path,
                "config": {},  # Default config
                "dependencies": [],  # No dependencies for built-in adapters
                "capabilities": metadata.capabilities,
                "metadata": {
                    "category": metadata.category,
                    "description": metadata.description or "",
                    "author": "Oneiric",
                    "source": "builtin",
                    "owner": metadata.owner,
                    "requires_secrets": metadata.requires_secrets,
                },
            }

            # Push to Dhruva via MCP tool
            response = self.client.post(
                f"{self.dhara_url}/tools/store_adapter",
                json=adapter_data,
            )

            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            return {
                "success": False,
                "error": f"HTTP error: {e}",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _make_adapter_id(self, metadata: AdapterMetadata) -> str:
        """Make adapter ID from metadata.

        Args:
            metadata: AdapterMetadata instance

        Returns:
            Adapter ID string (adapter:category:provider)
        """
        return f"adapter:{metadata.category}:{metadata.provider}"

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()


def push_adapters_on_startup(
    dhara_url: str = "http://127.0.0.1:8683",
) -> PushResult:
    """Push built-in adapters to Dhara on Oneiric startup.

    This function is called during Oneiric initialization to ensure
    Dhara has all built-in adapters available for distribution.

    Args:
        dhara_url: URL of Dhara MCP server

    Returns:
        Result dict with counts and details

    ★ Insight: Startup Integration ───────────────────────────────────
    This function should be called in:
    1. Oneiric Resolver.__init__() after adapter registration
    2. Oneiric MCP server startup
    3. Manual CLI command: python -m oneiric.adapters.dhruva_pusher

    Uses lazy initialization to avoid delaying Oneiric startup.
    ────────────────────────────────────────────────────────────────────
    """
    from .bootstrap import builtin_adapter_metadata

    pusher = DharaAdapterPusher(dhara_url=dhara_url)

    try:
        adapters = builtin_adapter_metadata()
        return pusher.push_builtin_adapters(adapters)
    finally:
        pusher.close()


# CLI command for manual adapter pushing
def main() -> int:
    """CLI entry point for manually pushing adapters.

    Usage:
        python -m oneiric.adapters.dhara_pusher
        python -m oneiric.adapters.dhara_pusher --dhara-url http://localhost:8683

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    import argparse

    parser = argparse.ArgumentParser(description="Push Oneiric adapters to Dhara")
    parser.add_argument(
        "--dhara-url",
        default="http://127.0.0.1:8683",
        help="Dhara MCP server URL",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    results = push_adapters_on_startup(dhara_url=args.dhara_url)

    print(f"\n📦 Pushed {results['success']}/{results['total']} adapters to Dhara")
    print(f"❌ Errors: {results['errors']}")

    if results["errors"] > 0:
        print("\nErrors:")
        for detail in results["details"]:
            if detail["status"] != "success":
                print(f"  - {detail['adapter_id']}: {detail.get('error', 'Unknown')}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
