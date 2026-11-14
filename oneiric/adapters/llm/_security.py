"""Internal security utilities for the LLM module."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from urllib.parse import urlsplit

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"sk-[a-zA-Z0-9\-]{20,}"),
        "<redacted>",
    ),  # Anthropic / OpenAI sk- keys (may contain hyphens)
    (
        re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]*)?"),
        "<redacted>",
    ),  # JWT / MiniMax Token Plan keys -- all three segments, the signature included
    (
        re.compile(r"Bearer [a-zA-Z0-9\-._~+/]{16,}"),
        "<redacted>",
    ),  # Bearer header values
    (
        re.compile(r"[\"'][A-Za-z0-9+/=_\-\.]{32,}[\"']"),
        "<redacted>",
    ),  # quoted long secrets
    # Assignment forms: ``api_key=…``, ``token: …``, ``x-bf-vk=…``. The label
    # is kept so the redacted diagnostic still says which credential it was.
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password|passwd|"
            r"credential|x-bf-vk)(\s*[=:]\s*)\"?[^\s\"']+"
        ),
        r"\1\2<redacted>",
    ),
]

#: Captures the scheme + "://" so ``userinfo@`` can be stripped from a URL.
_URL_USERINFO_RE = re.compile(r"^([a-z][a-z0-9+.\-]*://)[^@/\s]+@", re.IGNORECASE)

#: Hostnames that resolve to a cloud metadata service.
BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)

#: Networks that must never receive a provider credential.
#:
#: Loopback (``127.0.0.0/8``, ``::1``) is deliberately absent: the local
#: Bifrost gateway and the local llama-server are loopback services.
BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, includes AWS/Azure IMDS
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("192.0.0.192/32"),  # Oracle Cloud metadata
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
)

#: Hostnames that name the loopback interface.
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def sanitize_error(msg: str) -> str:
    """Strip secrets from error messages before logging."""
    for pattern, replacement in _SECRET_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg


def scrub_url(url: str) -> str:
    """Strip ``user:password@`` userinfo from a URL before logging it."""
    return _URL_USERINFO_RE.sub(r"\1***@", url)


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in BLOCKED_NETWORKS)


def validate_base_url(url: str) -> str:
    """Reject a ``base_url`` that would point a credential at a metadata service.

    A provider sends its API key in the ``Authorization`` header to whatever
    ``base_url`` names. A base URL that resolves to a cloud metadata
    endpoint or a private network turns that key into a credential handed
    to whoever controls that address.

    Rules:

    * a literal address in a blocked network (link-local, the cloud
      metadata services, RFC1918) is rejected;
    * a plain-HTTP URL is accepted only for loopback -- the local Bifrost
      gateway and the local llama-server;
    * a known metadata hostname is rejected.

    The host's *resolved* address is re-checked at request time by
    :func:`assert_resolved_host_allowed`, because a hostname that passes
    here can still resolve to a blocked address later.

    Raises:
        ValueError: If the URL is not acceptable.
    """
    if not url:
        return url

    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise ValueError(f"base_url {scrub_url(url)!r} has no host")

    normalized = host.lower().rstrip(".")
    if normalized in BLOCKED_HOSTNAMES:
        raise ValueError(
            f"base_url host {host!r} is a cloud metadata endpoint; refusing to "
            "send a provider credential there"
        )

    scheme = parts.scheme.lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None:
        if _is_blocked_address(address):
            raise ValueError(
                f"base_url host {host!r} is in a blocked network; refusing to "
                "send a provider credential there"
            )
        if not address.is_loopback and scheme != "https":
            raise ValueError(
                f"base_url {scrub_url(url)!r} must use https for a non-loopback host"
            )
        return url

    if normalized in _LOOPBACK_HOSTNAMES:
        return url

    if scheme != "https":
        raise ValueError(
            f"base_url {scrub_url(url)!r} must use https for a non-loopback host"
        )
    return url


async def assert_resolved_host_allowed(url: str) -> None:
    """Re-check the resolved address of a ``base_url`` before sending a credential.

    Static URL validation cannot catch DNS rebinding: a hostname that
    passes :func:`validate_base_url` can resolve to a blocked address by
    the time the request is sent. This resolves the host and rejects a
    blocked address.

    Residual window: the client resolves the name again when it opens the
    connection, so a host that rebinds *between* this check and that
    resolution is not caught. Closing that window needs address pinning in
    the HTTP client, not a pre-flight check.

    Raises:
        ValueError: If the host resolves to a blocked address, or cannot
            be resolved at all.
    """
    host = urlsplit(url).hostname
    if not host:
        return
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # A literal address was already judged by validate_base_url.
        return

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"could not resolve base_url host {host!r}: {exc}") from exc

    for info in infos:
        raw = info[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _is_blocked_address(address):
            raise ValueError(
                f"base_url host {host!r} resolves to the blocked address "
                f"{address}; refusing to send a provider credential there"
            )
