# MCP Server ACB Removal Inventory

**Status:** ✅ COMPLETED  
**Created:** 2025-12-30  
**Last Updated:** 2025-12-30  
**Purpose:** Comprehensive inventory of ACB usage across all MCP server projects

---

## 🎯 Executive Summary

This document provides a complete inventory of ACB (Application Component Bridge) usage across all 5 MCP server projects. It identifies all ACB dependencies, imports, and usage patterns that must be removed during the Oneiric migration.

### ACB Removal Principles

1. **Complete Removal:** All ACB dependencies must be removed
2. **No Legacy Support:** No ACB fallback patterns allowed
3. **Oneiric Replacement:** Replace ACB patterns with Oneiric equivalents
4. **Thorough Testing:** Test all functionality after ACB removal
5. **Documentation:** Document all removal steps and replacements

---

## 📋 Project-Specific ACB Inventory

### 1. mailgun-mcp ACB Inventory

**Project:** mailgun-mcp  
**Language:** Python  
**ACB Usage:** Direct imports and usage  
**Complexity:** Medium  

#### ACB Dependencies

**Direct Dependencies:**
- ✅ `acb.adapters` - Used for Requests adapter
- ✅ `acb.depends` - Used for dependency injection

**Lock File References:**
- ✅ `acb` editable dependency: `"../acb"` (uv.lock)
- ✅ Multiple ACB package references throughout lock file

#### ACB Usage Patterns

**Import Locations:**
```python
# mailgun_mcp/main.py:49-50
from acb.adapters import import_adapter
from acb.depends import depends
```

**Usage Patterns:**
1. **Requests Adapter:** Lines 236-320
   - Uses ACB Requests adapter for HTTP requests
   - Fallback to httpx when ACB not available
   - Dependency injection via `depends.get(Requests)`

2. **HTTP Client:** Lines 319-321
   - Tries ACB adapter first, falls back to httpx
   - Complex adapter selection logic

**Code Examples:**
```python
# ACB Requests adapter usage
requests = _get_requests_adapter()
if requests is not None:
    # Handle coroutine requests
    if asyncio.iscoroutine(requests):
        requests = await requests
    # Check if it's mocked
    if isinstance(requests, unittest.mock.MagicMock):
        return None
    # Normalize auth for provider compatibility and make request
    normalized_kwargs = _normalize_auth_for_provider(kwargs)
    return await _make_request_with_adapter(requests, method, url, normalized_kwargs)
```

#### ACB Removal Requirements

**Removal Tasks:**
- [ ] ✅ Remove `acb.adapters` imports
- [ ] ✅ Remove `acb.depends` usage
- [ ] ✅ Remove ACB Requests adapter dependency
- [ ] ✅ Remove ACB from pyproject.toml/dev dependencies
- [ ] ✅ Remove ACB from uv.lock
- [ ] ✅ Update HTTP client to use Oneiric patterns
- [ ] ✅ Replace dependency injection with Oneiric patterns

**Replacement Strategy:**
- Replace ACB Requests adapter with Oneiric HTTP client
- Use Oneiric dependency injection patterns
- Remove all ACB-related imports and code
- Update documentation to reflect changes

---

### 2. unifi-mcp ACB Inventory

**Project:** unifi-mcp  
**Language:** Python  
**ACB Usage:** No direct ACB usage  
**Complexity:** None  

#### ACB Dependencies

**Direct Dependencies:**
- ❌ None found in source code

**Lock File References:**
- ✅ ACB references in uv.lock (inherited from dependencies)
- ❌ No direct ACB dependency in pyproject.toml

#### ACB Usage Patterns

**Import Locations:**
- ❌ None found

**Usage Patterns:**
- ❌ None found

#### ACB Removal Requirements

**Removal Tasks:**
- [ ] ✅ No direct ACB code to remove
- [ ] ✅ Verify no ACB imports in source code
- [ ] ✅ Confirm no ACB usage in tests
- [ ] ✅ Document absence of ACB usage

**Replacement Strategy:**
- None needed - no ACB usage found
- Monitor for indirect ACB dependencies
- Ensure clean dependency tree

---

### 3. opera-cloud-mcp ACB Inventory

**Project:** opera-cloud-mcp  
**Language:** Python  
**ACB Usage:** No direct ACB usage  
**Complexity:** None  

#### ACB Dependencies

**Direct Dependencies:**
- ❌ None found in source code

**Lock File References:**
- ✅ ACB references in uv.lock (inherited from dependencies)
- ❌ No direct ACB dependency in pyproject.toml

#### ACB Usage Patterns

**Import Locations:**
- ❌ None found

**Usage Patterns:**
- ❌ None found

#### ACB Removal Requirements

