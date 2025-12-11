"""DynamoDB adapter built on aioboto3."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from pydantic import Field, SecretStr

from oneiric.adapters.metadata import AdapterMetadata
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger
from oneiric.core.resolution import CandidateSource

from .common import NoSQLAdapterBase, NoSQLBaseSettings, NoSQLDocument


class DynamoDBSettings(NoSQLBaseSettings):
    """Configuration for the DynamoDB adapter."""

    table_name: str = Field(
        default="oneiric", description="Target DynamoDB table name."
    )
    region_name: str = Field(
        default="us-east-1", description="AWS region for the table."
    )
    endpoint_url: str | None = Field(
        default=None,
        description="Custom endpoint for local testing (e.g., LocalStack).",
    )
    aws_access_key_id: SecretStr | None = Field(
        default=None, description="Optional AWS access key."
    )
    aws_secret_access_key: SecretStr | None = Field(
        default=None, description="Optional AWS secret key."
    )
    aws_session_token: SecretStr | None = Field(
        default=None, description="Optional AWS session token."
    )
    profile_name: str | None = Field(
        default=None, description="Named AWS profile to load via shared credentials."
    )
    consistent_reads: bool = Field(
        default=False, description="Use strongly consistent reads by default."
    )
    primary_key_field: str = Field(
        default="id",
        description="Field used as the document identifier when shaping responses.",
    )


class DynamoDBAdapter(NoSQLAdapterBase):
    """Adapter that wraps DynamoDB tables via aioboto3."""

    metadata = AdapterMetadata(
        category="nosql",
        provider="dynamodb",
        factory="oneiric.adapters.nosql.dynamodb:DynamoDBAdapter",
        capabilities=["documents", "key-value", "scan", "conditional_writes"],
        stack_level=30,
        priority=430,
        source=CandidateSource.LOCAL_PKG,
        owner="Data Platform",
        requires_secrets=True,
        settings_model=DynamoDBSettings,
    )

    def __init__(
        self,
        settings: DynamoDBSettings,
        *,
        session_factory: Callable[[], Any] | None = None,
        table_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(settings)
        self._settings = settings
        self._session_factory = session_factory
        self._table_factory = table_factory
        self._session: Any | None = None
        self._logger = get_logger("adapter.nosql.dynamodb").bind(
            domain="adapter",
            key="nosql",
            provider="dynamodb",
        )

    async def init(self) -> None:
        self._ensure_session()
        self._logger.info("dynamodb-adapter-init")

    async def health(self) -> bool:
        try:
            async with self._table() as table:
                loader = getattr(table, "load", None)
                if loader:
                    await loader()
            return True
        except Exception as exc:  # pragma: no cover - network/runtime errors
            self._logger.warning("dynamodb-health-check-failed", error=str(exc))
            return False

    async def cleanup(self) -> None:
        self._session = None
        self._logger.info("dynamodb-adapter-cleanup")

    async def get_item(
        self,
        key: dict[str, Any],
        *,
        consistent_read: bool | None = None,
    ) -> NoSQLDocument | None:
        async with self._table() as table:
            params = {
                "Key": key,
                "ConsistentRead": consistent_read
                if consistent_read is not None
                else self._settings.consistent_reads,
            }
            response = await table.get_item(**params)
        return self._document_from_item(response.get("Item"))

    async def put_item(
        self, item: dict[str, Any], *, condition_expression: str | None = None
    ) -> bool:
        async with self._table() as table:
            kwargs: dict[str, Any] = {"Item": item}
            if condition_expression:
                kwargs["ConditionExpression"] = condition_expression
            await table.put_item(**kwargs)
        return True

    async def update_item(
        self,
        key: dict[str, Any],
        *,
        update_expression: str,
        expression_attribute_values: dict[str, Any],
        condition_expression: str | None = None,
    ) -> dict[str, Any]:
        async with self._table() as table:
            kwargs: dict[str, Any] = {
                "Key": key,
                "UpdateExpression": update_expression,
                "ExpressionAttributeValues": expression_attribute_values,
                "ReturnValues": "UPDATED_NEW",
            }
            if condition_expression:
                kwargs["ConditionExpression"] = condition_expression
            response = await table.update_item(**kwargs)
        return response.get("Attributes", {})

    async def delete_item(
        self, key: dict[str, Any], *, condition_expression: str | None = None
    ) -> bool:
        async with self._table() as table:
            kwargs: dict[str, Any] = {"Key": key}
            if condition_expression:
                kwargs["ConditionExpression"] = condition_expression
            await table.delete_item(**kwargs)
        return True

    async def scan(self, *, limit: int | None = None) -> list[NoSQLDocument]:
        async with self._table() as table:
            kwargs: dict[str, Any] = {}
            if limit:
                kwargs["Limit"] = limit
            response = await table.scan(**kwargs)
        items = response.get("Items", [])
        return [doc for item in items if (doc := self._document_from_item(item))]

    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        factory = self._session_factory
        if factory is None:
            try:
                import aioboto3  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
                raise LifecycleError(
                    "aioboto3-not-installed: install optional extra 'oneiric[nosql-dynamo]' to use DynamoDBAdapter"
                ) from exc
            profile = self._settings.profile_name
            if profile:

                def factory():
                    return aioboto3.Session(profile_name=profile)
            else:
                factory = aioboto3.Session
        session = factory()
        self._session = session
        return session

    @asynccontextmanager
    async def _table(self) -> AsyncIterator[Any]:
        if self._table_factory:
            table = self._table_factory()
            if inspect.isawaitable(table):
                table = await table
            yield table
            return
        session = self._ensure_session()
        resource_kwargs = {
            "region_name": self._settings.region_name,
            "endpoint_url": self._settings.endpoint_url,
        }
        credentials = {
            "aws_access_key_id": self._settings.aws_access_key_id.get_secret_value()
            if self._settings.aws_access_key_id
            else None,
            "aws_secret_access_key": self._settings.aws_secret_access_key.get_secret_value()
            if self._settings.aws_secret_access_key
            else None,
            "aws_session_token": self._settings.aws_session_token.get_secret_value()
            if self._settings.aws_session_token
            else None,
        }
        for key, value in credentials.items():
            if value is not None:
                resource_kwargs[key] = value
        resource_kwargs = {k: v for k, v in resource_kwargs.items() if v is not None}
        resource = session.resource("dynamodb", **resource_kwargs)
        async with resource as dynamodb:
            table = dynamodb.Table(self._settings.table_name)
            yield table

    def _document_from_item(self, item: dict[str, Any] | None) -> NoSQLDocument | None:
        if not item:
            return None
        payload = dict(item)
        key_value = payload.pop(self._settings.primary_key_field, None)
        doc_id = str(key_value) if key_value is not None else None
        return NoSQLDocument(id=doc_id, data=payload)
