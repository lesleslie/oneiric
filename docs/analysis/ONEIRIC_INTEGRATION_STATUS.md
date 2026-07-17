---
status: active
role: canonical
date: 2025-01-25
last_reviewed: 2026-07-17
superseded_by: null
blocks_on: []
topic: lifecycle
---

# Oneiric Integration Status: Task Queues & Messaging
**Date**: 2025-01-25
**Projects**: Mahavishnu, Session-Buddy, Oneiric
**Focus**: Oneiric MCP Server for adapter availability

---

## 📋 Current State

### ✅ Oneiric MCP Server Status

**IN PROGRESS** - Oneiric is getting its own MCP server!

**Current Configuration** (`/Users/les/Projects/oneiric/.mcp.json`):
```json
{
  "mcpServers": {
    "crackerjack": {
      "type": "http",
      "url": "http://localhost:8676/mcp"
    },
    "session-mgmt": {
      "type": "http",
      "url": "http://localhost:8678/mcp"
    }
  }
}
```

**Note**: This is Oneiric's **client** configuration (what servers Oneiric connects to).

The **Oneiric MCP Server** itself is **in progress** but not yet visible in the repo structure.

---

## 1. Oneiric Adapter System

### Available Adapters (from `oneiric/adapters/`):

**Database Adapters** ✅:
```python
oneiric/adapters/database/postgres.py  # PostgreSQL operations
oneiric/adapters/database/sqlite.py    # SQLite operations
```

**Vector Adapters** ✅:
```python
oneiric/adapters/vector/pgvector.py    # pgvector operations
oneiric/adapters/vector/qdrant.py      # Qdrant vector DB
```

**Utility Adapters** ✅:
```python
oneiric/adapters/bootstrap.py          # Adapter discovery
oneiric/adapters/config.py              # Configuration management
```

### Task Queue & Messaging?

**Current Status**: **NO** native task queue or messaging adapters in Oneiric.

**What Oneiric Does Provide**:
- ✅ Adapter lifecycle management (`init`, `health`, `cleanup`)
- ✅ Configuration layering (defaults → yaml → env vars)
- ✅ Settings validation via Pydantic
- ✅ Health check system
- ✅ Graceful shutdown hooks

**What It Doesn't Have**:
- ❌ Task queue adapters (Celery, RQ, Bull, etc.)
- ❌ Message queue adapters (RabbitMQ, Redis, Kafka, etc.)
- ❌ Job scheduling adapters
- ❌ Workflow orchestration adapters

---

## 2. Mahavishnu's Oneiric Integration

### Current Usage:

**Configuration** (`mahavishnu/core/config.py`):
```python
from mcp_common.client import MCPServerSettings

class MahavishnuSettings(MCPServerSettings):
    """Mahavishnu configuration using Oneiric patterns."""

    # Adapter enablement
    adapters: AdapterSettings = Field(
        default_factory=AdapterSettings
    )

    # Oneiric-style layered config
    model_config = SettingsConfigDict(
        env_prefix="MAHAVISHNU_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )
```

**What Mahavishnu Uses from Oneiric**:
1. ✅ **Settings Management**: Pydantic models with validation
2. ✅ **Layered Configuration**: Defaults → YAML → ENV
3. ✅ **Lifecycle Hooks**: Adapter initialization patterns
4. ❌ **Task Queues**: NOT integrated yet
5. ❌ **Messaging**: NOT integrated yet

### Mahavishnu's Current Messaging:

**Custom Implementation** (`mahavishnu/messaging/`):
```python
# repository_messenger.py
class RepositoryMessenger:
    """Send messages to repositories via workflow sweep."""

    async def send_repository_messages(
        self,
        repo_path: str,
        messages: list[RepositoryMessage]
    ) -> dict[str, Any]:
        """Send messages to repository (NOT using Oneiric)."""
```

**Key Point**: Mahavishnu has its own messaging system **not** using Oneiric adapters.

---

## 3. Proposed Oneiric MCP Server

### Expected Capabilities:

Based on Oneiric's adapter system, the MCP server should provide:

**Tool: `list_adapters`**
```python
@mcp.tool()
async def list_adapters(
    adapter_type: str | None = None
) -> list[dict[str, Any]]:
    """List available Oneiric adapters.

    Args:
        adapter_type: Filter by type (database, vector, etc.)

    Returns:
        List of adapter info with:
        - name: Adapter name
        - type: Adapter type
        - status: available/configured/error
        - capabilities: List of capabilities
        - settings_schema: Pydantic schema for settings
    """
```

