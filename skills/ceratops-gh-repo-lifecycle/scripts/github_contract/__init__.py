"""Shared deterministic GitHub contract state engine."""

from .compose_desired_state import compose_desired_state
from .collect_observed_states import collect_observed_states
from .compare_states import compare_states

__all__ = ["collect_observed_states", "compare_states", "compose_desired_state"]
