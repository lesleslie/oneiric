from __future__ import annotations

from unittest.mock import patch

import pytest

from oneiric.core.lifecycle import LifecycleError, resolve_factory


def test_resolve_factory_wraps_import_error() -> None:
    with patch(
        "oneiric.core.lifecycle.validate_factory_string",
        return_value=(True, None),
    ):
        with patch(
            "oneiric.core.lifecycle.importlib.import_module",
            side_effect=ImportError("missing"),
        ):
            with pytest.raises(LifecycleError, match="Failed to load factory"):
                resolve_factory("pkg.module:factory")