**Tool: `get_adapter_info`**
```python
@mcp.tool()
async def get_adapter_info(
    adapter_name: str
) -> dict[str, Any]:
    """Get detailed information about an adapter.

    Returns:
        - description: Adapter description
        - class: Python class path
        - settings_class: Settings class
        - capabilities: Detailed capabilities
        - example_config: Example configuration
        - documentation_link: Link to docs
    """
```

**Tool: `validate_adapter_config`**
```python
@mcp.tool()
async def validate_adapter_config(
    adapter_name: str,
    config: dict[str, Any]
) -> dict[str, Any]:
    """Validate adapter configuration.

    Returns:
        - valid: Boolean
        - errors: List of validation errors
        - warnings: List of warnings
    """
```

**Tool: `test_adapter_connection`**
```python
@mcp.tool()
async def test_adapter_connection(
    adapter_name: str,
    config: dict[str, Any]
) -> dict[str, Any]:
    """Test adapter connection.

    Returns:
        - success: Boolean
        - latency_ms: Connection latency
        - error: Error details if failed
    """
```

### Resource: `adapters/{adapter_name}`

```python
@mcp.resource("adapters/{adapter_name}")
async def get_adapter_resource(adapter_name: str) -> dict[str, Any]:
    """Get adapter as a resource for monitoring."""
```

---

## 4. Integrating Oneiric Task Queues & Messaging

### Option A: Build Oneiric Adapters (Recommended)

**Task Queue Adapter**:
```python
# oneiric/adapters/queue/celery.py
class CeleryQueueAdapter:
    """Celery task queue adapter."""

    async def submit_task(
        self,
        task_name: str,
        args: list[Any],
        kwargs: dict[str, Any]
    ) -> str:
        """Submit task to queue."""

    async def get_task_status(
        self,
        task_id: str
    ) -> dict[str, Any]:
        """Get task status."""
```

**Message Queue Adapter**:
```python
# oneiric/adapters/messaging/redis.py
class RedisMessageAdapter:
    """Redis message queue adapter."""

    async def publish(
        self,
        queue: str,
        message: dict[str, Any]
    ) -> None:
        """Publish message to queue."""

    async def consume(
        self,
        queue: str,
        callback: Callable
    ) -> None:
        """Consume messages from queue."""
```

### Option B: Use Existing Systems

**Mahavishnu could integrate**:
1. **RQ (Redis Queue)**: Simple, Python-native
2. **Celery**: Feature-rich, widely adopted
3. **BullMQ**: Redis-based, great for Node.js interop
4. **AWS SQS**: Cloud-native, reliable

### Option C: Hybrid Approach

**Oneiric provides adapter interface**, Mahavishnu provides implementation:

```python
# mahavishnu/queue/oneiric_adapter.py
from oneiric.adapters.base import Adapter

class MahavishnuQueueAdapter(Adapter):
    """Mahavishnu's queue adapter using Oneiric patterns."""

    async def init(self) -> None:
        """Initialize queue connection."""
        # Use RQ/Celery/etc

    async def health(self) -> bool:
        """Check queue health."""

    async def cleanup(self) -> None:
        """Cleanup queue connections."""
```

---

## 5. Oneiric MCP Server Implementation Plan

### Phase 1: Discovery API (Week 1)

**Tools to Build**:
1. `list_adapters` - List all available adapters
2. `get_adapter_info` - Get adapter details
3. `validate_config` - Validate adapter settings

**Resources**:
1. `adapters://` - Enumerate all adapters
2. `adapters/{name}` - Get specific adapter

**Estimate**: 12 hours

### Phase 2: Configuration Management (Week 2)

**Tools to Build**:
1. `get_adapter_config` - Get current adapter config
2. `set_adapter_config` - Update adapter config
3. `test_adapter_connection` - Test adapter connectivity

**Estimate**: 8 hours

### Phase 3: Lifecycle Management (Week 3)

**Tools to Build**:
1. `initialize_adapter` - Initialize adapter
2. `check_adapter_health` - Health check
3. `cleanup_adapter` - Cleanup resources

**Estimate**: 8 hours

### Phase 4: Task Queue & Messaging Adapters (Week 4+)

**Adapters to Build**:
1. **CeleryQueueAdapter** - Celery integration
2. **RedisQueueAdapter** - RQ integration
3. **RedisMessageAdapter** - Pub/sub messaging

**Estimate**: 20 hours per adapter

---

## 6. Mahavishnu Integration with Oneiric MCP

### Current State:

**No Integration** ❌ - Mahavishnu doesn't query Oneiric for adapters yet.

### Proposed Integration:

