# oneiric/tests/plan_index/test_render.py
from oneiric.plan_index.entry import Entry
from oneiric.plan_index.render import render_index

def test_render_includes_kind_column():
    """The Kind column is part of the table header and rows (Decision #11)."""
    entries = {
        "docs/plans/": [
            Entry(rel="docs/plans/a.md", store="docs/plans/", date="2026-10-19",
                  status="active", role="implementation", kind="plan", topic="t", title="A"),
        ]
    }
    rendered = render_index(entries_by_store=entries, generated_at="2026-10-19")
    assert "| Kind |" in rendered
    assert "| `plan` |" in rendered

def test_render_distribution_footer_present():
    """Distribution footer is part of render_index output (per Decision #9)."""
    entries = {"docs/plans/": [
        Entry(rel="docs/plans/a.md", store="docs/plans/", date="2026-10-19",
              status="active", role="implementation", kind="plan", topic="t", title="A"),
    ]}
    rendered = render_index(entries_by_store=entries, generated_at="2026-10-19")
    assert "Lifecycle × Role Distribution" in rendered

def test_render_sorted_by_date_desc_then_path():
    e1 = Entry(rel="docs/plans/aaa.md", store="docs/plans/", date="2026-10-01", status="active", role="implementation", kind="plan", topic="t", title="Aaa")
    e2 = Entry(rel="docs/plans/zzz.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="t", title="Zzz")
    e3 = Entry(rel="docs/plans/mmm.md", store="docs/plans/", date="2026-10-19", status="active", role="implementation", kind="plan", topic="t", title="Mmm")
    rendered = render_index(entries_by_store={"docs/plans/": [e1, e2, e3]}, generated_at="2026-10-19")
    # Expected order: e2 (date desc), e3 (same date, path asc), e1
    assert rendered.index("Zzz") < rendered.index("Mmm") < rendered.index("Aaa")