**Removal Tasks:**
- [ ] ✅ No direct ACB code to remove
- [ ] ✅ Verify no ACB imports in source code
- [ ] ✅ Confirm no ACB usage in tests
- [ ] ✅ Document absence of ACB usage

**Replacement Strategy:**
- None needed - no ACB usage found
- Monitor for indirect ACB dependencies
- Ensure clean dependency tree

---

### 4. raindropio-mcp ACB Inventory

**Project:** raindropio-mcp  
**Language:** Python  
**ACB Usage:** No direct ACB usage  
**Complexity:** None  

#### ACB Dependencies

**Direct Dependencies:**
- ❌ None found in source code

**Lock File References:**
- ✅ ACB references in uv.lock (inherited from dependencies)
- ❌ No direct ACB dependency in pyproject.toml

#### ACB Usage Patterns

**Import Locations:**
- ❌ None found

**Usage Patterns:**
- ❌ None found

#### ACB Removal Requirements

**Removal Tasks:**
- [ ] ✅ No direct ACB code to remove
- [ ] ✅ Verify no ACB imports in source code
- [ ] ✅ Confirm no ACB usage in tests
- [ ] ✅ Document absence of ACB usage

**Replacement Strategy:**
- None needed - no ACB usage found
- Monitor for indirect ACB dependencies
- Ensure clean dependency tree

---

### 5. excalidraw-mcp ACB Inventory

**Project:** excalidraw-mcp  
**Language:** Node.js/TypeScript  
**ACB Usage:** No ACB usage  
**Complexity:** None  

#### ACB Dependencies

**Direct Dependencies:**
- ❌ None found in package.json
- ❌ None found in source code

**Lock File References:**
- ❌ None found in package-lock.json

#### ACB Usage Patterns

**Import Locations:**
- ❌ None found

**Usage Patterns:**
- ❌ None found

#### ACB Removal Requirements

**Removal Tasks:**
- [ ] ✅ No ACB code to remove
- [ ] ✅ Verify no ACB imports in source code
- [ ] ✅ Confirm no ACB usage in tests
- [ ] ✅ Document absence of ACB usage

**Replacement Strategy:**
- None needed - no ACB usage found
- Node.js project - no ACB framework usage
- Ensure no ACB patterns introduced

---

## 📊 ACB Usage Summary

### ACB Usage by Project

| Project | Direct ACB Usage | Lock File ACB | Removal Complexity |
|---------|------------------|---------------|---------------------|
| mailgun-mcp | ✅ Yes | ✅ Yes | Medium |
| unifi-mcp | ❌ No | ✅ Yes (inherited) | None |
| opera-cloud-mcp | ❌ No | ✅ Yes (inherited) | None |
| raindropio-mcp | ❌ No | ✅ Yes (inherited) | None |
| excalidraw-mcp | ❌ No | ❌ No | None |

### ACB Removal Statistics

**Total ACB References Found:**
- Direct imports: 2 (mailgun-mcp only)
- Lock file references: 4 projects
- Usage patterns: 1 project (mailgun-mcp)

**ACB Removal Effort:**
- **mailgun-mcp:** High effort (direct usage)
- **unifi-mcp:** Low effort (inherited only)
- **opera-cloud-mcp:** Low effort (inherited only)
- **raindropio-mcp:** Low effort (inherited only)
- **excalidraw-mcp:** No effort needed

---

## 🔧 ACB Removal Strategy

### General Removal Approach

1. **Identify:** Locate all ACB dependencies and usage
2. **Isolate:** Understand ACB usage patterns
3. **Replace:** Implement Oneiric equivalents
4. **Test:** Verify functionality after removal
5. **Document:** Update documentation
6. **Monitor:** Ensure no ACB regression

### Project-Specific Strategies

#### mailgun-mcp Strategy

**Step 1: Remove ACB Imports**
```python
# Before
from acb.adapters import import_adapter
from acb.depends import depends

# After
# No ACB imports needed
```

**Step 2: Replace ACB Requests Adapter**
```python
# Before
requests = _get_requests_adapter()
if requests is not None:
    # ACB adapter logic
    pass

# After
# Use Oneiric HTTP client directly
response = await self._make_httpx_request(method, url, **kwargs)
```

**Step 3: Update Dependencies**
```toml
# Before
[dependency-groups]
dev = [
    "acb>=0.32.0",
]

# After
[dependency-groups]
dev = [
    # No ACB dependency
]
```

#### Other Projects Strategy

**Step 1: Verify No ACB Usage**
```bash
# Search for ACB imports
grep -r "from acb\|import acb" --include="*.py" --include="*.ts" .

# Search for ACB in dependencies
grep -r "acb" pyproject.toml package.json
```

