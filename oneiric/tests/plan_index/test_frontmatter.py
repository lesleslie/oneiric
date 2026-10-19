import yaml
from oneiric.plan_index.frontmatter import extract_frontmatter


def test_unclosed_yaml_block_returns_none():
    text = "---\nstatus: active\nrole: implementation\n"
    assert extract_frontmatter(text, yaml) is None


def test_single_dash_not_a_boundary():
    text = "--- key: value\nstatus: active\n"
    assert extract_frontmatter(text, yaml) is None


def test_valid_yaml_missing_required_key():
    text = "---\nstatus: active\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed is not None
    assert "role" not in parsed  # missing required key — caller validates


def test_invalid_enum_value_passes_parser():
    text = "---\nstatus: foo\nrole: bar\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed == {"status": "foo", "role": "bar"}


def test_valid_yaml_returns_dict():
    text = "---\nstatus: active\nrole: implementation\nkind: plan\n---\n# Title\n"
    parsed = extract_frontmatter(text, yaml)
    assert parsed == {"status": "active", "role": "implementation", "kind": "plan"}
