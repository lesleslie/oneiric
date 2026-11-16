"""Lazy-loaded file_transfer adapters.

The concrete adapters below are re-exported lazily (PEP 562). Importing
this package eagerly pulled in every sibling adapter in the family and
every client library they need, which cost seconds of import time -- and a consumer
importing a single concrete adapter paid that tax too, because Python
executes every parent package's ``__init__`` on the way down.

Resolution is now deferred to first attribute access, so
``from oneiric.adapters.file_transfer import SomeAdapter`` still works and
``import oneiric.adapters.file_transfer`` stays cheap.

See ``oneiric/adapters/_lazy.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "FTPFileTransferAdapter",
    "FTPFileTransferSettings",
    "HTTPArtifactAdapter",
    "HTTPArtifactSettings",
    "HTTPSUploadAdapter",
    "HTTPSUploadSettings",
    "SCPFileTransferAdapter",
    "SCPFileTransferSettings",
    "SFTPFileTransferAdapter",
    "SFTPFileTransferSettings",
]


if TYPE_CHECKING:
    from oneiric.adapters.file_transfer.ftp import (
        FTPFileTransferAdapter,
        FTPFileTransferSettings,
    )
    from oneiric.adapters.file_transfer.http_artifact import (
        HTTPArtifactAdapter,
        HTTPArtifactSettings,
    )
    from oneiric.adapters.file_transfer.http_upload import (
        HTTPSUploadAdapter,
        HTTPSUploadSettings,
    )
    from oneiric.adapters.file_transfer.scp import (
        SCPFileTransferAdapter,
        SCPFileTransferSettings,
    )
    from oneiric.adapters.file_transfer.sftp import (
        SFTPFileTransferAdapter,
        SFTPFileTransferSettings,
    )


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "FTPFileTransferAdapter": (
        "oneiric.adapters.file_transfer.ftp",
        "FTPFileTransferAdapter",
    ),
    "FTPFileTransferSettings": (
        "oneiric.adapters.file_transfer.ftp",
        "FTPFileTransferSettings",
    ),
    "HTTPArtifactAdapter": (
        "oneiric.adapters.file_transfer.http_artifact",
        "HTTPArtifactAdapter",
    ),
    "HTTPArtifactSettings": (
        "oneiric.adapters.file_transfer.http_artifact",
        "HTTPArtifactSettings",
    ),
    "HTTPSUploadAdapter": (
        "oneiric.adapters.file_transfer.http_upload",
        "HTTPSUploadAdapter",
    ),
    "HTTPSUploadSettings": (
        "oneiric.adapters.file_transfer.http_upload",
        "HTTPSUploadSettings",
    ),
    "SCPFileTransferAdapter": (
        "oneiric.adapters.file_transfer.scp",
        "SCPFileTransferAdapter",
    ),
    "SCPFileTransferSettings": (
        "oneiric.adapters.file_transfer.scp",
        "SCPFileTransferSettings",
    ),
    "SFTPFileTransferAdapter": (
        "oneiric.adapters.file_transfer.sftp",
        "SFTPFileTransferAdapter",
    ),
    "SFTPFileTransferSettings": (
        "oneiric.adapters.file_transfer.sftp",
        "SFTPFileTransferSettings",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported adapter on first attribute access (PEP 562)."""
    from oneiric.adapters._lazy import resolve_lazy_export

    value = resolve_lazy_export(__name__, name, _LAZY_EXPORTS)
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    """Advertise the lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
