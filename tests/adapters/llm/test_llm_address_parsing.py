"""Regression tests for address- and URL-parsing differentials.

A security control that parses an address one way and another component
parses it another way is not a control. These tests pin the cases where
the two disagreed:

* an IPv4 address wearing an IPv6 hat (``::ffff:169.254.169.254``) is
  not a member of an IPv4 network -- the membership test is
  family-sensitive, so the mapped form has to be folded first;
* the IPv6 link-local, unique-local, and metadata ranges were missing;
* a URL's *query string* can carry a credential, and a *password* can
  contain a ``/``, both of which defeat a userinfo regex;
* a quoted label (``"api_key": "..."``) is JSON, and the assignment
  pattern did not match a quoted label.
"""

from __future__ import annotations

import ipaddress

import pytest
from pydantic import ValidationError

from oneiric.adapters.llm._security import sanitize_error, scrub_url
from oneiric.adapters.llm.config import ProviderConfig

SECRET = "topsecretvalue"


# ---------------------------------------------------------------------------
# Address parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        "https://[::ffff:169.254.169.254]/v1",  # IMDS, IPv4-mapped
        "https://[::ffff:10.0.0.5]/v1",  # RFC1918, IPv4-mapped
        "https://[::ffff:192.168.1.5]/v1",  # RFC1918, IPv4-mapped
        "https://[fe80::1]/v1",  # IPv6 link-local
        "https://[fc00::1]/v1",  # IPv6 unique local
        "https://[fd00:ec2::254]/v1",  # Oracle Cloud metadata (IMDSv6)
    ],
)
def test_an_obfuscated_metadata_address_is_rejected(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(name="minimax", base_url=base_url)


def test_an_ipv4_mapped_address_folds_onto_its_ipv4_form() -> None:
    """The membership test is family-sensitive; the fold makes it total."""
    mapped = ipaddress.ip_address("::ffff:169.254.169.254")
    assert not (mapped in ipaddress.ip_network("169.254.0.0/16")), (
        "the raw membership test is family-sensitive — that is the bug"
    )


def test_a_loopback_address_is_still_allowed() -> None:
    assert ProviderConfig(name="local", base_url="http://[::1]:8081/v1")


# ---------------------------------------------------------------------------
# URL scrubbing
# ---------------------------------------------------------------------------


def test_scrub_url_drops_a_query_string() -> None:
    """A query string can carry the credential."""
    scrubbed = scrub_url(f"https://host/v1?api_key={SECRET}")
    assert SECRET not in scrubbed


def test_scrub_url_drops_a_password_containing_a_slash() -> None:
    """``[^@/]`` stops at the slash, so the password survived."""
    scrubbed = scrub_url("https://user:pa/ss@host/v1")
    assert "pa/ss" not in scrubbed
    assert "user" not in scrubbed


def test_scrub_url_keeps_the_host_and_path() -> None:
    scrubbed = scrub_url("https://api.minimax.io/v1")
    assert scrubbed == "https://api.minimax.io/v1"


def test_scrub_url_leaves_a_placeholder_alone() -> None:
    assert scrub_url("${MINIMAX_BASE_URL}") == "${MINIMAX_BASE_URL}"


# ---------------------------------------------------------------------------
# Redaction of a quoted label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f'{{"api_key": "{SECRET}"}}',
        f"'token': '{SECRET}'",
        f'"secret" = "{SECRET}"',
        f"api_key={SECRET}",
        f"x-bf-vk={SECRET}",
    ],
)
def test_a_quoted_or_bare_label_is_redacted(text: str) -> None:
    assert SECRET not in sanitize_error(text)


def test_a_short_quoted_secret_is_redacted() -> None:
    assert "abcdefghij0123456789" not in sanitize_error(
        '"0123456789abcdef0123456789abcdef"'
    )
