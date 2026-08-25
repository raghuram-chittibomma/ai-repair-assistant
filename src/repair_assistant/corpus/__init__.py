"""The corpus layer: manifest, applicability, and integrity.

Phase 1 of the project. Describes and verifies the manufacturer document corpus
without redistributing any of it.
"""

from .applicability import Appliance, Serial, SerialRange, document_applies, model_matches
from .manifest import Document, Manifest, load, validate

__all__ = [
    "Appliance",
    "Document",
    "Manifest",
    "Serial",
    "SerialRange",
    "document_applies",
    "load",
    "model_matches",
    "validate",
]
