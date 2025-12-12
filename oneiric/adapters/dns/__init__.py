"""DNS adapters."""

from .cloudflare import CloudflareDNSAdapter, CloudflareDNSSettings
from .route53 import Route53DNSAdapter, Route53DNSSettings

__all__ = [
    "CloudflareDNSAdapter",
    "CloudflareDNSSettings",
    "Route53DNSAdapter",
    "Route53DNSSettings",
]
