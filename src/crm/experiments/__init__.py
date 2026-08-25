"""Leakage-resistant, auditable experiment protocol."""

from .config import ExperimentConfig, load_config
from .runner import run_locked_test, run_selection

__all__ = ["ExperimentConfig", "load_config", "run_locked_test", "run_selection"]
