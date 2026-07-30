"""Observed-state collectors for the GitHub contract engine."""

from .local_repository import collect_local_repository
from .organization import collect_organization
from .registries import collect_registries
from .repository import collect_repository

__all__ = [
    "collect_local_repository",
    "collect_organization",
    "collect_registries",
    "collect_repository",
]
