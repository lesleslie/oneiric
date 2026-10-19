# oneiric/tests/plan_index/test_entry.py
from oneiric.plan_index.entry import Entry


def test_entry_has_eight_fields():
    e = Entry(rel="docs/plans/foo.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="test", title="Foo")
    assert e.rel == "docs/plans/foo.md"
    assert e.store == "docs/plans/"
    assert e.date == "2026-10-19"
    assert e.status == "active"
    assert e.role == "implementation"
    assert e.kind == "plan"
    assert e.topic == "test"
    assert e.title == "Foo"


def test_entry_is_frozen():
    e = Entry(rel="x", store="y", date="z", status="a", role="b", kind="c", topic="d", title="e")
    import pytest
    with pytest.raises(Exception):
        e.rel = "y"  # type: ignore[misc]
