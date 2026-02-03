from __future__ import annotations


def normalize_payload(payload: dict | None) -> dict:
    return payload or {}
