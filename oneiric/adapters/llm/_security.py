"""Internal security utilities for the LLM module."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

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
        re.compile(r"[\"'][A-Za-z0-9+/=_~\-\.]{20,}[\"']"),
        "<redacted>",
    ),  # quoted long secrets
    # Assignment forms: ``api_key=…``, ``token: …``, ``x-bf-vk=…``. The label
    # may be quoted (``"api_key": "…"`` is JSON, and the label is followed
    # by a closing quote before the separator), and the value may be
    # quoted. The label is kept so the redacted diagnostic still says
    # which credential it was.
    (
        re.compile(
            r"(?i)([\"']?\b(?:api[_-]?key|access[_-]?token|token|secret|password|"
            r"passwd|credential|x-bf-vk)\b[\"']?\s*[=:]\s*)"
            r"[\"']?[^\s\"',}\]]+[\"']?"
        ),
        r"\1<redacted>",
    ),
]

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
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local, includes AWS/Azure IMDS
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("192.0.0.192/32"),  # Oracle Cloud metadata
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local (covers fd00::/8)
    ipaddress.ip_network("fd00:ec2::254/128"),  # Oracle Cloud metadata (IMDSv6)
    # IPv4-mapped IPv6. The whole mapped range is refused: the form is
    # an attempt to present an IPv4 address to an IPv6-shaped check, and
    # plain IPv4 (127.0.0.1 for the local gateway) stays available.
    ipaddress.ip_network("::ffff:0:0/96"),
)

#: Hostnames that name the loopback interface.
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def sanitize_error(msg: str) -> str:
    """Strip secrets from error messages before logging."""
    for pattern, replacement in _SECRET_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg


def scrub_url(url: str) -> str:
    """Strip everything credential-shaped from a URL before logging it.

    Rebuilding from the parsed parts beats a regex here. A userinfo
    pattern has two holes: a password may contain ``/`` (which stops a
    ``[^@/]`` pattern dead), and a *query string* can carry the
    credential outright -- ``?api_key=…`` is not userinfo at all. A URL
    with credentials in it is reported as ``scheme://***`` and a URL
    without them keeps its host and path but loses the query and the
    fragment.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparsable url>"
    if not parts.scheme and not parts.netloc:
        # Not a URL at all (an unresolved ``${ENV_VAR}`` placeholder).
        return url
    if parts.username is not None or parts.password is not None:
        return f"{parts.scheme}://***"
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        # An authority whose colon does not introduce a valid port is a
        # userinfo fragment in all but name (``user:pa/ss@host`` parses
        # its authority as "user:pa" because the slash ends it early).
        return f"{parts.scheme}://***"
    netloc = f"{host}:{port}" if port else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether an address falls in a blocked network.

    The containment test is family-sensitive -- an IPv6 address compared
    against an IPv4 network is silently *not* a member -- so the version
    is checked explicitly and an IPv4-mapped address is tested both as
    the IPv6 address it is and as the IPv4 address it carries.
    """
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if ip.version == 6:
        mapped = ip.ipv4_mapped
        if mapped is not None:
            candidates.append(mapped)
    for candidate in candidates:
        for network in BLOCKED_NETWORKS:
            if candidate.version != network.version:
                continue
            if candidate in network:
                return True
    return False


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
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        # A literal address gets the same blocked-address rule as a
        # resolved one, so the two paths cannot disagree.
        if _is_blocked_address(literal):
            raise ValueError(
                f"base_url host {host!r} is in a blocked network; refusing to "
                "send a provider credential there"
            )
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
