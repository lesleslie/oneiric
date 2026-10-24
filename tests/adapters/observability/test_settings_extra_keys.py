"""``observability`` is a key consumers already use for another meaning.

Oneiric's ``OTelStorageSettings`` models where to STORE OTLP telemetry
(pgvector connection string, embedding model, vector dimension).
Mahavishnu's ``ObservabilityConfig`` models whether to EXPORT metrics and
traces. Both live under the top-level key ``observability``, so the two
collide in any layered YAML a consumer writes.

With pydantic-settings' default ``extra="forbid"``, one unknown nested key
raised ValidationError inside ``OneiricSettings`` construction.
``load_settings`` propagated it, and the consumer's entire layered config was
discarded in favour of defaults -- taking unrelated settings
(``adapters.hatchet_enabled``, ``qc.enabled``) down with no symptom beyond a
traceback nobody reads at 3am.

These tests pin the blast radius: an unrecognised key under ``observability``
must cost exactly that key, and nothing else.
"""

from __future__ import annotations

from typing import Any

import pytest
from oneiric.adapters.observability.settings import OTelStorageSettings
from oneiric.core.config import OneiricSettings


def test_an_unknown_observability_key_is_tolerated() -> None:
    """The collision itself must not raise."""
    s = OTelStorageSettings(metrics_enabled=True)
    # The recognised keys keep their declared values.
    assert s.cache_size == 1000
    assert s.similarity_threshold == pytest.approx(0.85)


def test_recognised_keys_still_type_check() -> None:
    """Permissive must not mean unvalidated."""
    s = OTelStorageSettings(cache_size=500)
    assert s.cache_size == 500

    with pytest.raises(ValueError):
        # ge=100 on cache_size is a real constraint, not a typo guard.
        OTelStorageSettings(cache_size=1)


def test_an_unknown_nested_key_does_not_discard_the_layer() -> None:
    """The whole-layer regression, at the settings root.

    This is the assertion that would have caught the original bug: a single
    bad key must not silently revert every OTHER setting to its default.

    ``qc`` is not a declared field on OneiricSettings, so under
    ``extra="allow"`` it rides through ``__pydantic_extra__`` as a plain dict.
    """
    settings = OneiricSettings(
        observability={"metrics_enabled": True},
        qc={"enabled": True, "min_score": 42},
    )

    qc = (settings.model_extra or {}).get("qc")
    assert isinstance(qc, dict), f"qc did not survive: {qc!r}"
    assert qc.get("enabled") is True, (
        "an unknown key under observability took unrelated settings down with it"
    )
    assert qc.get("min_score") == 42


def test_top_level_permissiveness_was_already_the_intent() -> None:
    """Documents why the nested model was the outlier.

    ``OneiricSettings`` has been ``extra="allow"`` at the top level; a strict
    child under a permissive parent is what made the blast radius total rather
    than local.
    """
    assert OneiricSettings.model_config.get("extra") == "allow"
    assert OTelStorageSettings.model_config.get("extra") == "allow"


def test_unknown_keys_are_readable_rather_than_discarded() -> None:
    """They are preserved, so a consumer can still see what it asked for."""
    s = OTelStorageSettings(metrics_enabled=True)
    extras: dict[str, Any] = dict(s.model_extra or {})
    assert extras.get("metrics_enabled") is True
