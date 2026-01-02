# mailgun-mcp Migration Baseline Audit

**Project:** mailgun-mcp  
**Date:** 2025-12-30  
**Version:** 0.1.3  
**Status:** Pre-migration baseline  

## Executive Summary

This document establishes the baseline state of mailgun-mcp before Oneiric migration. It captures current dependencies, CLI patterns, test coverage, and ACB usage to ensure a smooth transition.

## Current State Analysis

### Project Structure

```
mailgun-mcp/
├── mailgun_mcp/
│   ├── __init__.py
│   ├── main.py          # Main FastMCP server implementation
│   └── utils/
│       └── process_utils.py
├── tests/
│   ├── __init__.py
│   └── test_main.py     # Comprehensive test suite
├── pyproject.toml       # Project configuration
├── uv.lock             # Dependency lock file
└── coverage.json       # Test coverage data
```

### Current Dependencies

**Production Dependencies:**
- `fastmcp` - FastMCP framework (to be replaced with Oneiric)
- `mcp-common` - Common MCP utilities
- `acb` - ACB framework (to be removed)

**Development Dependencies:**
- `crackerjack>=0.39.1`
- `excalidraw-mcp>=0.34.0`
- `session-buddy>=0.4.0`

### Current CLI Patterns

**Current Entry Point:**
- No direct CLI entry point found
- Currently runs as: `python -m mailgun_mcp` (but no __main__.py)
- Uses FastMCP's built-in server startup

**Current Commands:**
- No explicit CLI commands defined
- Server starts via FastMCP's `mcp.http_app`
- Configuration via environment variables

### ACB Usage Inventory

**ACB Dependencies Found:**
1. **Imports:**
   - `from acb.adapters import import_adapter` (line 49)
   - `from acb.depends import depends` (line 50)

2. **Usage Patterns:**
   - ACB Requests adapter for HTTP requests (lines 236-320)
   - Dependency injection via `depends.get(Requests)` (line 240)
   - Fallback to httpx when ACB not available

3. **Lock File References:**
   - `acb` editable dependency: `"../acb"` (uv.lock lines 12, 2535)
   - Multiple ACB package references throughout lock file

### Test Coverage Baseline

**Current Coverage:** 46%  
**Test Files:**
- `tests/test_main.py` - 645 lines of comprehensive tests
- Tests cover all major Mailgun API endpoints
- Mock-based testing for HTTP requests

**Test Categories:**
- ✅ Email sending (send_message)
- ✅ Domain management (get_domains, create_domain, etc.)
- ✅ Event tracking (get_events, get_stats)
- ✅ Suppression management (bounces, complaints, unsubscribes)
- ✅ Route management (get_routes, create_route, etc.)
- ✅ Template management (get_templates, create_template, etc.)
- ✅ Webhook management (get_webhooks, create_webhook, etc.)

### Configuration Patterns

**Current Configuration:**
- Environment variables: `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`
- FastMCP configuration in `pyproject.toml`:
  ```toml
  [tool.mailgun-mcp]
  http_port = 3039
  http_host = "127.0.0.1"
  enable_http_transport = true
  ```

### Runtime Behavior

**Current Startup:**
1. Validates Mailgun API key at startup
2. Initializes FastMCP server with 31 tools
3. Sets up rate limiting middleware
4. Uses ACB Requests adapter for HTTP (with httpx fallback)

**Current Health/Status:**
- No explicit health endpoints
- No runtime snapshots
- No PID file management
- No standardized status reporting

## Migration Requirements

### CLI Migration Requirements

**New Oneiric CLI Commands Needed:**
- `mailgun-mcp start` - Start the MCP server
- `mailgun-mcp stop` - Stop the running server  
- `mailgun-mcp restart` - Restart the server
- `mailgun-mcp status` - Show server status
- `mailgun-mcp health` - Health check endpoint
- `mailgun-mcp health --probe` - Live health probe

### Configuration Migration Requirements

**New Configuration Pattern:**
```python
from oneiric.core.config import OneiricMCPConfig
from pydantic import Field

class MailgunConfig(OneiricMCPConfig):
    http_port: int = Field(default=3039, env="MAILGUN_HTTP_PORT")
    http_host: str = Field(default="127.0.0.1", env="MAILGUN_HTTP_HOST")
    api_key: str = Field(..., env="MAILGUN_API_KEY")
    domain: str = Field(..., env="MAILGUN_DOMAIN")
    enable_http_transport: bool = Field(default=True, env="MAILGUN_ENABLE_HTTP")

    class Config:
        env_prefix = "MAILGUN_"
```