**Step 1: Add Oneiric MCP Client**
```python
# mahavishnu/core/oneiric_client.py
from mcp_common.client import MCPClient

class OneiricAdapterClient:
    """Query Oneiric MCP server for available adapters."""

    def __init__(self, oneiric_mcp_url: str):
        self.client = MCPClient(oneiric_mcp_url)

    async def get_available_adapters(
        self,
        adapter_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get list of available adapters from Oneiric."""
        return await self.client.call_tool(
            "list_adapters",
            {"adapter_type": adapter_type}
        )
```

**Step 2: Use in Mahavishnu Initialization**
```python
# mahavishnu/core/app.py
class MahavishnuApp:
    async def _discover_adapters(self) -> None:
        """Discover available adapters from Oneiric."""
        adapters = await self.oneiric_client.get_available_adapters()

        for adapter_info in adapters:
            if adapter_info["name"] in self.settings.adapters:
                # Initialize adapter
                await self._initialize_adapter(adapter_info)
```

**Step 3: Dynamic Adapter Loading**
```python
async def _initialize_adapter(
    self,
    adapter_info: dict[str, Any]
) -> None:
    """Initialize adapter discovered from Oneiric."""
    adapter_name = adapter_info["name"]
    adapter_class = import_class(adapter_info["class"])

    # Get config from Oneiric
    config = await self.oneiric_client.get_adapter_config(adapter_name)

    # Initialize
    adapter = adapter_class(config)
    await adapter.init()

    setattr(self, adapter_name, adapter)
```

---

## 7. Task Queue & Messaging Architecture

### Recommended Architecture:

```
┌─────────────────────────────────────────────────────────┐
│                  Mahavishnu App                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │         Oneiric MCP Client                       │  │
│  │  - Query available adapters                     │  │
│  │  - Get adapter configs                          │  │
│  │  - Validate configurations                       │  │
│  └────────────┬─────────────────────────────────────┘  │
└───────────────┼───────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│            Oneiric MCP Server                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │     Adapter Discovery API                        │  │
│  │  - list_adapters()                               │  │
│  │  - get_adapter_info()                            │  │
│  │  - validate_config()                             │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
│  Available Adapters:                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Postgres   │  │   Pgvector   │  │  Celery     │ │
│  │   Database   │  │    Vector    │  │   Queue     │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  Redis Queue │  │Redis Message │  │   SQLite    │ │
│  │    (RQ)      │  │   (Pub/Sub)  │  │   Database  │ │
│  └──────────────┘  └──────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              Backend Systems                            │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │  PostgreSQL  │  │    Redis     │  │  Celery     │  │
│  │   + pgvector │  │    (RQ)      │  │  Workers    │  │
│  └──────────────┘  └──────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Message Flow:

**1. Adapter Discovery**
```
Mahavishnu → Oneiric MCP → list_adapters() → ["postgres", "celery", "redis"]
```

**2. Task Submission**
```
Mahavishnu → CeleryQueueAdapter → Celery → Task Queued
```

**3. Message Publishing**
```
Mahavishnu → RedisMessageAdapter → Redis Pub/Sub → Subscribers
```

**4. Result Polling**
```
Mahavishnu → CeleryQueueAdapter → get_task_status() → Result
```

---

## 8. FastBlocks & SplashSand Integration

### FastBlocks with Oneiric Task Queues:

**Use Case: Block Processing Pipeline**
```python
# fastblocks/orchestration/pipeline.py
from oneiric.adapters.queue.celery import CeleryQueueAdapter

class FastBlocksPipeline:
    """Process blocks through Celery pipeline."""

    def __init__(self, queue_adapter: CeleryQueueAdapter):
        self.queue = queue_adapter

    async def process_block(
        self,
        block: FastBlock,
        pipeline_steps: list[str]
    ) -> str:
        """Submit block for processing."""
        # Submit to Celery queue
        task_id = await self.queue.submit_task(
            task_name="process_fastblock",
            args=[block.to_dict()],
            kwargs={"steps": pipeline_steps}
        )

        return task_id

    async def get_status(
        self,
        task_id: str
    ) -> dict[str, Any]:
        """Check block processing status."""
        return await self.queue.get_task_status(task_id)
```

### SplashSand with Oneiric Messaging:

**Use Case: Sandcastle Events**
```python
# splashsand/orchestration/events.py
from oneiric.adapters.messaging.redis import RedisMessageAdapter

