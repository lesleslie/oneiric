"""SSRF defense tests for ``BifrostLLMSettings``.

REQ-BIFROST-016. Pydantic ``HttpUrl`` + loopback-only default +
IMDS / RFC1918 blocklist in the opt-in path.

The opt-in path is governed by the ``BIFROST_ALLOW_REMOTE=1`` env var
(operator-controlled). The blocklist is non-negotiable — an operator
who opts in to non-loopback URLs still cannot pivot to AWS / GCP /
Azure IMDS or RFC1918 ranges.
"""

from __future__ import annotations

import pytest

from oneiric.adapters.llm.bifrost import BifrostLLMSettings


# ---------------------------------------------------------------------------
# Default: loopback-only
# ---------------------------------------------------------------------------


def test_default_settings_are_loopback() -> None:
    """The Pydantic default (no env-var override) is loopback-only."""
    s = BifrostLLMSettings()
    assert s.base_url.host == "127.0.0.1"
    assert s.anthropic_base_url.host == "127.0.0.1"


def test_loopback_url_accepted() -> None:
    """127.0.0.1 (the default) is accepted by the validator."""
    s = BifrostLLMSettings(
        base_url="http://127.0.0.1:9000",  # type: ignore[arg-type]
        anthropic_base_url="http://127.0.0.1:9000/anthropic",  # type: ignore[arg-type]
    )
    assert s.base_url.host == "127.0.0.1"


def test_non_loopback_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ``BIFROST_ALLOW_REMOTE=1``, a non-loopback URL raises."""
    monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError, match="non-loopback host"):
        BifrostLLMSettings(
            base_url="http://api.example.com",  # type: ignore[arg-type]
        )


def test_non_loopback_local_provider_url_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The validator runs on every URL field, including ``local_provider_url``."""
    monkeypatch.delenv("BIFROST_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError, match="non-loopback host"):
        BifrostLLMSettings(
            local_provider_enabled=True,
            local_provider_url="http://10.0.0.5:8081",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Opt-in path: BIFROST_ALLOW_REMOTE=1
# ---------------------------------------------------------------------------


def test_allow_remote_accepts_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the opt-in, a public URL is accepted."""
    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    s = BifrostLLMSettings(
        base_url="http://gateway.example.com:8471",  # type: ignore[arg-type]
    )
    assert s.base_url.host == "gateway.example.com"


# ---------------------------------------------------------------------------
# Opt-in path: still blocks IMDS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",  # AWS / Azure IMDS
        "169.254.169.253",  # AWS IMDS alt
        "100.100.100.200",  # GCP IMDS
    ],
)
def test_allow_remote_blocks_imds_ipv4(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opt-in path explicitly rejects the IMDS IPv4 endpoints."""
    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="IMDS / RFC1918 blocklist"):
        BifrostLLMSettings(base_url=f"http://{host}:80")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "host",
    [
        "metadata.google.internal",
        "metadata.azure.com",
    ],
)
def test_allow_remote_blocks_imds_hostnames(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opt-in path rejects the metadata service hostnames."""
    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="IMDS / RFC1918 blocklist"):
        BifrostLLMSettings(base_url=f"http://{host}")  # type: ignore[arg-type]


def test_allow_remote_blocks_aws_imds_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-in path also blocks the AWS IMDS IPv6 endpoint."""
    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="IMDS / RFC1918 blocklist"):
        BifrostLLMSettings(base_url="http://[fd00:ec2::254]:80")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Opt-in path: still blocks RFC1918
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "10.0.0.5",  # RFC1918 10/8
        "172.16.0.5",  # RFC1918 172.16/12
        "192.168.1.5",  # RFC1918 192.168/16
    ],
)
def test_allow_remote_blocks_rfc1918(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opt-in path explicitly rejects RFC1918 ranges."""
    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="IMDS / RFC1918 blocklist"):
        BifrostLLMSettings(base_url=f"http://{host}:8081")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scheme allowlist
# ---------------------------------------------------------------------------


def test_unsupported_scheme_rejected() -> None:
    """Pydantic ``HttpUrl`` already enforces http/https. Verify the
    validator's downstream check doesn't accept a different scheme.
    """
    with pytest.raises(ValueError):
        BifrostLLMSettings(base_url="ftp://127.0.0.1:8471")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Operator-identity logging is opt-IN (PII-safe default)
# ---------------------------------------------------------------------------


def test_allow_remote_default_does_not_log_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The non-loopback opt-in log line records ONLY the flag flip by default.

    ``BIFROST_LOG_OPERATOR_IDENTITY`` is opt-IN — its default is OFF
    (the env var absent or =0). On a shared host, a non-loopback
    flag flip should not leak ``getpass.getuser()`` or
    ``socket.gethostname()`` into the audit log. Background security
    review flagged the prior opt-out default as
    "sensitive-to-observability"; the fix flips to opt-in.
    """
    import structlog

    from oneiric.adapters.llm.bifrost import logger as bifrost_logger  # noqa: PLC0415

    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    monkeypatch.delenv("BIFROST_LOG_OPERATOR_IDENTITY", raising=False)

    with structlog.testing.capture_logs() as captured:
        BifrostLLMSettings(
            base_url="http://gateway.example.com:8471"  # type: ignore[arg-type]
        )

    bifrost_logs = [
        entry
        for entry in captured
        if entry.get("event") == "bifrost_allow_remote_opt_in"
    ]
    assert len(bifrost_logs) == 1
    # operator + hostname must NOT be present by default
    assert "operator" not in bifrost_logs[0]
    assert "hostname" not in bifrost_logs[0]
    # the structural signal (the flag flip) IS present
    assert bifrost_logs[0]["allow_remote_opt_in"] is True


def test_allow_remote_opt_in_to_log_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BIFROST_LOG_OPERATOR_IDENTITY=1`` opts IN to recording
    ``getpass.getuser()`` and ``socket.gethostname()``.
    """
    import structlog

    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    monkeypatch.setenv("BIFROST_LOG_OPERATOR_IDENTITY", "1")

    with structlog.testing.capture_logs() as captured:
        BifrostLLMSettings(
            base_url="http://gateway.example.com:8471"  # type: ignore[arg-type]
        )

    bifrost_logs = [
        entry
        for entry in captured
        if entry.get("event") == "bifrost_allow_remote_opt_in"
    ]
    assert len(bifrost_logs) == 1
    assert "operator" in bifrost_logs[0]
    assert "hostname" in bifrost_logs[0]


def test_allow_remote_log_identity_zero_means_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BIFROST_LOG_OPERATOR_IDENTITY=0`` explicitly opts OUT (matches
    the pre-flip behavior for operators who want a no-op).
    """
    import structlog

    monkeypatch.setenv("BIFROST_ALLOW_REMOTE", "1")
    monkeypatch.setenv("BIFROST_LOG_OPERATOR_IDENTITY", "0")

    with structlog.testing.capture_logs() as captured:
        BifrostLLMSettings(
            base_url="http://gateway.example.com:8471"  # type: ignore[arg-type]
        )

    bifrost_logs = [
        entry
        for entry in captured
        if entry.get("event") == "bifrost_allow_remote_opt_in"
    ]
    assert len(bifrost_logs) == 1
    assert "operator" not in bifrost_logs[0]
    assert "hostname" not in bifrost_logs[0]
