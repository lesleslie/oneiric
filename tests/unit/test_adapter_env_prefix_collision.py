"""T2.8: cross-prefix collision + per-base env-var loading tests.

Asserts that:
- LLM_API_KEY flows only into LLMBaseSettings-derived adapters, never into
  Embedding/Vector/NoSQL adapter settings or MahavishnuSettings.
- EMBEDDING_API_KEY flows only into EmbeddingBaseSettings-derived adapters.
- VECTOR_URL flows only into VectorBaseSettings-derived adapters.
- ONEIRIC_OBSERVABILITY__CONNECTION_STRING flows only into the nested
  OTelStorageSettings via OneiricSettings.observability.
- LLM/EMBEDDING/VECTOR prefixes never bleed into each other.
"""

from __future__ import annotations

import importlib
import os
import sys


def _clean_env() -> None:
    """Strip test env vars between scenarios."""
    for k in list(os.environ):
        if k in (
            "LLM_API_KEY",
            "EMBEDDING_API_KEY",
            "VECTOR_URL",
            "ONEIRIC_OBSERVABILITY__CONNECTION_STRING",
            "ONEIRIC_API_KEY",
            "VECTOR_DSN",
            "NOSQL_URI",
        ):
            del os.environ[k]


def _reload_oneiric_config() -> None:
    """Reload oneiric.core.config to re-trigger env-var resolution."""
    sys.modules.pop("oneiric.core.config", None)


# ---------------------------------------------------------------------------
# Per-base env-var loading
# ---------------------------------------------------------------------------


def test_llm_api_key_flows_to_openai_llm_settings() -> None:
    _clean_env()
    os.environ["LLM_API_KEY"] = "sk-llm-test"
    from oneiric.adapters.llm.openai import OpenAILLMSettings

    s = OpenAILLMSettings()
    assert s.api_key is not None and s.api_key.get_secret_value() == "sk-llm-test"


def test_llm_api_key_flows_to_anthropic_llm_settings() -> None:
    _clean_env()
    os.environ["LLM_API_KEY"] = "sk-anthropic-test"
    from oneiric.adapters.llm.anthropic import AnthropicLLMSettings

    s = AnthropicLLMSettings()
    assert s.api_key is not None and s.api_key.get_secret_value() == "sk-anthropic-test"


def test_embedding_api_key_flows_to_openai_embedding_settings() -> None:
    _clean_env()
    os.environ["EMBEDDING_API_KEY"] = "sk-emb-test"
    from oneiric.adapters.embedding.openai import OpenAIEmbeddingSettings

    s = OpenAIEmbeddingSettings()
    assert s.api_key is not None and s.api_key.get_secret_value() == "sk-emb-test"


def test_vector_url_flows_to_qdrant_settings() -> None:
    _clean_env()
    os.environ["VECTOR_URL"] = "http://qdrant-test"
    from oneiric.adapters.vector.qdrant import QdrantSettings

    s = QdrantSettings()
    assert s.url == "http://qdrant-test"


def test_vector_dsn_flows_to_pgvector_settings() -> None:
    _clean_env()
    os.environ["VECTOR_DSN"] = "postgresql://x-dsn"
    from oneiric.adapters.vector.pgvector import PgvectorSettings

    s = PgvectorSettings()
    assert s.dsn == "postgresql://x-dsn"


def test_nosql_uri_flows_to_mongodb_settings() -> None:
    _clean_env()
    os.environ["NOSQL_URI"] = "mongodb://x-nosql"
    from oneiric.adapters.nosql.mongodb import MongoDBSettings

    s = MongoDBSettings()
    assert s.uri == "mongodb://x-nosql"


def test_oneiric_observability_connection_string_flows_to_nested_settings() -> None:
    _clean_env()
    os.environ["ONEIRIC_OBSERVABILITY__CONNECTION_STRING"] = "postgresql://x-test"
    _reload_oneiric_config()
    from oneiric.core.config import load_settings

    s = load_settings(project_name="oneiric")
    assert s.observability.connection_string == "postgresql://x-test"


# ---------------------------------------------------------------------------
# Cross-prefix isolation
# ---------------------------------------------------------------------------


def test_llm_env_does_not_bleed_into_embedding_settings() -> None:
    _clean_env()
    os.environ["LLM_API_KEY"] = "sk-llm-only"
    from oneiric.adapters.embedding.openai import OpenAIEmbeddingSettings

    emb = OpenAIEmbeddingSettings()
    assert emb.api_key is None or emb.api_key.get_secret_value() != "sk-llm-only"


def test_embedding_env_does_not_bleed_into_llm_settings() -> None:
    _clean_env()
    os.environ["EMBEDDING_API_KEY"] = "sk-emb-only"
    from oneiric.adapters.llm.openai import OpenAILLMSettings

    llm = OpenAILLMSettings()
    assert llm.api_key is None or llm.api_key.get_secret_value() != "sk-emb-only"


def test_vector_env_does_not_bleed_into_llm_settings() -> None:
    _clean_env()
    os.environ["VECTOR_URL"] = "http://vector-only"
    from oneiric.adapters.llm.openai import OpenAILLMSettings

    llm = OpenAILLMSettings()
    assert llm.api_key is None


def test_llm_env_does_not_bleed_into_vector_settings() -> None:
    _clean_env()
    os.environ["LLM_API_KEY"] = "sk-llm-only"
    from oneiric.adapters.vector.qdrant import QdrantSettings

    qdr = QdrantSettings()
    # Qdrant default url is "http://localhost: 6333"; LLM_API_KEY must not
    # change it.
    assert qdr.url != "sk-llm-only"


# ---------------------------------------------------------------------------
# Cross-project isolation: LLM_API_KEY must not feed MahavishnuSettings.api_key
# ---------------------------------------------------------------------------


def test_llm_env_does_not_bleed_into_mahavishnu_settings() -> None:
    _clean_env()
    os.environ["ONEIRIC_API_KEY"] = "sk-mahavishnu"
    os.environ["LLM_API_KEY"] = "sk-llm-bleed"
    _reload_oneiric_config()
    from oneiric.core.config import load_settings

    ms = load_settings(project_name="oneiric")
    if hasattr(ms, "api_key") and ms.api_key is not None:
        # Mahavishnu api_key should equal the Mahavishnu-prefixed value,
        # NOT the LLM-prefixed value.
        assert ms.api_key.get_secret_value() == "sk-mahavishnu"