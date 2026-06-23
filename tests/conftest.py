"""Pytest configuration and shared fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """DPM repository root."""
    return Path(__file__).resolve().parent.parent