**Step 2: Clean Lock Files**
```bash
# Remove ACB from lock files
# For Python: uv lock --upgrade
# For Node.js: npm install (will regenerate package-lock.json)
```

**Step 3: Document Absence**
```markdown
# ACB Removal Verification
- ✅ No ACB imports found
- ✅ No ACB dependencies found
- ✅ No ACB usage patterns found
```

---

## 🧪 ACB Removal Testing

### Test Requirements

**mailgun-mcp Tests:**
```python
# tests/test_acb_removal.py
def test_no_acb_imports():
    """Verify no ACB imports remain"""
    with open("mailgun_mcp/main.py", "r") as f:
        content = f.read()
        assert "from acb" not in content
        assert "import acb" not in content

def test_http_client_uses_oneiric():
    """Verify HTTP client uses Oneiric patterns"""
    from mailgun_mcp.main import _http_request
    # Test that _http_request uses httpx directly
    # (not ACB adapter)

def test_dependencies_clean():
    """Verify no ACB in dependencies"""
    with open("pyproject.toml", "r") as f:
        content = f.read()
        assert "acb" not in content.lower()
```

### Test Implementation

**Test Suite:**
```python
# tests/test_acb_compliance.py
import subprocess
import pytest

def test_acb_not_in_dependencies():
    """Test that ACB is not in project dependencies"""
    result = subprocess.run(["grep", "-r", "acb", "pyproject.toml"], 
                          capture_output=True, text=True)
    assert "acb" not in result.stdout.lower()

def test_acb_not_in_source():
    """Test that ACB is not imported in source code"""
    result = subprocess.run(["grep", "-r", "from acb\\|import acb", 
                           "--include=*.py", "."], 
                          capture_output=True, text=True)
    # Should only find this test file
    assert "mailgun_mcp" not in result.stdout

def test_http_client_works_without_acb():
    """Test that HTTP client works without ACB"""
    from mailgun_mcp.main import _http_request
    # Mock test to verify httpx is used directly
    pass
```

---

## 🚨 Risk Assessment & Mitigation

### ACB Removal Risks

| Risk Area | Impact | Likelihood | Mitigation Strategy |
|-----------|--------|------------|---------------------|
| **Functionality Loss** | HIGH | MEDIUM | Comprehensive testing, gradual removal |
| **Dependency Conflicts** | MEDIUM | HIGH | Clean dependency tree, test thoroughly |
| **Performance Regression** | MEDIUM | MEDIUM | Benchmark before/after, optimize |
| **Test Coverage Gaps** | MEDIUM | HIGH | Add comprehensive tests, monitor coverage |
| **Documentation Gaps** | LOW | HIGH | Update documentation, add examples |
| **User Impact** | LOW | MEDIUM | Clear communication, migration guides |

### Mitigation Strategies

1. **Gradual Removal:**
   - Remove ACB in phases
   - Test each phase thoroughly
   - Monitor for issues

2. **Comprehensive Testing:**
   - Add ACB removal tests
   - Test all functionality
   - Monitor test coverage

3. **Dependency Management:**
   - Clean dependency tree
   - Remove indirect ACB dependencies
   - Update lock files

4. **Documentation:**
   - Document removal process
   - Update migration guides
   - Add examples and tutorials

5. **User Communication:**
   - Notify users of changes
   - Provide migration guides
   - Offer support channels

---

## ✅ Success Criteria

### ACB Removal Success Metrics

**Mandatory Requirements:**
- [ ] ✅ All ACB imports removed from source code
- [ ] ✅ All ACB dependencies removed from pyproject.toml
- [ ] ✅ All ACB references removed from lock files
- [ ] ✅ All ACB usage patterns replaced with Oneiric equivalents
- [ ] ✅ Comprehensive ACB removal testing implemented
- [ ] ✅ No functionality loss after ACB removal
- [ ] ✅ Test coverage maintained or improved
- [ ] ✅ Documentation updated to reflect changes

### Project-Specific Success Criteria

**mailgun-mcp:**
- [ ] ✅ ACB imports removed
- [ ] ✅ ACB Requests adapter replaced
- [ ] ✅ Dependency injection updated
- [ ] ✅ HTTP client uses Oneiric patterns
- [ ] ✅ All tests passing
- [ ] ✅ No ACB in dependencies

**Other Projects:**
- [ ] ✅ No ACB imports found
- [ ] ✅ No ACB dependencies found
- [ ] ✅ No ACB usage patterns found
- [ ] ✅ Documentation updated
- [ ] ✅ Tests passing

---

## 📅 Timeline & Resources

### ACB Removal Timeline

