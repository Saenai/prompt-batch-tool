"""Backward-compatible public batch API.

New code may import from :mod:`prompt_batch` directly.  This module remains so
existing integrations using ``prompt_batch.engine`` do not break.
"""

from .domain import BatchOptions, ValidationReport
from .preparation import validate_batch
from .runner import run_batch

__all__ = ["BatchOptions", "ValidationReport", "run_batch", "validate_batch"]
