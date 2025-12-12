"""Route53 DNS adapter."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource


class Route53DNSSettings(BaseModel):
    """AWS Route53 configuration."""

    hosted_zone_id: str = Field(description="Hosted zone ID")
    region_name: str = Field(default="us-east-1")
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    session_token: SecretStr | None = None


class Route53DNSAdapter:
    """Manage DNS records via AWS Route53."""

    metadata = AdapterMetadata(
        category="dns",
        provider="route53",
        factory="oneiric.adapters.dns.route53:Route53DNSAdapter",
        capabilities=["record.manage", "record.list"],
        stack_level=30,
        priority=310,
        source=CandidateSource.LOCAL_PKG,
        owner="Platform Core",
        requires_secrets=True,
        settings_model=Route53DNSSettings,
    )

    def __init__(
        self,
        settings: Route53DNSSettings,
        *,
        client_factory: Callable[..., Coroutine[Any, Any, Any]] | None = None,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._client = client
        self._owns_client = client is None
        self._client_cm: Any = None
        self._logger = get_logger("adapter.dns.route53").bind(
            domain="adapter",
            key="dns",
            provider="route53",
        )

    async def init(self) -> None:
        """Initialize AWS client."""
        if self._client:
            self._logger.info("route53-dns-init-reuse-client")
            return
        if self._client_factory is not None:
            self._client = await self._client_factory()
            self._owns_client = True
            self._logger.info("route53-dns-init-factory")
            return

        try:
            import aioboto3
        except ModuleNotFoundError as exc:  # pragma: no cover - optional path
            raise LifecycleError(
                "aioboto3-is-required: install aioboto3 to use Route53DNSAdapter"
            ) from exc

        session = aioboto3.Session(
            aws_access_key_id=(
                self._settings.access_key_id.get_secret_value()
                if self._settings.access_key_id
                else None
            ),
            aws_secret_access_key=(
                self._settings.secret_access_key.get_secret_value()
                if self._settings.secret_access_key
                else None
            ),
            aws_session_token=(
                self._settings.session_token.get_secret_value()
                if self._settings.session_token
                else None
            ),
            region_name=self._settings.region_name,
        )
        self._client_cm = session.client("route53")
        self._client = await self._client_cm.__aenter__()
        self._owns_client = True
        self._logger.info("route53-dns-init")

    async def cleanup(self) -> None:
        """Dispose AWS client."""
        if self._owns_client and self._client_cm:
            await self._client_cm.__aexit__(None, None, None)
        self._client = None
        self._client_cm = None
        self._logger.info("route53-dns-cleanup")

    async def health(self) -> bool:
        client = self._ensure_client()
        try:
            resp = await client.list_resource_record_sets(
                HostedZoneId=self._settings.hosted_zone_id,
                MaxItems="1",
            )
            return "ResourceRecordSets" in resp
        except Exception as exc:  # pragma: no cover - network path
            self._logger.warning("route53-dns-health-failed", error=str(exc))
            return False

    async def list_records(
        self, *, record_type: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        client = self._ensure_client()
        params: dict[str, Any] = {
            "HostedZoneId": self._settings.hosted_zone_id,
        }
        if name:
            params["StartRecordName"] = name
        if record_type:
            params["StartRecordType"] = record_type
        resp = await client.list_resource_record_sets(**params)
        return resp.get("ResourceRecordSets", [])

    async def create_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str,
        ttl: int = 300,
    ) -> str:
        change = self._record_change("CREATE", name, record_type, content, ttl)
        resp = await self._change_record(change)
        return resp.get("ChangeInfo", {}).get("Id", "")

    async def update_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str,
        ttl: int = 300,
    ) -> str:
        change = self._record_change("UPSERT", name, record_type, content, ttl)
        resp = await self._change_record(change)
        return resp.get("ChangeInfo", {}).get("Id", "")

    async def delete_record(
        self,
        *,
        name: str,
        record_type: Literal["A", "AAAA", "CNAME", "TXT", "SRV", "MX", "NS"] = "A",
        content: str = "",
        ttl: int = 300,
    ) -> bool:
        change = self._record_change("DELETE", name, record_type, content, ttl)
        resp = await self._change_record(change)
        return bool(resp.get("ChangeInfo"))

    def _record_change(
        self,
        action: Literal["CREATE", "DELETE", "UPSERT"],
        name: str,
        record_type: str,
        content: str,
        ttl: int,
    ) -> dict[str, Any]:
        record = {
            "Action": action,
            "ResourceRecordSet": {
                "Name": name,
                "Type": record_type,
                "TTL": ttl,
                "ResourceRecords": [{"Value": content}],
            },
        }
        return record

    async def _change_record(self, change: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        try:
            resp = await client.change_resource_record_sets(
                HostedZoneId=self._settings.hosted_zone_id,
                ChangeBatch={"Changes": [change]},
            )
            return resp
        except Exception as exc:
            self._logger.error(
                "route53-dns-change-failed", error=str(exc), change=change
            )
            raise LifecycleError("route53-dns-change-failed") from exc

    def _ensure_client(self) -> Any:
        if self._client is None:
            raise LifecycleError("route53-dns-client-not-initialized")
        return self._client
