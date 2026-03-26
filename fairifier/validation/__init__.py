"""Output format validation shared by CLI and evaluation."""

from .metadata_json_format import (
    REQUIRED_FIELDS_BY_SHEET,
    check_metadata_json_output,
)

__all__ = [
    "REQUIRED_FIELDS_BY_SHEET",
    "check_metadata_json_output",
]
