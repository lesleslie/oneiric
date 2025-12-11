# Adapter Obsolescence Analysis

**Purpose:** Identify adapters that are no longer needed in Oneiric's modern architecture.

**Date:** 2025-11-26

______________________________________________________________________

## Executive Summary

**Obsolete Adapters:** 1 (models adapter)
**Rearchitecture Needed:** 2 (admin, app adapters)
**Reason:** Modern Pydantic-first strategy eliminates need for model abstraction layer; admin/app are framework features, not adapters.

______________________________________________________________________

## 1. Models Adapter - OBSOLETE ❌

### Current State (ACB)

**Purpose:** Unified registry/factory for different model libraries.

**Implementation:**

```python
# ACB models adapter provides:
models.sql.User  # SQLModel/SQLAlchemy models
models.nosql.Session  # Redis-OM models

# Supported libraries:
-SQLModel(SQL)
-SQLAlchemy(SQL)
-Pydantic(validation)
-Redis - OM(Redis)
-msgspec(serialization)
-attrs(dataclasses)
```

**Features:**

- Abstraction over 6 different model libraries
- Unified `.sql` and `.nosql` accessors
- Model adapter wrappers for serialization/deserialization
- Type introspection helpers

### Why It's Obsolete

**1. Pydantic V2 Unifies Everything**

Modern ecosystem has converged on Pydantic V2 as the standard:

- ✅ **SQLModel** = Pydantic + SQLAlchemy (SQL databases)
- ✅ **Redis-OM** = Pydantic + Redis (NoSQL)
- ✅ **ODMantic** = Pydantic + MongoDB (NoSQL)
- ✅ **Beanie** = Pydantic + Motor (MongoDB, alternative to ODMantic)

**All use Pydantic V2 models** - no abstraction layer needed.

**2. Direct Library Usage is Simpler**

**Old Way (ACB models adapter):**

```python
# Need adapter to access models
models = await get_adapter("models")
user = models.sql.User(name="Alice")  # Extra indirection
```

**New Way (Direct Pydantic):**

```python
# Direct import, no adapter
from myapp.models import User

user = User(name="Alice")  # Clean, simple
```

**3. Type Safety Suffers**

Models adapter uses `__getattr__` for `.sql.ModelName` access:

- ❌ No IDE autocomplete
- ❌ No mypy/pyright validation
- ❌ Runtime errors instead of compile-time errors

Direct imports preserve full type information:

- ✅ IDE autocomplete
- ✅ Full type checking
- ✅ Compile-time error detection

**4. Modern Tooling Makes It Redundant**

Tools that replace models adapter functionality:

- **SQLModel** - Already provides SQL + Pydantic unification
- **Alembic** - Database migrations (better than hand-rolled)
- **Pydantic** - Serialization/validation (built-in)
- **mypy/pyright** - Type introspection (IDE integration)

### Recommendation: DO NOT PORT ❌

**Instead:**

1. Use **SQLModel** directly for SQL models
1. Use **Redis-OM** directly for Redis models
1. Use **ODMantic** directly for MongoDB models
1. Document best practices in `docs/MODELS_GUIDE.md`

**Migration Path:**

```python
# Before (ACB with models adapter)
models = await get_adapter("models")
user = models.sql.User(name="Alice")

# After (Oneiric without models adapter)
from myapp.models import User

user = User(name="Alice")

# Database adapter handles connections
db = await get_adapter("database")
async with db.session() as session:
    session.add(user)
    await session.commit()
```

______________________________________________________________________

## 2. Admin Adapter - REARCHITECTURE NEEDED ⚠️

### Current State (FastBlocks)

**Purpose:** SQLAdmin integration for database admin panels.

**Implementation:**

```python
class Admin(AdminBase):
    def __init__(self, templates, app=None, **kwargs):
        self._sqladmin = SqlAdminBase(app=app, **kwargs)
        self.templates = templates.admin

    async def init(self):
        # Auto-discover and register models
        models = await depends.get("models")
        admin_models = models.get_admin_models()
        for model in admin_models:
            self._sqladmin.add_view(model)
```

**Features:**

- Wraps SQLAdmin library
- Auto-model discovery
- Template integration
- Lifespan management

### Why It's Not Really an Adapter

**Problem:** Admin is a **framework feature**, not an infrastructure adapter.

**Evidence:**

1. **Tightly coupled to web framework** - Requires Starlette/FastAPI app instance
1. **Application-level concern** - Admin panels are UI features, not data access
1. **Depends on models** - Requires models to exist (circular with models adapter)
1. **Template-heavy** - UI rendering is app responsibility

**Comparison to Real Adapters:**

