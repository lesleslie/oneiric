from oneiric.adapters.bootstrap import builtin_adapter_metadata


def test_builtin_metadata_includes_ai_and_vector_adapters() -> None:
    """Ensure recently ported adapters register with the resolver."""
    metadata = builtin_adapter_metadata()
    available = {(item.category, item.provider) for item in metadata}

    expected = {
        ("database", "duckdb"),
        ("vector", "pinecone"),
        ("vector", "qdrant"),
        ("nosql", "mongodb"),
        ("nosql", "dynamodb"),
        ("nosql", "firestore"),
        ("embedding", "openai"),
        ("embedding", "sentence_transformers"),
        ("embedding", "onnx"),
        ("llm", "openai"),
        ("llm", "anthropic"),
    }

    missing = expected - available
    assert not missing, f"Missing adapter metadata entries: {missing}"
