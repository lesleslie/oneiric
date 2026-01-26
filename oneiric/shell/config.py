"""Shell configuration using Oneiric patterns."""

from pydantic import BaseModel, Field


class ShellConfig(BaseModel):
    """Configuration for admin shell.

    Attributes:
        banner: Shell banner text displayed on startup
        display_prompt: Whether to display the interactive prompt
        table_max_width: Maximum width for table output
        show_tracebacks: Whether to show full tracebacks on errors
        auto_refresh_enabled: Enable auto-refresh for dynamic data
        auto_refresh_interval: Seconds between auto-refresh cycles
    """

    banner: str = Field(default="Oneiric Admin Shell", description="Shell banner text")
    display_prompt: bool = Field(default=True, description="Display interactive prompt")
    table_max_width: int = Field(
        default=120, ge=40, le=300, description="Maximum table width"
    )
    show_tracebacks: bool = Field(default=False, description="Show full tracebacks")
    auto_refresh_enabled: bool = Field(default=False, description="Enable auto-refresh")
    auto_refresh_interval: float = Field(
        default=5.0, ge=1.0, le=60.0, description="Auto-refresh interval in seconds"
    )
