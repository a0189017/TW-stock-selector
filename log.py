"""Lightweight shared logger.

Network fetchers previously swallowed every error with `except Exception: pass`,
which made "candidates silently shrank" impossible to debug. They now log a
warning instead. By default logs go to stderr at WARNING level (so MCP stdout —
which carries the JSON protocol — stays clean); call enable_debug() from the CLI
--debug flag to see everything.
"""
import logging
import sys

_LOGGER_NAME = "tw_stock_selector"
_configured = False


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        _configured = True
    return logger


def enable_debug() -> None:
    get_logger().setLevel(logging.DEBUG)
