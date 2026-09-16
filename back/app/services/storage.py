"""Read database-backed documents and legacy files during the storage migration."""
from pathlib import Path

from app.core.config import get_settings
from app.db.models.traite import TraiteDocument


def read_legacy_content(path: str, expected_size: int) -> bytes:
    """Read only files inside UPLOAD_DIR; reject missing or truncated legacy data."""
    root = Path(get_settings().upload_dir).resolve()
    source = Path(path).resolve()
    if not source.is_relative_to(root):
        raise ValueError("Legacy document path is outside UPLOAD_DIR.")
    if expected_size < 0:
        raise ValueError("Legacy document has an invalid recorded size.")
    with source.open("rb") as stream:
        content = stream.read(expected_size + 1)
    if len(content) != expected_size:
        raise ValueError("Legacy document size does not match its recorded metadata.")
    return content


def read_document_content(document: TraiteDocument) -> bytes:
    """Use with a synchronous session, or explicitly load content in async callers."""
    if document.content is not None:
        return document.content
    if document.fichier_chemin is None:
        raise ValueError("Document has no stored content.")
    return read_legacy_content(document.fichier_chemin, document.taille_octets)
