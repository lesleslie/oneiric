"""Helpers for routing workflow.notify payloads to ChatOps adapters."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from oneiric.adapters import AdapterBridge
from oneiric.adapters.messaging.common import (
    MessagingSendResult,
    NotificationMessage,
)
from oneiric.core.lifecycle import LifecycleError
from oneiric.core.logging import get_logger


@dataclass
class NotificationRoute:
    """Configuration describing how to deliver a workflow notification."""

    adapter_key: str | None = None
    adapter_provider: str | None = None
    target: str | None = None
    channel: str | None = None
    title: str | None = None
    title_template: str | None = None
    include_context: bool = True
    extra_payload: dict[str, Any] | None = None


class NotificationRouter:
    """Routes workflow.notify payloads to messaging adapters."""

    def __init__(
        self,
        adapter_bridge: AdapterBridge,
        *,
        default_adapter_key: str | None = None,
    ) -> None:
        self._adapter_bridge = adapter_bridge
        self._default_adapter_key = default_adapter_key
        self._logger = get_logger("runtime.notifications")

    @property
    def default_adapter_key(self) -> str | None:
        return self._default_adapter_key

    async def send(
        self,
        record: Mapping[str, Any],
        route: NotificationRoute | None = None,
    ) -> MessagingSendResult | None:
        """Send a workflow notification using the resolved adapter."""

        route = route or NotificationRoute()
        adapter_key = route.adapter_key or self._default_adapter_key
        if not adapter_key:
            self._logger.info(
                "notification-skip",
                reason="adapter-missing",
            )
            return None

        handle = await self._adapter_bridge.use(
            adapter_key, provider=route.adapter_provider
        )
        sender = getattr(handle.instance, "send_notification", None)
        if not callable(sender):
            raise LifecycleError(
                f"Adapter '{adapter_key}' missing send_notification handler"
            )

        message = self._build_message(record, route)
        result = sender(message)
        if inspect.isawaitable(result):
            result = await result
        self._logger.info(
            "notification-sent",
            adapter=adapter_key,
            provider=handle.provider,
            target=message.target,
            status=getattr(result, "status_code", None),
        )
        return result

    def _build_message(
        self,
        record: Mapping[str, Any],
        route: NotificationRoute,
    ) -> NotificationMessage:
        title = self._resolve_title(record, route)
        target = route.target or route.channel or record.get("channel")
        text = self._render_text(record, include_context=route.include_context)
        extra_payload = dict(route.extra_payload or {})
        return NotificationMessage(
            text=text,
            title=title,
            target=target,
            extra_payload=extra_payload,
        )

    def _resolve_title(
        self, record: Mapping[str, Any], route: NotificationRoute
    ) -> str:
        if route.title:
            return route.title
        if route.title_template:
            try:
                return route.title_template.format(
                    level=str(record.get("level", "info")).upper(),
                    channel=record.get("channel", "workflow"),
                    message=record.get("message", ""),
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                self._logger.warning(
                    "notification-title-template-error",
                    template=route.title_template,
                    error=str(exc),
                )
        level = str(record.get("level", "info")).upper()
        channel = record.get("channel", "workflow")
        return f"[{level}] {channel}"

    def _render_text(
        self,
        record: Mapping[str, Any],
        *,
        include_context: bool,
    ) -> str:
        base = str(record.get("message") or "").strip()
        if not base:
            base = f"{record.get('channel', 'workflow')} notification"

        context = record.get("context")
        if include_context and isinstance(context, Mapping) and context:
            context_lines = "\n".join(
                f"- {key}: {context[key]}" for key in sorted(context)
            )
            base = f"{base}\n\nContext:\n{context_lines}"
        return base