| Aspect | Real Adapter (e.g., Database) | Admin "Adapter" |
|--------|-------------------------------|-----------------|
| **Purpose** | Infrastructure access (DB, cache, queue) | UI feature (admin panel) |
| **Reusability** | Used across multiple apps | App-specific |
| **Dependencies** | External service (Postgres, Redis) | Internal (models, templates) |
| **Lifecycle** | Connection management | App startup/shutdown |
| **Swap-ability** | Can swap Postgres → MySQL | Can't swap admin panel mid-request |

### Recommended Rearchitecture

**Option 1: Move to Services Domain** ✅ (Recommended)

Admin is a **service** (not adapter):

```python
# oneiric/services/admin/sqladmin.py
from oneiric.services.base import ServiceBase


class SQLAdminService(ServiceBase):
    metadata = ServiceMetadata(
        service_id="admin",
        provider="sqladmin",
        factory="oneiric.services.admin.sqladmin:SQLAdminService",
    )

    def __init__(self, app: Starlette, settings: AdminSettings):
        from sqladmin import Admin

        self._admin = Admin(app=app, **settings.model_dump())

    async def register_models(self, models: list[type]) -> None:
        for model in models:
            self._admin.add_view(model)


# Usage
admin = await get_service("admin")
await admin.register_models([User, Post, Comment])
```

**Option 2: Move to Application Layer** (Alternative)

If admin is FastBlocks-specific:

```python
# fastblocks/admin.py (not in adapters/)
class FastBlocksAdmin:
    """Admin panel integration for FastBlocks applications."""

    def __init__(self, app: FastBlocks):
        from sqladmin import Admin

        self.admin = Admin(app=app)

    def register_models(self, models: list[type]) -> None:
        for model in models:
            self.admin.add_view(model)


# In FastBlocks app initialization
app = FastBlocks()
admin = FastBlocksAdmin(app)
admin.register_models([User, Post])
```

**Rationale for Services Domain:**

- ✅ Admin provides functionality (service), not infrastructure (adapter)
- ✅ Can have multiple admin providers (SQLAdmin, Flask-Admin, Django Admin)
- ✅ Follows Oneiric's multi-domain pattern
- ✅ Keeps adapter domain clean (infrastructure only)

______________________________________________________________________

## 3. App Adapter - REARCHITECTURE NEEDED ⚠️

### Current State (FastBlocks)

**Purpose:** Main application instance with lifecycle management.

**Implementation:**

```python
class AppSettings(AppBaseSettings):
    name: str = "fastblocks"
    style: str = "bulma"
    theme: str = "light"
    url: str = "http://localhost:8000"
    token_id: str = "_fb_"


class FastBlocksApp(FastBlocks):
    def __init__(self, **kwargs):
        super().__init__(lifespan=self.lifespan, **kwargs)

    async def init(self):
        pass  # Initialize adapters, services

    @asynccontextmanager
    async def lifespan(self, app):
        # Startup sequence
        await self.init()
        yield
        # Shutdown sequence
        await self.cleanup()
```

**Features:**

- App-wide settings (name, style, theme, URL)
- Lifespan management (startup/shutdown)
- Adapter initialization orchestration
- Debug/logging configuration

### Why It's Not Really an Adapter

**Problem:** App is the **application framework itself**, not a swappable component.

**Evidence:**

1. **Singleton by nature** - Only one app instance per process
1. **Framework-level** - This IS the framework, not an adapter TO a framework
1. **Not swappable** - Can't hot-swap the entire application
1. **Orchestrates adapters** - Consumers of adapters, not adapters themselves

**Conceptual Issue:**

- Adapters are **consumed by** the application
- App is **the consumer** of adapters
- Can't have an adapter that contains itself (circular)

### Recommended Rearchitecture

**Option 1: Move to Application Core** ✅ (Recommended)

App configuration is application-level, not adapter-level:

```python
# fastblocks/application.py (not in adapters/)
from starlette.applications import Starlette
from oneiric.runtime import RuntimeOrchestrator


class FastBlocksApp(Starlette):
    """FastBlocks application with Oneiric integration."""

    def __init__(
        self,
        name: str = "fastblocks",
        style: str = "bulma",
        theme: str = "light",
        **kwargs,
    ):
        super().__init__(lifespan=self.lifespan, **kwargs)
        self.name = name
        self.style = style
        self.theme = theme
        self.orchestrator = RuntimeOrchestrator()

    @asynccontextmanager
    async def lifespan(self, app):
        # Startup: Initialize Oneiric runtime
        await self.orchestrator.start()

        # Initialize adapters
        db = await get_adapter("database")
        cache = await get_adapter("cache")

        yield

        # Shutdown: Cleanup
        await self.orchestrator.stop()


# Usage
app = FastBlocksApp(name="myapp", style="bulma")
```

**Option 2: Configuration Object** (Alternative)

If app settings need to be swappable:

```python
# fastblocks/config.py
from pydantic import BaseModel


class AppConfig(BaseModel):
    """Application configuration (not an adapter)."""

    name: str = "fastblocks"
    style: str = "bulma"
    theme: str = "light"
    url: str = "http://localhost:8000"


# Usage
config = AppConfig(name="myapp", style="webawesome")
app = FastBlocks(config=config)
```

**Rationale:**

- ✅ App is framework core, not swappable infrastructure
- ✅ Configuration belongs in settings, not adapters
- ✅ Lifespan management is framework responsibility
- ✅ Keeps adapter domain clean (infrastructure only)

______________________________________________________________________

## Summary Table

| Adapter | ACB/FastBlocks | Oneiric Recommendation | Reason |
|---------|----------------|------------------------|--------|
| **models** | ✅ Exists (ACB) | ❌ **OBSOLETE** | Pydantic V2 + SQLModel/Redis-OM/ODMantic replace it |
| **admin** | ✅ Exists (FastBlocks) | ⚠️ **Move to Services** | UI feature, not infrastructure adapter |
| **app** | ✅ Exists (FastBlocks) | ⚠️ **Move to App Core** | Framework itself, not swappable component |

______________________________________________________________________

## Other Potentially Obsolete Adapters

### From ACB Inspection

**Check these when porting from ACB:**

1. **Logger Adapter** (`acb/adapters/logger/`) - LIKELY OBSOLETE

   - **Reason:** Oneiric uses structlog directly (`core/logging.py`)
   - **Alternative:** Configure structlog in app settings
   - **When to keep:** If need runtime-swappable logging backends

1. **Config Adapter** (if exists) - LIKELY OBSOLETE

   - **Reason:** Pydantic settings handle config
   - **Alternative:** Use Pydantic BaseSettings + YAML/TOML

1. **DI/Dependency Injection Adapter** (if exists) - LIKELY OBSOLETE

   - **Reason:** Oneiric's resolver IS the DI system
   - **Alternative:** Use `get_adapter()`, `get_service()`

______________________________________________________________________

## Migration Guide

### For ACB Projects Using Models Adapter

**Before (ACB):**

```python
# models.py
class User:
    name: str
    email: str


# application.py
models = await get_adapter("models")
user = models.sql.User(name="Alice", email="alice@example.com")
```

**After (Oneiric):**

```python
# models.py
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str


# application.py
from myapp.models import User

db = await get_adapter("database")
user = User(name="Alice", email="alice@example.com")

async with db.session() as session:
    session.add(user)
    await session.commit()
```

### For FastBlocks Projects Using Admin Adapter

**Before (FastBlocks):**

```python
admin = await get_adapter("admin")
await admin.init()  # Auto-discovers models
```

**After (Oneiric):**

```python
# Option 1: As service
admin = await get_service("admin", provider="sqladmin")
await admin.register_models([User, Post, Comment])

# Option 2: As app feature
from fastblocks.admin import FastBlocksAdmin

admin = FastBlocksAdmin(app)
admin.register_models([User, Post, Comment])
```

### For FastBlocks Projects Using App Adapter

**Before (FastBlocks):**

```python
app = await get_adapter("app")
await app.init()
```

**After (Oneiric):**

```python
# Direct instantiation (not an adapter)
from fastblocks import FastBlocks

app = FastBlocks(name="myapp", style="bulma", theme="light")


# In lifespan
@asynccontextmanager
async def lifespan(app):
    # Initialize Oneiric runtime
    await orchestrator.start()
    yield
    await orchestrator.stop()
```

______________________________________________________________________

## Conclusion

**Key Decisions:**

1. ✅ **Models Adapter:** DO NOT PORT - Use SQLModel/Redis-OM/ODMantic directly
1. ⚠️ **Admin Adapter:** REARCHITECTURE - Move to Services domain (not adapters)
1. ⚠️ **App Adapter:** REARCHITECTURE - Move to Application core (not adapters)

**Rationale:**

- **Adapters = Infrastructure** (databases, caches, queues, HTTP clients)
- **Services = Application Logic** (admin panels, auth, business logic)
- **App Core = Framework** (application instance, lifespan, orchestration)

**Benefits:**

- ✅ Cleaner separation of concerns
- ✅ Better type safety (direct imports vs dynamic lookup)
- ✅ Simpler mental model (adapters = infrastructure only)
- ✅ Easier to understand and maintain
- ✅ Leverages modern ecosystem (Pydantic V2 everywhere)

**Next Steps:**

1. Document SQLModel/Redis-OM patterns in `docs/MODELS_GUIDE.md`
1. Create services domain for admin panels
1. Update FastBlocks to use app core (not adapter)
1. Add migration guide to ADAPTER_STRATEGY.md