### ACB Removal Requirements

**ACB Components to Remove:**
1. ✅ Remove `acb.adapters` imports
2. ✅ Remove `acb.depends` usage
3. ✅ Remove ACB Requests adapter dependency
4. ✅ Remove ACB from pyproject.toml/dev dependencies
5. ✅ Remove ACB from uv.lock
6. ✅ Update HTTP client to use Oneiric patterns

### Runtime Cache Requirements

**New Runtime Cache Files:**
- `.oneiric_cache/server.pid` - PID file
- `.oneiric_cache/runtime_health.json` - Health snapshot
- `.oneiric_cache/runtime_telemetry.json` - Telemetry data

### Health Schema Requirements

**New Health Schema (mcp-common.health):**
```python
from mcp_common.health import HealthStatus, ComponentHealth, HealthCheckResponse

class MailgunHealthCheck:
    def health_check(self) -> HealthCheckResponse:
        return HealthCheckResponse(
            status=HealthStatus.HEALTHY,
            components=[
                ComponentHealth(
                    name="mailgun_api",
                    status=HealthStatus.HEALTHY,
                    message="Mailgun API connection healthy",
                    latency_ms=120
                ),
                ComponentHealth(
                    name="http_client",
                    status=HealthStatus.HEALTHY,
                    message="HTTP client operational"
                )
            ]
        )
```

## Migration Checklist

### Phase 1: Foundation (Completed ✅)
- [x] Create baseline audit document
- [x] Create pre-migration rollback tag (`v1.0.0-pre-migration`)
- [x] Document current CLI patterns
- [x] Establish test coverage baseline (46%)
- [x] Complete ACB removal inventory

### Phase 2: Integration Layer
- [ ] Develop Oneiric CLI factory integration
- [ ] Create MailgunConfig class
- [ ] Implement lifecycle hooks (start, stop, health)
- [ ] Add runtime snapshot management
- [ ] Update HTTP client to Oneiric patterns

### Phase 3: Migration Implementation
- [ ] Replace FastMCP with OneiricMCPServer
- [ ] Integrate Oneiric CLI factory
- [ ] Remove all ACB dependencies
- [ ] Add health check endpoints
- [ ] Implement runtime cache management
- [ ] Update configuration patterns

### Phase 4: Testing & Validation
- [ ] Maintain ≥46% test coverage
- [ ] Add Oneiric-specific tests
- [ ] Validate CLI commands
- [ ] Test runtime snapshots
- [ ] Verify health schema compliance

### Phase 5: Rollout
- [ ] Create user migration guide
- [ ] Update documentation
- [ ] Test rollback procedures
- [ ] Final ACB verification

## Rollback Procedures

### Rollback to Pre-Migration State
```bash
# 1. Checkout pre-migration tag
git checkout v1.0.0-pre-migration

# 2. Reinstall dependencies
pip install -e .

# 3. Verify functionality
python -c "from mailgun_mcp.main import mcp; print('Mailgun MCP loaded successfully')"

# 4. Run tests
pytest tests/test_main.py -v
```

## Success Criteria

### Technical Success Metrics
- ✅ All ACB dependencies removed
- ✅ Oneiric CLI factory implemented
- ✅ Standardized lifecycle management
- ✅ Runtime cache files created
- ✅ Health schema compliance
- ✅ Test coverage ≥46% maintained

### User Success Metrics
- ✅ Clear migration guide provided
- ✅ CLI command mapping documented
- ✅ Configuration migration examples
- ✅ Rollback procedures tested

## Next Steps

1. **Immediate:** Begin Phase 2 - Integration Layer
2. **Priority:** Develop Oneiric CLI factory for mailgun-mcp
3. **Focus:** Remove ACB dependencies and replace with Oneiric patterns
4. **Testing:** Ensure all existing functionality preserved
5. **Documentation:** Create user migration guide

## References

- **Oneiric CLI Patterns:** `oneiric/core/cli.py`
- **Oneiric Configuration:** `oneiric/core/config.py`
- **Health Schema:** `mcp_common.health`
- **Migration Plan:** `MCP_SERVER_MIGRATION_PLAN.md`

---

**Audit Completed:** 2025-12-30  
**Audit Status:** BASELINE ESTABLISHED  
**Next Review:** Phase 2 Integration Layer