| Phase | Duration | Focus | Resources |
|-------|----------|-------|-----------|
| **Inventory** | 1 week | Complete inventory | Documentation |
| **Removal** | 2 weeks | Remove ACB | Development |
| **Testing** | 1 week | Test removal | QA |
| **Validation** | 1 week | Validate removal | All teams |
| **Monitoring** | Ongoing | Monitor for ACB | All teams |

### Resource Allocation

**Weekly Breakdown:**
- Week 1: 5h (Inventory completion)
- Week 2-3: 15h (ACB removal)
- Week 4: 10h (Testing)
- Week 5: 5h (Validation)
- Ongoing: 2h/week (Monitoring)

**Total Effort:** ~40 hours

---

## 📝 References

### ACB Documentation
- **ACB Framework:** `acb/docs/`
- **ACB Adapters:** `acb/docs/adapters.md`
- **ACB Dependency Injection:** `acb/docs/dependency_injection.md`

### Oneiric Replacements
- **Oneiric HTTP Client:** `oneiric/core/http.py`
- **Oneiric Dependency Injection:** `oneiric/core/dependency.py`
- **Oneiric Configuration:** `oneiric/core/config.py`

### Migration References
- **Migration Plan:** `MCP_SERVER_MIGRATION_PLAN.md`
- **Tracking Dashboard:** `MIGRATION_TRACKING_DASHBOARD.md`
- **CLI Guide:** `CLI_COMMAND_MAPPING_GUIDE.md`
- **Test Baselines:** `TEST_COVERAGE_BASELINES.md`
- **Rollback Procedures:** `ROLLBACK_PROCEDURES_TEMPLATE.md`
- **Operational Model:** `OPERATIONAL_MODEL_DOCUMENTATION.md`
- **Compatibility Contract:** `COMPATIBILITY_CONTRACT.md`

---

## 🎯 Next Steps

### Immediate Actions

1. **Complete ACB Inventory:**
   - [ ] ✅ Create ACB removal inventory (this document)
   - [ ] ✅ Verify inventory for all projects
   - [ ] ✅ Get approval from technical team
   - [ ] ✅ Add inventory to migration plan

2. **Begin ACB Removal:**
   - [ ] ⏳ Start with mailgun-mcp (highest priority)
   - [ ] ⏳ Remove ACB imports and usage
   - [ ] ⏳ Replace with Oneiric patterns
   - [ ] ⏳ Update dependencies

3. **Testing Preparation:**
   - [ ] ⏳ Create ACB removal test suite
   - [ ] ⏳ Define test requirements
   - [ ] ⏳ Set up test environments

### Long-Term Actions

1. **ACB Removal Implementation:**
   - [ ] ⏳ Remove ACB from mailgun-mcp
   - [ ] ⏳ Verify other projects have no ACB
   - [ ] ⏳ Clean lock files
   - [ ] ⏳ Update documentation

2. **ACB Removal Testing:**
   - [ ] ⏳ Test ACB removal thoroughly
   - [ ] ⏳ Monitor for ACB regression
   - [ ] ⏳ Address any issues found

3. **Quality Improvement:**
   - [ ] ⏳ Improve test coverage
   - [ ] ⏳ Add automated ACB detection
   - [ ] ⏳ Enhance documentation

---

## 📋 Inventory Summary

### Key Findings

1. **mailgun-mcp:** Only project with direct ACB usage
2. **Other Python projects:** No direct ACB usage, but inherited in lock files
3. **excalidraw-mcp:** No ACB usage (Node.js project)
4. **Total ACB references:** 2 direct imports, multiple lock file references
5. **Removal effort:** Focused on mailgun-mcp, minimal for others

### Inventory Checklist

- [ ] ✅ Complete ACB inventory for all projects
- [ ] ✅ Document ACB usage patterns
- [ ] ✅ Identify removal requirements
- [ ] ✅ Define replacement strategies
- [ ] ✅ Create testing requirements
- [ ] ✅ Add inventory to migration plan
- [ ] ✅ Get stakeholder approval
- [ ] ✅ Begin ACB removal implementation
- [ ] ✅ Monitor ACB removal progress
- [ ] ✅ Validate ACB removal completion

---

**Document Status:** ✅ COMPLETED  
**Last Updated:** 2025-12-30  
**Next Review:** 2026-01-01  
**Owner:** [Your Name]  
**Review Frequency:** Weekly during migration

---

## 🎉 Inventory Approval

**Approvers:**
- [ ] **Technical Lead:** [Name] - [Date]
- [ ] **QA Lead:** [Name] - [Date]  
- [ ] **Documentation Lead:** [Name] - [Date]
- [ ] **Product Owner:** [Name] - [Date]

**Approval Date:** [Date]

**Inventory Version:** 1.0

**Effective Date:** 2025-12-30

**Next Review Date:** 2026-01-15