class SplashSandEvents:
    """Handle sandcastle events via Redis pub/sub."""

    def __init__(self, message_adapter: RedisMessageAdapter):
        self.messaging = message_adapter

    async def publish_deployment_event(
        self,
        sandcastle: str,
        event: str,
        data: dict[str, Any]
    ) -> None:
        """Publish deployment event."""
        await self.messaging.publish(
            queue=f"sandcastle:{sandcastle}:events",
            message={
                "event": event,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def subscribe_to_events(
        self,
        sandcastle: str,
        callback: Callable
    ) -> None:
        """Subscribe to sandcastle events."""
        await self.messaging.consume(
            queue=f"sandcastle:{sandcastle}:events",
            callback=callback
        )
```

---

## 9. Implementation Roadmap

### Phase 1: Oneiric MCP Server (Week 1-2)

**Tasks**:
1. [ ] Create `oneiric/mcp/server.py`
2. [ ] Implement `list_adapters` tool
3. [ ] Implement `get_adapter_info` tool
4. [ ] Implement `validate_config` tool
5. [ ] Add adapter discovery resources
6. [ ] Test with Mahavishnu client

**Estimate**: 20 hours

### Phase 2: Mahavishnu Integration (Week 3)

**Tasks**:
1. [ ] Create `MahavishnuApp.oneiric_client`
2. [ ] Implement adapter discovery
3. [ ] Add dynamic adapter loading
4. [ ] Update configuration to use Oneiric
5. [ ] Test adapter initialization

**Estimate**: 12 hours

### Phase 3: Task Queue Adapters (Week 4-5)

**Tasks**:
1. [ ] Create `oneiric/adapters/queue/base.py`
2. [ ] Implement `CeleryQueueAdapter`
3. [ ] Implement `RedisQueueAdapter` (RQ)
4. [ ] Add queue health checks
5. [ ] Test task submission/status

**Estimate**: 24 hours

### Phase 4: Messaging Adapters (Week 6-7)

**Tasks**:
1. [ ] Create `oneiric/adapters/messaging/base.py`
2. [ ] Implement `RedisMessageAdapter`
3. [ ] Add pub/sub support
4. [ ] Test message publish/consume
5. [ ] Add message persistence

**Estimate**: 20 hours

### Phase 5: FastBlocks Integration (Week 8)

**Tasks**:
1. [ ] Integrate Celery for block processing
2. [ ] Add task status monitoring
3. [ ] Implement block pipeline orchestration
4. [ ] Test with real blocks

**Estimate**: 16 hours

### Phase 6: SplashSand Integration (Week 9)

**Tasks**:
1. [ ] Integrate Redis for event messaging
2. [ ] Add deployment event publishing
3. [ ] Implement event subscription
4. [ ] Test with sandcastle deployments

**Estimate**: 16 hours

---

## 10. Key Recommendations

### ✅ DO THIS:

1. **Build Oneiric MCP Server First** (Week 1-2)
   - Foundation for everything else
   - Enables adapter discovery
   - Simple API, high value

2. **Use Redis for Task Queues** (Week 4)
   - Simpler than Celery
   - Great for Mahavishnu's needs
   - Easy to scale later

3. **Use Redis Pub/Sub for Messaging** (Week 6)
   - Lightweight, fast
   - Good for event-driven architecture
   - Easy to monitor

### ⚠️ CONSIDER:

1. **Celery if You Need** (Week 5)
   - Complex task dependencies
   - Scheduled tasks
   - Distributed worker pools

2. **Kafka if You Need** (Later)
   - High-throughput messaging
   - Event sourcing
   - Stream processing

### ❌ DON'T DO YET:

1. **Don't build custom queue system**
   - Use Redis/Celery instead
   - Battle-tested, well-documented

2. **Don't over-engineer**
   - Start with Redis pub/sub
   - Upgrade only if needed

---

## 11. Summary

### Current State:
- ✅ **Oneiric**: Database & vector adapters working
- ✅ **Mahavishnu**: Using Oneiric config patterns
- ⚠️ **Oneiric MCP Server**: In progress (not visible yet)
- ❌ **Task Queues**: Not integrated yet
- ❌ **Messaging**: Not integrated yet

### What Needs to Happen:
1. **Oneiric MCP Server** (20 hours) - Adapter discovery API
2. **Mahavishnu Integration** (12 hours) - Query Oneiric for adapters
3. **Queue Adapters** (24 hours) - Redis/Celery for task queues
4. **Messaging Adapters** (20 hours) - Redis pub/sub for events
5. **FastBlocks Integration** (16 hours) - Use queues for block processing
6. **SplashSand Integration** (16 hours) - Use messaging for events

### Total Estimate: 108 hours (13 weeks)

### Priority Order:
1. Oneiric MCP Server (foundation)
2. Mahavishnu integration (enables discovery)
3. Redis queue adapter (simple task queues)
4. Redis messaging adapter (event system)
5. FastBlocks integration (real use case)
6. SplashSand integration (real use case)

**Recommendation**: Start with Oneiric MCP Server this week! 🚀
