from __future__ import annotations

from collections.abc import Callable

from oneiric.core.config import LayerSettings, OneiricSettings


def create_layer_selector(
    domain_name: str,
) -> Callable[[OneiricSettings], LayerSettings]:
    def selector(settings: OneiricSettings) -> LayerSettings:
        return getattr(settings, f"{domain_name}s")

    return selector


def get_domain_settings(settings: OneiricSettings, domain: str) -> LayerSettings:
    return getattr(settings, f"{domain}s")


SUPPORTED_DOMAINS = [
    "adapter",
    "service",
    "task",
    "event",
    "workflow",
    "action",
]


def is_supported_domain(domain: str) -> bool:
    return domain in SUPPORTED_DOMAINS
