# syntax=docker/dockerfile:1.4

#######################################
# Stage 1: Builder
#######################################
FROM python:3.14-slim AS builder

LABEL maintainer="oneiric-team"
LABEL description="Oneiric - Universal Resolution Layer (Builder Stage)"

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set environment variables for build
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Set working directory
WORKDIR /build

# Copy dependency files first (layer caching optimization)
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev dependencies)
# This creates a virtual environment at /build/.venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY oneiric ./oneiric
COPY README.md LICENSE ./

# Build wheel package
RUN uv build --wheel --out-dir /build/dist

#######################################
# Stage 2: Runtime
#######################################
FROM python:3.14-slim AS runtime

LABEL maintainer="oneiric-team"
LABEL description="Oneiric - Universal Resolution Layer (Production Runtime)"
LABEL version="0.1.0"

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user and group
RUN groupadd -r oneiric --gid=1000 && \
    useradd -r -g oneiric --uid=1000 --home-dir=/app --shell=/sbin/nologin oneiric

# Set working directory
WORKDIR /app

# Install uv for runtime (needed for dependency installation)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install oneiric from wheel into system Python
RUN uv pip install --system /tmp/*.whl && \
    rm /tmp/*.whl

# Create required directories with correct permissions
RUN mkdir -p /app/.oneiric_cache /app/logs && \
    chown -R oneiric:oneiric /app

# Copy default settings (optional - can be overridden by volume mount)
# Uncomment if you want to include default settings in the image
# COPY --chown=oneiric:oneiric settings /app/settings

# Switch to non-root user
USER oneiric

# Expose default ports
# 8000: Application port (if running HTTP server)
# 9090: Prometheus metrics port
EXPOSE 8000 9090

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    ONEIRIC_CONFIG=/app/settings \
    ONEIRIC_CACHE_DIR=/app/.oneiric_cache \
    LOG_LEVEL=INFO \
    OTEL_SERVICE_NAME=oneiric

# Health check
# Runs every 30 seconds, times out after 10 seconds
# Gives the container 40 seconds to start before first check
# Fails after 3 consecutive failures
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -m oneiric.cli health --probe || exit 1

# Default command: Run orchestrator with remote manifest syncing
# Override with your own command or use docker-compose
CMD ["python", "-m", "oneiric.cli", "orchestrate", \
     "--manifest", "/app/settings/manifest.yaml", \
     "--refresh-interval", "120"]

# Alternative commands (examples):
# CMD ["python", "-m", "oneiric.cli", "remote-sync", "--manifest", "/app/settings/manifest.yaml", "--watch"]
# CMD ["python", "-m", "oneiric.cli", "list", "--domain", "adapter"]
# CMD ["python", "-m", "oneiric.cli", "health", "--probe", "--json"]
