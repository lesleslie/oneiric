"""Google Cloud DNS adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class GCDNSSettings(BaseModel):
    """Configuration for Google Cloud DNS."""

    managed_zone: str = Field(description="Name of the managed zone.")
    project_id: str | None = Field(default=None, description="GCP project ID.")
    credentials_file: Path | None = Field(
        default=None,
        description="Optional path to a service account JSON file.",
    )
    default_ttl: int = Field(default=300, ge=0, description="Default record TTL.")


class GCDNSAdapter:
    """Manage DNS records via Google Cloud DNS."""

    metadata = AdapterMetadata(
        category="dns",
        provider="gcdns",
        factory="oneiric.adapters.dns.gcdns:GCDNSAdapter",
        capabilities=["record.manage", "record.list"],
        stack_level=30,
        priority=330,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=GCDNSSettings,
    )

    def __init__(
        self,
        settings: GCDNSSettings,
        *,
        client: Any | None = None,
        zone: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._zone = zone
        self._logger = get_logger("adapter.dns.gcdns").bind(
            domain="adapter",
            key="dns",
            provider="gcdns",
            zone=settings.managed_zone,
        )

    async def init(self) -> None:
        """Initialize the DNS client and managed zone."""
        if self._zone is not None:
            self._logger.info("gcdns-init-zone-reuse")
            return
        if self._client is None:
            self._client = self._create_client()
        self._zone = self._client.zone(self._settings.managed_zone)
        self._logger.info("gcdns-init")

    async def cleanup(self) -> None:
        self._client = None
        self._zone = None
        self._logger.info("gcdns-cleanup")

    async def health(self) -> bool:
        zone = self._ensure_zone()
        try:
            exists = await asyncio.to_thread(zone.exists)
            return bool(exists)
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("gcdns-health-failed", error=str(exc))
            return False

    async def list_records(
        self, *, record_type: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        zone = self._ensure_zone()
        records = await asyncio.to_thread(self._list_record_sets, zone)
        result: list[dict[str, Any]] = []
        for record in records:
            if record_type and record.record_type != record_type:
                continue
            if name and record.name != name:
                continue
            result.append(
                {
                    "name": record.name,
                    "type": record.record_type,
                    "ttl": record.ttl,
                    "rrdatas": list(record.rrdatas or []),
                }
            )
        return result

    async def create_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str,
        ttl: int | None = None,
    ) -> str:
        zone = self._ensure_zone()
        record_set = zone.resource_record_set(
            name,
            record_type,
            ttl or self._settings.default_ttl,
            [content],
        )
        change = zone.changes()
        change.add_record_set(record_set)
        await self._create_change(change)
        return str(getattr(change, "id", ""))

    async def update_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str,
        ttl: int | None = None,
    ) -> str:
        zone = self._ensure_zone()
        existing = await self._list_matching(zone, name=name, record_type=record_type)
        record_set = zone.resource_record_set(
            name,
            record_type,
            ttl or self._settings.default_ttl,
            [content],
        )
        change = zone.changes()
        for record in existing:
            change.delete_record_set(record)
        change.add_record_set(record_set)
        await self._create_change(change)
        return str(getattr(change, "id", ""))

    async def delete_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str | None = None,
        ttl: int | None = None,
    ) -> bool:
        zone = self._ensure_zone()
        change = zone.changes()
        if content:
            record_set = zone.resource_record_set(
                name,
                record_type,
                ttl or self._settings.default_ttl,
                [content],
            )
            change.delete_record_set(record_set)
        else:
            existing = await self._list_matching(
                zone, name=name, record_type=record_type
            )
            for record in existing:
                change.delete_record_set(record)
        await self._create_change(change)
        return True

    def _create_client(self) -> Any:
        try:
            from google.cloud import dns  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise LifecycleError(
                "google-cloud-dns-missing: install 'oneiric[dns-gcdns]' to use GCDNSAdapter"
            ) from exc

        credentials = None
        if self._settings.credentials_file:
            try:
                from google.oauth2 import service_account  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
                raise LifecycleError(
                    "google-auth-missing: install google-auth to load service account credentials"
                ) from exc
            credentials = service_account.Credentials.from_service_account_file(
                str(self._settings.credentials_file)
            )

        return dns.Client(project=self._settings.project_id, credentials=credentials)

    def _ensure_zone(self) -> Any:
        if self._zone is None:
            raise LifecycleError("gcdns-zone-not-initialized")
        return self._zone

    def _list_record_sets(self, zone: Any) -> list[Any]:  # type: ignore[valid-type]
        return list(zone.list_resource_record_sets())

    async def _list_matching(
        self, zone: Any, *, name: str, record_type: str
    ) -> list[Any]:
        records = await asyncio.to_thread(self._list_record_sets, zone)
        return [
            record
            for record in records
            if record.name == name and record.record_type == record_type
        ]

    async def _create_change(self, change: Any) -> None:
        try:
            await asyncio.to_thread(change.create)
        except Exception as exc:
            self._logger.error("gcdns-change-failed", error=str(exc))
            raise LifecycleError("gcdns-change-failed") from exc
