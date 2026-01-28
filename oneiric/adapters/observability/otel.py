"""OpenTelemetry storage adapter."""

from oneiric.adapters.observability.settings import OTelStorageSettings


class OTelStorageAdapter:
    """OpenTelemetry trace storage adapter.

    This adapter stores and retrieves OpenTelemetry traces with semantic search.
    Full implementation coming in Task 2.
    """

    def __init__(self, settings: OTelStorageSettings) -> None:
        """Initialize the OTel storage adapter.

        Args:
            settings: OTel storage configuration settings
        """
        self.settings = settings
