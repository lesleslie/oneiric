"""DNS adapters."""

from .cloudflare import CloudflareDNSAdapter, CloudflareDNSSettings
from .gcdns import GCDNSAdapter, GCDNSSettings
from .route53 import Route53DNSAdapter, Route53DNSSettings

__all__ = [
    "CloudflareDNSAdapter",
    "CloudflareDNSSettings",
    "GCDNSAdapter",
    "GCDNSSettings",
    "Route53DNSAdapter",
    "Route53DNSSettings",
]
