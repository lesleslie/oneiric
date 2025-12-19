"""HTTP helper utilities shared across adapters and actions."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import httpx

from oneiric.core.observability import observed_span


async def observed_http_request(
    *,
    domain: str,
    key: str,
    adapter: str,
    provider: str,
    operation: str,
    url: str,
    component: str,
    span_name: str,
    send: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    from oneiric.adapters.metrics import record_adapter_request_metrics

    span_attrs = {
        "oneiric.domain": domain,
        "oneiric.key": key,
        "oneiric.provider": provider,
        "oneiric.operation": operation,
        "http.method": operation,
        "http.url": str(url),
    }
    start = time.perf_counter()
    success = False
    timeout_hit = False
    with observed_span(
        span_name,
        component=component,
        attributes=span_attrs,
        log_context={
            "domain": domain,
            "key": key,
            "provider": provider,
            "operation": operation,
        },
    ) as span:
        try:
            response = await send()
        except httpx.TimeoutException as exc:
            timeout_hit = True
            span.record_exception(exc)
            span.set_attributes({"http.timeout": True, "oneiric.success": False})
            raise
        except httpx.HTTPError as exc:
            span.record_exception(exc)
            span.set_attributes({"oneiric.success": False})
            raise
        else:
            success = response.is_success
            span.set_attributes(
                {"http.status_code": response.status_code, "oneiric.success": success}
            )
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            record_adapter_request_metrics(
                domain=domain,
                adapter=adapter,
                provider=provider,
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                timeout=timeout_hit,
            )
