"""
Tests for src/logging_utils.py - Standardized logging configuration.

Tiny module, but free coverage.
"""

import pytest
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.logging_utils import get_logger, configure_logging


class TestGetLogger:

    def test_returns_logger(self):
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name(self):
        logger = get_logger("my.module.name")
        assert logger.name == "my.module.name"

    def test_different_names_different_loggers(self):
        a = get_logger("module_a")
        b = get_logger("module_b")
        assert a is not b
        assert a.name != b.name

    def test_same_name_same_logger(self):
        a = get_logger("same_name")
        b = get_logger("same_name")
        assert a is b


class TestConfigureLogging:

    def test_idempotent(self):
        """Calling configure_logging multiple times should not crash."""
        configure_logging()
        configure_logging()
        configure_logging()
