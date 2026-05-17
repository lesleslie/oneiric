from __future__ import annotations

from types import SimpleNamespace

from oneiric.remote import metrics as m


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float | int, dict[str, str]]] = []

    def add(self, value, attributes=None):
        self.calls.append(("add", value, dict(attributes or {})))

    def record(self, value, attributes=None):
        self.calls.append(("record", value, dict(attributes or {})))


def test_remote_metrics_cover_all_branches(monkeypatch) -> None:
    success = _Recorder()
    registered = _Recorder()
    failure = _Recorder()
    duration = _Recorder()
    digest = _Recorder()
    monkeypatch.setattr(m, "_success_counter", success)
    monkeypatch.setattr(m, "_registered_counter", registered)
    monkeypatch.setattr(m, "_failure_counter", failure)
    monkeypatch.setattr(m, "_duration_histogram", duration)
    monkeypatch.setattr(m, "_digest_counter", digest)

    m.record_remote_success_metric(source="cdn", url="https://example.com", registered=2)
    m.record_remote_success_metric(source="", url="https://example.com", registered=0)
    m.record_remote_failure_metric(url="https://example.com", error="x" * 200)
    m.record_remote_duration_metric(url="https://example.com", source="cdn", duration_ms=12.5)
    m.record_digest_checks_metric(url="https://example.com", count=0)
    m.record_digest_checks_metric(url="https://example.com", count=3)

    assert success.calls[0][1] == 1
    assert registered.calls[0][1] == 2
    assert success.calls[1][2]["source"] == "unknown"
    assert failure.calls[0][2]["error"].endswith("...")
    assert duration.calls[0][0] == "record"
    assert digest.calls[0][1] == 3
