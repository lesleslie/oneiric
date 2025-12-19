# Oneiric Project Context

## Project Overview

Oneiric is a universal resolution layer for pluggable Python components with hot-swapping and remote manifest delivery capabilities. It provides explainable component resolution, lifecycle management, and remote delivery for Python 3.14+ runtimes. The project extracts the resolver/lifecycle core from ACB and turns it into a stand-alone platform.

### Key Features

- **Deterministic resolver**: Explicit selections with stack order, priorities, and registration order
- **Lifecycle orchestration**: Activation, health, bind, and cleanup with rollback capabilities
- **Config watchers & supervisor**: Auto-swap components using watchfiles/polling
- **Remote manifests + packaging**: CDN/file manifests with ED25519 signatures and SHA256 verification
- **Runtime orchestration**: Event dispatcher, DAG runtime, supervisor, and structured telemetry
- **Observability + ChatOps**: Structured logging, runtime health snapshots, and notification routing
- **Plugin/secrets tooling**: Entry-point discovery and secure secret caching

### Architecture Domains

- **Adapters**: Activity-aware swaps with built-in examples for Redis, Memcached, databases, etc.
- **Services**: Lifecycle-managed business services
- **Tasks**: Async runners with queue metadata and retry controls
- **Events**: Dispatcher with filters, fan-out policies, and retry mechanisms
- **Workflows**: DAG execution with checkpoints and telemetry
- **Actions**: Action bridge with kits for various operations

## Building and Running

### Prerequisites

- Python 3.13+ (as specified in `.python-version`)
- `uv` package manager (recommended)

### Development Setup

```bash
# Install dependencies
uv sync

# Install the package in development mode
uv add oneiric

# Run the demo
uv run python main.py

# Run tests
uv run pytest

# Check coverage
uv run pytest --cov=oneiric --cov-report=term
```

### Using the CLI

Oneiric provides a comprehensive command-line interface:

```bash
# Domain introspection
uv run python -m oneiric.cli list --domain adapter
uv run python -m oneiric.cli status --domain service
uv run python -m oneiric.cli explain status --domain service --key status

# Runtime controls
uv run python -m oneiric.cli pause
uv run python -m oneiric.cli drain
uv run python -m oneiric.cli health --probe

# Workflows and events
uv run python -m oneiric.cli workflow run --workflow fastblocks.workflows.fulfillment
uv run python -m oneiric.cli event emit --topic fastblocks.order.created

# Remote sync
uv run python -m oneiric.cli remote-sync --manifest docs/sample_remote_manifest.yaml
```

### Docker Deployment

The project includes a multi-stage Dockerfile and docker-compose configuration:

```bash
# Build and run with Docker
docker-compose up --build

# Or build the image directly
docker build -t oneiric .
docker run -d --name oneiric-container oneiric
```

## Development Conventions

### Code Structure

- **Core components** are organized in the `oneiric/` package
- **Configuration**: `pyproject.toml` manages dependencies and build settings
- **Logging**: Uses `structlog` with structured JSON output
- **Type checking**: Uses `mypy` with specific configurations in `mypy.ini`
- **Linting**: Uses `ruff` with auto-fix capabilities

### Testing

- Unit and integration tests located in the `tests/` directory
- Code coverage requirements enforced via `pytest-cov`
- Quality gates maintained with `crackerjack` tool

### Environment Variables

- `ONEIRIC_PROFILE`: Sets runtime profile (e.g., "serverless")
- `ONEIRIC_CONFIG`: Points to configuration directory
- `LOG_LEVEL`: Controls logging verbosity
- `OTEL_SERVICE_NAME`: Service name for OpenTelemetry

### Documentation

- Extensive documentation in the `docs/` directory
- Reference specs: architecture, telemetry, deployment guides
- Implementation plans and audit reports
- Examples and observability guides

## Project Configuration

### Main Configuration Files

- `pyproject.toml`: Project metadata, dependencies, and tool configurations
- `Dockerfile`: Multi-stage Docker build for production deployment
- `docker-compose.yml`: Full-stack deployment with monitoring stack
- `main.py`: Entry point for demo and basic orchestration
- `mypy.ini`: Type checking configuration
- `.envrc`: Direnv configuration using `layout uv`

### Dependency Management

The project uses `uv` for fast Python packaging and dependency management:

- Dependencies defined in `pyproject.toml`
- Lock file at `uv.lock`
- Multiple optional dependency groups for different integrations (databases, storage, messaging, etc.)

### Monitoring and Observability

- **Logging**: Structured logging with `structlog`
- **Metrics**: Prometheus integration with port 9090
- **Tracing**: OpenTelemetry support
- **Health checks**: Built-in health probe endpoints
- **Runtime telemetry**: Stored in `.oneiric_cache/runtime_telemetry.json`
- **Activity tracking**: SQLite-based domain activity store

## Special Considerations

### Security Features

- ED25519 signatures for remote manifest verification
- SHA256 digest validation
- Secure secret handling with caching
- Component isolation through lifecycle management

### Cloud-Native Features

- Serverless profile for Cloud Run deployment
- Remote manifest synchronization
- Configurable refresh intervals for remote updates
- Activity state persistence for pause/drain operations
- Health probes for container orchestration

### Performance Optimization

- Bytecode compilation with `UV_COMPILE_BYTECODE=1`
- Asynchronous design throughout the codebase
- Efficient component resolution algorithms
- Caching mechanisms for secrets and component metadata

## File Structure

```
oneiric/
├── adapters/           # Component adapters for various services
├── core/              # Core functionality (config, lifecycle, resolution)
├── domains/           # Domain-specific bridges (services, tasks, events, etc.)
├── runtime/           # Runtime orchestration and supervision
├── actions/           # Action kit implementations
├── remote/            # Remote manifest handling and security
├── cli.py             # Command-line interface
├── plugins.py         # Plugin system
└── __init__.py        # Package initialization
```

This project is production-ready with extensive documentation, testing, and monitoring capabilities. The architecture supports pluggable components with hot-swapping, remote configuration, and comprehensive observability.
